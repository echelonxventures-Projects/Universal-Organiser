"""Clear clutter inside the projects home. Everything goes to the Trash (kept in its folder structure) with a log.

  python3 -I declutter.py plan             what would go, nothing changed
  python3 -I declutter.py run              move to the Trash; log in logs/declutter-<time>.jsonl
  python3 -I declutter.py undo LOG.jsonl   put everything back

What counts as clutter
  copies      (inside git repositories also iCloud's "name 2.ext" style, untracked only)
              "name (1).ext" whose content is identical to "name.ext" beside it; a folder "name (1)" whose every file is
              identical to the one in "name"
  system      .DS_Store, ._* and ~$* files
  logs        *.log of 5 MB or more
  backups     archives (.zip .tar.gz .tgz .tar) of 1 MB or more with "backup" in their path
  installers  .dmg / .pkg, and a "release" folder that holds a built .app
  rebuildable node_modules, virtual environments, caches and build output - ONLY in projects whose status is Paused/Completed
Never: anything git tracks, .git itself, a project that a program has open, "(1)" files that differ from the original,
items with iCloud-only parts (they cannot leave the synced folder until downloaded),
keys and .env files, empty files and folders."""
import os, re, sys, json, time, hashlib, subprocess, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.abspath(os.path.expanduser(os.environ.get("UO_DATA") or ROOT))
ALWAYS = {"node_modules", "__pycache__", ".next", ".turbo", ".cache", ".nx", ".ruff_cache", ".pytest_cache", ".mypy_cache", ".parcel-cache"}
BUILD = {"dist": ("package.json",), "build": ("package.json",), "coverage": ("package.json",), "target": ("Cargo.toml", "pom.xml")}
COPY = re.compile(r"^(.*?) \(\d+\)(\.[^.]*)?$")
COPY2 = re.compile(r"^(.*?) \d(\.[^.]*)?$")  # iCloud's own style "name 2.ext": only trusted inside a git repository, for untracked items
ARCH = (".zip", ".tar.gz", ".tgz", ".tar")


def _hash(p):
    m = hashlib.sha1()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            m.update(b)
    return m.hexdigest()


def _same(a, b):
    try:
        return os.path.isfile(a) and os.path.isfile(b) and os.lstat(a).st_size == os.lstat(b).st_size and _hash(a) == _hash(b)
    except OSError:
        return False


def _dsize(p):
    n = s = 0
    for dp, dn, fn in os.walk(p):
        for f in fn:
            try:
                s += os.lstat(os.path.join(dp, f)).st_size; n += 1
            except OSError:
                pass
    return n, s


class Tracked:
    """Which paths git tracks. A repository that cannot be read counts as 'everything tracked' (nothing is touched)."""
    def __init__(self):
        self.repos = {}

    def _load(self, repo):
        try:
            r = subprocess.run(["git", "--no-optional-locks", "-C", repo, "ls-files", "-z"], capture_output=True, timeout=60)
            self.repos[repo] = None if r.returncode else {repo + "/" + x for x in r.stdout.decode("utf-8", "replace").split("\0") if x}
        except (subprocess.TimeoutExpired, OSError):
            self.repos[repo] = None

    def repo_of(self, path, top):
        d = path if os.path.isdir(path) else os.path.dirname(path)
        while len(d) >= len(top):
            if os.path.exists(os.path.join(d, ".git")):
                return d
            d = os.path.dirname(d)
        return None

    def file(self, path, top):
        repo = self.repo_of(path, top)
        if not repo:
            return False
        if repo not in self.repos:
            self._load(repo)
        t = self.repos[repo]
        return True if t is None else path in t

    def under(self, folder, top):
        repo = self.repo_of(folder, top)
        if not repo:
            return False
        if repo not in self.repos:
            self._load(repo)
        t = self.repos[repo]
        return True if t is None else any(x.startswith(folder + "/") for x in t)


