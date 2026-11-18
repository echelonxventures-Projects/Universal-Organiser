"""Stop iCloud syncing working projects - without moving or renaming anything.

macOS (File Provider) honours the attribute  com.apple.fileprovider.ignore#P = 1  on a folder: iCloud then stops
syncing that folder and everything in it (checked with `fileproviderctl evaluate` -> isExcludedFromSync = 1).
The folder keeps its name and path, so editors, terminals, Docker and scripts are unaffected.

For each project, in order, stopping at the first problem:
  1. every iCloud-only file is downloaded (Apple's startDownloadingUbiquitousItem) and checked to be on this Mac
  2. nothing is using it (open files / terminals via lsof, running Docker containers via docker inspect)
  3. uncommitted git changes are reported (never touched)
  4. the attribute is set, then iCloud is asked to confirm the exclusion; otherwise it is rolled back
Undo removes the attribute; iCloud then syncs the project again. Protected projects are never touched."""
import os, re, json, time, subprocess, shutil
from . import platforms
from .plugins.macos_vision import HELPER

ATTR = "com.apple.fileprovider.ignore#P"
LOGS = None
SCHEMA = "CREATE TABLE IF NOT EXISTS project_sync(path TEXT PRIMARY KEY, excluded REAL, by TEXT, warnings TEXT, undone REAL)"
SKIP_WALK = {".git"}
STATUSES = ("Active", "Paused", "Completed", "Experiment")
STATUS_SCHEMA = "CREATE TABLE IF NOT EXISTS project_status(path TEXT PRIMARY KEY, status TEXT, by TEXT, t REAL)"


def set_status(cfg, cat, path, status, by):
    """Working status of a project: kept in the catalogue and shown as a Finder tag on the folder.
    The folder is never renamed or moved for a status change. Tags you set yourself are kept."""
    from . import tags as TG
    cat.db.execute(STATUS_SCHEMA)
    if status not in STATUSES + ("",):
        return {"ok": False, "why": "unknown status"}
    if not os.path.isdir(path) or os.path.islink(path):
        return {"ok": False, "why": "not a folder"}
    from .sorter import _under
    if _under(path, cfg.protect):
        return {"ok": False, "why": "protected: never touched"}
    keep = [t for t in TG.read(path) if t.split("\n")[0] not in STATUSES]
    tagged = TG.write(path, keep + ([status] if status else []))
    if status:
        cat.db.execute("INSERT OR REPLACE INTO project_status VALUES(?,?,?,?)", (path, status, by, time.time()))
    else:
        cat.db.execute("DELETE FROM project_status WHERE path=?", (path,))
    cat.db.commit()
    _log({"action": "status", "path": path, "status": status, "by": by})
    return {"ok": True, "why": status or "no status", "tagged": tagged}


def _synced_roots(cfg):
    h = os.path.expanduser("~")
    roots = [h + "/Desktop", h + "/Documents"] + [r for r in cfg.roots if "Mobile Documents" in r]
    return [r + "/" for r in roots]


def eligible(cfg, path):
    from .sorter import _under
    if _under(path, cfg.protect):
        return False, "protected: never touched"
    if not any(path.startswith(r) for r in _synced_roots(cfg)):
        return False, "not in an iCloud-synced folder"
    if os.path.islink(path) or not os.path.isdir(path):
        return False, "not a folder"
    return True, None


