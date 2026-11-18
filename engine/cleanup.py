"""Clean-up review: other versions of projects that already have a chosen (kept) version.

Nothing is deleted here. A version you tick is renamed into a holding folder (instant, same disk) and can be put
back with one click. Each other version is compared with the kept one:
  - files that are not in the kept version (same relative path + size counts as "in the kept version")
  - git commits the kept version does not have (branch tips checked with `git cat-file`, 10 s limit per call)
Groups:  safe = nothing here that the kept version lacks;  probably = only a handful of small differences;
         different = has files or commits the kept version does not have (never pre-ticked).
Never offered: protected projects, anything under the projects home or Desktop, links."""
import os, re, json, time, subprocess, shutil
from . import platforms

REB = {"node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", "target", ".turbo", ".cache", ".git"}
SCHEMA = "CREATE TABLE IF NOT EXISTS cleanup_held(held TEXT PRIMARY KEY, orig TEXT, by TEXT, t REAL, restored REAL)"
_NORM = re.compile(r"(?i)\s*\(from[^)]*\)(_\d+)?|_(broken|corrupted|old|local|pre_restore|working_backup|backup)[\w-]*|[-_ ]?(main|master|\d{8}_\d{4,6}|\d{10})$|\s*\(\d+\)|\s+\d$")


def norm(name):
    return _NORM.sub("", name).lower().strip(" -_")


def home(cfg):
    return getattr(cfg, "projects_home", None)


def holding(cfg):
    return os.path.expanduser((getattr(cfg, "data", None) or {}).get("cleanup_holding", "~/Documents/Organized/_Deleted projects"))


def _git(p, *a):
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", p, *a], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def _info(p):
    sig, n, size, newest, cloud = {}, 0, 0, 0, 0
    for dp, dn, fn in os.walk(p):
        dn[:] = [x for x in dn if x not in REB and not os.path.islink(os.path.join(dp, x))]
        for f in fn:
            if f == ".DS_Store":
                continue
            q = os.path.join(dp, f)
            try:
                st = os.lstat(q)
            except OSError:
                continue
            n += 1; size += st.st_size; newest = max(newest, st.st_mtime); cloud += bool(platforms.cloud_only(st))
            sig[q[len(p) + 1:]] = st.st_size
    return {"path": p, "name": os.path.basename(p), "files": n, "size": size, "changed": newest, "cloud": cloud, "sig": sig,
            "has_git": os.path.isdir(os.path.join(p, ".git"))}


def _git_compare(copy, keeper):
    """-> (text, missing) ; missing: number of branch tips the kept version lacks, None if unknown."""
    if not copy["has_git"] or not shutil.which("git"):
        return "no git", 0
    tips = _git(copy["path"], "for-each-ref", "--format=%(objectname)")
    head = _git(copy["path"], "rev-parse", "HEAD")
    n = _git(copy["path"], "rev-list", "--count", "--all") or "some"
    if "TIMEOUT" in (tips, head, n):
        return "git history not readable", None
    shas = {s for s in ((tips or "").split() + [head or ""]) if s}
    if not shas:
        return "git with no commits", 0
    if not keeper["has_git"]:
        return f"{n} commits; the kept version has no git", len(shas)
    miss = 0
    for s in shas:
        r = _git(keeper["path"], "cat-file", "-e", s + "^{commit}")
        if r == "TIMEOUT":
            return "git history not readable", None
        miss += r is None
    return (f"{n} commits, all in the kept version" if not miss else f"{n} commits; {miss} branch tip(s) NOT in the kept version"), miss