def plan(home, status, in_use):
    T, items, skipped = Tracked(), [], []
    add = lambda kind, p, n, s: items.append({"kind": kind, "path": p, "files": n, "size": s})
    for name in sorted(os.listdir(home), key=str.lower):
        top = os.path.join(home, name)
        if name.startswith(".") or not os.path.isdir(top) or os.path.islink(top):
            continue
        if any(u == top or u.startswith(top + "/") for u in in_use):
            skipped.append((name, "open in a program")); continue
        paused = status.get(top) in ("Paused", "Completed")
        for dp, dn, fn in os.walk(top):
            keep = []
            for d in dn:
                q = os.path.join(dp, d)
                if os.path.islink(q) or d == ".git":
                    continue
                reb = d in ALWAYS or os.path.isfile(os.path.join(q, "pyvenv.cfg")) or (d in BUILD and any(os.path.exists(os.path.join(dp, m)) for m in BUILD[d]))
                if reb:
                    if paused and not T.under(q, top):
                        add("rebuildable", q, *_dsize(q))
                    continue  # never look inside libraries or build output
                if d == "release" and any(x.endswith(".app") for sub in ("", "mac", "mac-arm64") if os.path.isdir(os.path.join(q, sub)) for x in os.listdir(os.path.join(q, sub))):
                    if not T.under(q, top):
                        add("installers", q, *_dsize(q))
                    continue
                m = COPY.match(d) or (COPY2.match(d) if T.repo_of(q, top) else None)
                if m and os.path.isdir(os.path.join(dp, m.group(1))) and not T.under(q, top):
                    o, same, cnt = os.path.join(dp, m.group(1)), True, 0
                    for dp2, _, fn2 in os.walk(q):
                        for f in fn2:
                            if f == ".DS_Store": continue
                            cnt += 1
                            if not _same(os.path.join(dp2, f), os.path.join(o + dp2[len(q):], f)):
                                same = False; break
                        if not same: break
                    if same:
                        add("copies", q, *_dsize(q)); continue
                keep.append(d)
            dn[:] = keep
            for f in fn:
                q = os.path.join(dp, f)
                try:
                    st = os.lstat(q)
                except OSError:
                    continue
                if os.path.islink(q):
                    continue
                low, kind = f.lower(), None
                m = COPY.match(f) or (COPY2.match(f) if T.repo_of(q, top) else None)
                if f == ".DS_Store" or f.startswith("._") or f.startswith("~$"):
                    kind = "system"
                elif m and _same(q, os.path.join(dp, m.group(1) + (m.group(2) or ""))):
                    kind = "copies"
                elif low.endswith(".log") and st.st_size >= 5_000_000:
                    kind = "logs"
                elif low.endswith(ARCH) and st.st_size >= 1_000_000 and "backup" in q[len(top):].lower():
                    kind = "backups"
                elif low.endswith((".dmg", ".pkg")):
                    kind = "installers"
                if kind and not T.file(q, top):
                    add(kind, q, 1, st.st_size)
    return items, skipped


def _cloud_only(p):
    DL = 0x40000000
    try:
        if os.lstat(p).st_flags & DL:
            return True
        for dp, dn, fn in os.walk(p):
            for f in fn + dn:
                if os.lstat(os.path.join(dp, f)).st_flags & DL:
                    return True
    except OSError:
        pass
    return False


def _in_use():
    out = subprocess.run(["lsof", "-Fn"], capture_output=True, text=True, timeout=120).stdout
    return {l[1:] for l in out.splitlines() if l.startswith("n/")}


def _status(home):
    sys.path.insert(0, ROOT)
    from engine.config import Config
    from engine.catalogue import Catalogue
    from engine import platforms
    cfg = Config(); cat = Catalogue(platforms.open_store(cfg, create=False))
    st = dict(cat.db.execute("SELECT path, status FROM project_status"))
    cat.db.close()
    return cfg.projects_home, st


def main():
    cmd = sys.argv[1]
    if cmd == "undo":
        for r in reversed([json.loads(l) for l in open(sys.argv[2]) if l.strip()]):
            if os.path.lexists(r["path"]) or not os.path.lexists(r["trash"]):
                print("SKIP", r["path"]); continue
            os.makedirs(os.path.dirname(r["path"]), exist_ok=True); os.rename(r["trash"], r["path"])
        print("put back"); return
    home, status = _status(None)
    items, skipped = plan(home, status, _in_use())
    by = collections.defaultdict(lambda: [0, 0, 0])
    for i in items:
        by[i["kind"]][0] += 1; by[i["kind"]][1] += i["files"]; by[i["kind"]][2] += i["size"]
    for k, v in sorted(by.items(), key=lambda x: -x[1][2]):
        print(f"{k:12} {v[0]:6,} items  {v[1]:8,} files  {v[2]/1e6:9,.1f} MB")
    print(f"TOTAL {sum(v[2] for v in by.values())/1e9:.2f} GB; skipped projects: {skipped}")
    if cmd == "plan":
        json.dump(items, open(os.path.join(DATA, "logs", "declutter-plan.json"), "w")); return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bin_ = os.path.join(os.path.expanduser("~/.Trash"), "Projects clutter " + stamp)
    log = os.path.join(DATA, "logs", f"declutter-{stamp}.jsonl")
    done = fail = 0
    import threading
    for n, i in enumerate(items):
        dest = os.path.join(bin_, i["path"][len(home) + 1:])
        if _cloud_only(i["path"]):  # iCloud will not let an item leave before it is downloaded; such a move can hang for hours
            fail += 1; print("LEFT (iCloud-only, not downloaded)", i["path"], flush=True); continue
        err = []
        def mv():
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                os.rename(i["path"], dest)
            except OSError as e:
                err.append(e)
        t = threading.Thread(target=mv, daemon=True); t.start(); t.join(300)
        if t.is_alive():
            print("STOPPED: stuck for 5 minutes on", i["path"], f"({done:,} moved so far; log {log})", flush=True); os._exit(2)
        if err:
            fail += 1; print("FAILED", i["path"], err[0], flush=True); continue
        if n % 500 == 0:
            print(f"  {n:,}/{len(items):,}", flush=True)
        with open(log, "a") as f:
            f.write(json.dumps({**i, "trash": dest, "t": time.time()}, ensure_ascii=False) + "\n")
        done += 1
    print(f"moved to Trash: {done:,} items, failed {fail}; log {log}")


if __name__ == "__main__":
    main()