def is_excluded(path):
    r = subprocess.run(["/usr/bin/xattr", "-p", ATTR, path], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() not in ("", "0")


def icloud_says_excluded(path):
    r = subprocess.run(["/usr/bin/fileproviderctl", "evaluate", path], capture_output=True, text=True, timeout=60)
    m = re.search(r"isExcludedFromSync = (\d)", r.stdout)
    return None if not m else m.group(1) == "1"


def cloud_files(path):
    out, size = [], 0
    for dp, dn, fn in os.walk(path):
        dn[:] = [d for d in dn if not os.path.islink(os.path.join(dp, d))]
        for f in fn:
            p = os.path.join(dp, f)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if platforms.cloud_only(st):
                out.append(p); size += st.st_size
    return out, size


def git_state(path):
    if not os.path.isdir(os.path.join(path, ".git")) or not shutil.which("git"):
        return None
    # 10 s per call: git waits forever on history objects that iCloud has offloaded; that must not stall anything
    g = lambda *a: subprocess.run(["git", "--no-optional-locks", "-C", path, *a], capture_output=True, text=True, timeout=10).stdout.strip()
    try:
        dirty = len([l for l in g("status", "--porcelain").splitlines() if l.strip()])
        return {"branch": g("rev-parse", "--abbrev-ref", "HEAD"), "dirty": dirty, "last_commit": g("log", "-1", "--format=%cI"),
                "remote": bool(g("remote"))}
    except subprocess.TimeoutExpired:
        return {"error": "git history not readable (parts are in iCloud only)"}


def users_of(paths):
    """Which processes / containers use any of these folders right now."""
    found = {p: [] for p in paths}
    if shutil.which("lsof"):
        try:
            out = subprocess.run(["lsof", "-nP", "-F", "pcn"], capture_output=True, text=True, timeout=60).stdout
            cmd = None
            for line in out.splitlines():
                if line.startswith("c"):
                    cmd = line[1:]
                elif line.startswith("n"):
                    n = line[1:]
                    for p in paths:
                        if n == p or n.startswith(p + "/"):
                            if cmd not in found[p]:
                                found[p].append(cmd)
        except subprocess.TimeoutExpired:
            pass
    if shutil.which("docker"):
        try:
            ids = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, timeout=20).stdout.split()
            if ids:
                info = subprocess.run(["docker", "inspect", "-f", "{{.Name}}|{{range .Mounts}}{{.Source}};{{end}}", *ids],
                                      capture_output=True, text=True, timeout=30).stdout
                for line in info.splitlines():
                    name, _, srcs = line.partition("|")
                    for s in srcs.split(";"):
                        for p in paths:
                            if s and (s == p or s.startswith(p + "/") or p.startswith(s + "/")):
                                found[p].append("docker" + name)
        except subprocess.TimeoutExpired:
            pass
    return found


def listing(cfg, cat, deep=False):
    cat.db.execute(SCHEMA)
    log = {r[0]: dict(zip(("path", "excluded", "by", "warnings", "undone"), r)) for r in cat.db.execute("SELECT * FROM project_sync")}
    cat.db.execute(STATUS_SCHEMA)
    stat = dict(cat.db.execute("SELECT path, status FROM project_status"))
    out = []
    for path, size, n in cat.db.execute("SELECT path, size, inner_count FROM files WHERE unit IN ('project','protected') AND path NOT LIKE 'uo://%' ORDER BY path"):
        ok, why = eligible(cfg, path)
        d = {"path": path, "name": os.path.basename(path), "size": size, "files": n, "eligible": ok, "why": why,
             "excluded": is_excluded(path) if os.path.isdir(path) and not why == "protected: never touched" else False,
             "log": log.get(path), "status": stat.get(path, ""), "group": os.path.basename(os.path.dirname(path))}
        if deep and ok:
            cf, cs = cloud_files(path)
            d.update(cloud_files=len(cf), cloud_bytes=cs, git=git_state(path))
            newest = 0
            for dp, dn, fn in os.walk(path):
                dn[:] = [x for x in dn if x not in ("node_modules", ".git", ".venv", "venv")]
                for f in fn[:100]:
                    try:
                        newest = max(newest, os.lstat(os.path.join(dp, f)).st_mtime)
                    except OSError:
                        pass
            d["changed"] = newest
        out.append(d)
    return out