def analyse(cfg, cat, progress=lambda done, total, step: None):
    from .sorter import _under
    if not home(cfg):
        return {"at": time.time(), "families": [], "unrelated": [], "holding": holding(cfg),
                "note": "Set a projects folder (projects_home) in your profile to compare project versions."}
    H, hm, hold = os.path.expanduser("~"), home(cfg).rstrip("/") + "/", holding(cfg).rstrip("/") + "/"
    paths = [r[0] for r in cat.db.execute("SELECT path FROM files WHERE unit='project' AND path NOT LIKE 'uo://%' ORDER BY path")]
    keepers = [p for p in paths if p.startswith(hm) and "/" not in p[len(hm):] and os.path.isdir(p)]
    from .projindex import MARK
    for k in list(keepers):  # a project made of parts (frontend, backend, an older copy): each part is compared on its own
        for sub in sorted(os.listdir(k)):
            q = os.path.join(k, sub)
            if os.path.isdir(q) and not os.path.islink(q) and not sub.startswith(".") and (
                    os.path.exists(os.path.join(q, ".git")) or any(os.path.exists(os.path.join(q, m)) for m in MARK)):
                keepers.append(q)
    cands = [p for p in paths if not p.startswith(H + "/Desktop/") and not p.startswith(hold) and not _under(p, cfg.protect)
             and os.path.isdir(p) and not os.path.islink(p)]
    K = []
    for i, p in enumerate(keepers):
        progress(i, len(keepers) + len(cands), os.path.basename(p)); K.append(_info(p))
    byname = {}
    for k in K:
        byname.setdefault(norm(k["name"]), k)
    fams, unrelated = {}, 0
    for i, p in enumerate(cands):
        progress(len(keepers) + i, len(keepers) + len(cands), os.path.basename(p))
        c = _info(p)
        k = byname.get(norm(c["name"]))
        if not k and c["files"] >= 30:  # same content under another name
            best = max(K, key=lambda x: sum(1 for r, s in c["sig"].items() if x["sig"].get(r) == s), default=None)
            if best and sum(1 for r, s in c["sig"].items() if best["sig"].get(r) == s) >= max(30, 0.6 * c["files"]):
                k = best
        if not k:
            unrelated += 1; continue
        only = [(r, s) for r, s in c["sig"].items() if s > 0 and k["sig"].get(r) != s]
        shared = sum(1 for r, s in c["sig"].items() if s > 0 and k["sig"].get(r) == s)
        gtxt, miss = _git_compare(c, k)
        if not only and miss == 0:
            grp, why = "safe", ("empty" if not c["files"] else "every file is also in the kept version")
        elif miss == 0 and len(only) <= 5:
            grp, why = "probably", f"{len(only)} file(s) differ from the kept version"
        else:
            grp = "different"
            why = "; ".join(x for x in ("same name but no file in common: probably a different project" if only and not shared else "",
                                        f"{len(only):,} file(s) not in the kept version" if only else "",
                                        "has git commits the kept version lacks" if miss else "",
                                        "git could not be compared" if miss is None else "") if x)
        fams.setdefault(k["path"], {"keeper": {x: k[x] for x in ("path", "name", "files", "size", "changed")}, "versions": []})["versions"].append(
            {**{x: c[x] for x in ("path", "name", "files", "size", "changed", "cloud")}, "only": len(only),
             "only_bytes": sum(s for _, s in only), "sample": [r for r, _ in sorted(only, key=lambda t: -t[1])[:5]],
             "git": gtxt, "group": grp, "why": why})
    out = sorted(fams.values(), key=lambda f: -len(f["versions"]))
    for f in out:
        f["versions"].sort(key=lambda v: ({"safe": 0, "probably": 1, "different": 2}[v["group"]], v["name"].lower()))
    res = {"at": time.time(), "families": out, "unrelated": unrelated, "holding": holding(cfg)}
    cat.set_meta("cleanup_cache", res)
    return res


def held(cat):
    cat.db.execute(SCHEMA)
    return [dict(zip(("held", "orig", "by", "t"), r)) for r in cat.db.execute("SELECT held, orig, by, t FROM cleanup_held WHERE restored IS NULL ORDER BY t DESC")
            if os.path.isdir(r[0])]


def _in_use(path):
    try:
        out = subprocess.run(["lsof", "-Fn"], capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return True
    return any(l[1:] == path or l[1:].startswith(path + "/") for l in out.splitlines() if l.startswith("n/"))


def hold(cfg, cat, path, by):
    """Rename one reviewed version into the holding folder. Only paths from the last analysis are accepted."""
    cat.db.execute(SCHEMA)
    known = {v["path"] for f in (cat.get_meta("cleanup_cache") or {}).get("families", []) for v in f["versions"]}
    from .sorter import _under
    if path not in known or _under(path, cfg.protect) or path.startswith(os.path.expanduser("~/Desktop/")):
        return {"path": path, "ok": False, "why": "not in the review"}
    if os.path.islink(path) or not os.path.isdir(path):
        return {"path": path, "ok": False, "why": "no longer there"}
    if _in_use(path):
        return {"path": path, "ok": False, "why": "in use by a running program; close it and try again"}
    hd = holding(cfg); os.makedirs(hd, exist_ok=True)
    if os.stat(hd).st_dev != os.stat(path).st_dev:
        return {"path": path, "ok": False, "why": "holding folder is on another disk"}
    dest, i = os.path.join(hd, os.path.basename(path)), 1
    while os.path.lexists(dest):
        i += 1; dest = os.path.join(hd, f"{os.path.basename(path)} ~{i}")
    os.rename(path, dest)
    cat.db.execute("INSERT OR REPLACE INTO cleanup_held VALUES(?,?,?,?,NULL)", (dest, path, by, time.time())); cat.db.commit()
    _log({"action": "hold", "orig": path, "held": dest, "by": by})
    return {"path": path, "ok": True, "why": "moved to the holding folder"}


def restore(cfg, cat, held_path, by):
    cat.db.execute(SCHEMA)
    r = cat.db.execute("SELECT orig FROM cleanup_held WHERE held=? AND restored IS NULL", (held_path,)).fetchone()
    if not r or not os.path.isdir(held_path):
        return {"ok": False, "why": "not in the holding folder"}
    if os.path.lexists(r[0]):
        return {"ok": False, "why": "something else is now at the old place: " + r[0]}
    os.makedirs(os.path.dirname(r[0]), exist_ok=True)
    os.rename(held_path, r[0])
    cat.db.execute("UPDATE cleanup_held SET restored=? WHERE held=?", (time.time(), held_path)); cat.db.commit()
    _log({"action": "restore", "orig": r[0], "held": held_path, "by": by})
    return {"ok": True, "why": "put back at " + r[0]}


def _log(d):
    from .config import DATA as ROOT
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    with open(os.path.join(ROOT, "logs", "cleanup.jsonl"), "a") as f:
        f.write(json.dumps({**d, "t": time.time()}, ensure_ascii=False) + "\n")