def download(path, progress=lambda m: None, max_wait=None):
    """Ask iCloud for every iCloud-only file in the folder, then wait until all are on this Mac."""
    files, size = cloud_files(path)
    if not files:
        return True, 0
    if not os.path.exists(HELPER):
        return False, len(files)
    for i in range(0, len(files), 500):
        subprocess.run([HELPER, "download"], input="\n".join(files[i:i + 500]) + "\n", capture_output=True, text=True, timeout=600)
    max_wait = max_wait or min(6 * 3600, 600 + len(files) // 5 + size // 1_000_000)
    t0, left = time.time(), files
    while time.time() - t0 < max_wait:
        left = [p for p in left if os.path.exists(p) and platforms.cloud_only(os.lstat(p))]
        progress(f"downloading from iCloud: {len(files) - len(left):,} of {len(files):,} files")
        if not left:
            return True, 0
        time.sleep(5)
    return False, len(left)


def stop_sync(cfg, cat, path, by, progress=lambda m: None, wait=None):
    """The whole safe sequence for one project. Returns a result dict; never leaves a half-done state."""
    cat.db.execute(SCHEMA)
    ok, why = eligible(cfg, path)
    if not ok:
        return {"path": path, "ok": False, "why": why}
    if is_excluded(path):
        return {"path": path, "ok": True, "why": "already not syncing"}
    progress("checking files")
    done, left = download(path, progress, wait)
    if not done:
        return {"path": path, "ok": False, "why": f"{left:,} files are still downloading from iCloud; nothing changed. Try again later."}
    left_now = len(cloud_files(path)[0])
    if left_now:
        return {"path": path, "ok": False, "why": f"{left_now} files are not on this Mac yet; nothing changed."}
    progress("checking nothing is using it")
    users = users_of([path])[path]
    if users:
        return {"path": path, "ok": False, "why": "in use by " + ", ".join(sorted(set(users))[:6]) + "; close them and try again. Nothing changed."}
    warnings = []
    g = git_state(path)
    if g and g.get("dirty"):
        warnings.append(f"{g['dirty']} uncommitted git changes (left as they are)")
    if g and not g.get("remote"):
        warnings.append("git has no remote: after this, Time Machine is its only backup")
    if not g:
        warnings.append("no git: after this, Time Machine is its only backup")
    progress("telling iCloud to stop syncing it")
    if subprocess.run(["/usr/bin/xattr", "-w", ATTR, "1", path], capture_output=True).returncode != 0:
        return {"path": path, "ok": False, "why": "could not set the marker; nothing changed"}
    confirmed = None
    for _ in range(20):
        confirmed = icloud_says_excluded(path)
        if confirmed:
            break
        time.sleep(2)
    if not confirmed:
        subprocess.run(["/usr/bin/xattr", "-d", ATTR, path], capture_output=True)
        return {"path": path, "ok": False, "why": "iCloud did not confirm the exclusion; the marker was removed again (nothing changed)"}
    cat.db.execute("INSERT OR REPLACE INTO project_sync VALUES(?,?,?,?,NULL)", (path, time.time(), by, json.dumps(warnings)))
    cat.db.commit()
    _log({"action": "stop-sync", "path": path, "by": by, "warnings": warnings})
    return {"path": path, "ok": True, "why": "iCloud no longer syncs it", "warnings": warnings}


def resume_sync(cfg, cat, path, by):
    cat.db.execute(SCHEMA)
    if not is_excluded(path):
        return {"path": path, "ok": True, "why": "already syncing"}
    subprocess.run(["/usr/bin/xattr", "-d", ATTR, path], capture_output=True)
    time.sleep(2)
    if is_excluded(path):
        return {"path": path, "ok": False, "why": "could not remove the marker"}
    cat.db.execute("UPDATE project_sync SET undone=? WHERE path=?", (time.time(), path)); cat.db.commit()
    _log({"action": "resume-sync", "path": path, "by": by})
    return {"path": path, "ok": True, "why": "iCloud syncs it again (it will upload the project)"}


def _log(d):
    from .config import DATA as ROOT
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    with open(os.path.join(ROOT, "logs", "project-sync.jsonl"), "a") as f:
        f.write(json.dumps({**d, "t": time.time()}, ensure_ascii=False) + "\n")
