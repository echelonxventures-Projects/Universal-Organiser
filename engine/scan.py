"""Read-only scanner: walks the profile's roots, builds units (file / project / package / protected folder),
runs enabled plug-ins in batches, and saves to the catalogue. Never writes, moves or renames user files.
Incremental: unchanged files (same size + mtime) are skipped on later runs."""
import os, time, json
from . import plugins
from .config import DATA as ROOT

STATUS = os.path.join(ROOT, "logs", "scan-status.json")
from . import platforms


def _status(**kw):
    kw["t"] = time.time()
    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    with open(STATUS + ".tmp", "w") as f:
        json.dump(kw, f)
    os.replace(STATUS + ".tmp", STATUS)


def _under(p, bases):
    pl = p.lower()
    return any(pl == b.lower() or pl.startswith(b.lower() + "/") for b in bases)


def dir_stats(d):
    n = size = 0
    for dp, dn, fn in os.walk(d):
        for f in fn:
            try:
                st = os.lstat(os.path.join(dp, f)); n += 1; size += platforms.disk_bytes(st)
            except OSError:
                pass
    return n, size


def _code_folder(cfg, names, full):
    """A folder (outside the library) where most files are code is a project, kept whole."""
    if _under(full, [cfg.library]):
        return False
    cf = cfg.get("skip", {}).get("code_folder", {})
    files = [n for n in names if "." in n and not n.startswith(".")]
    if len(files) < cf.get("min_files", 5):
        return False
    code = sum(1 for n in files if cfg.kind_of.get(n.rsplit(".", 1)[-1].lower()) == "Code")
    return code / len(files) >= cf.get("share", 0.6)


def walk(cfg):
    """Yield (path, unit, reason) for everything to catalogue."""
    import fnmatch
    seen = set()
    sk = cfg.get("skip", {})
    hide_dirs, suffixes, pats = sk.get("hidden_folders", True), tuple(sk.get("dir_suffixes", [])), sk.get("file_patterns", [])
    for root in cfg.roots:
        if not os.path.isdir(root):
            continue
        try:
            rnames = set(os.listdir(root))
        except OSError:
            continue
        # the root itself is one project: only for a git repository that is not a general place holding other folders' work
        if ".git" in rnames and not _under(root, cfg.protect) and root not in (cfg.library, cfg.projects_home) \
                and os.path.basename(root) not in ("Desktop", "Documents", "Downloads", "Pictures", "Movies", "Music"):
            yield platforms.norm(root), "project", "root is a project"; continue
        for dp, dn, fn in os.walk(root):
            dp = platforms.norm(dp)
            if _under(dp, cfg.exclude):
                dn[:] = []; continue
            keep = []
            for d in dn:
                full = dp + "/" + d
                if os.path.islink(full) or d in cfg.skip_dirs or d.lower().endswith(("venv", "virtualenv")):
                    continue
                if (hide_dirs and d.startswith(".")) or (suffixes and d.endswith(suffixes)):
                    continue  # hidden tool folders and app-managed libraries
                if _under(full, cfg.exclude):
                    continue
                if _under(full, cfg.protect):
                    yield full, "protected", "protected path"; continue
                ext = d.rsplit(".", 1)[-1].lower() if "." in d else ""
                if ext in cfg.package_exts:
                    yield full, "package", ext; continue
                try:
                    names = set(os.listdir(full))
                except OSError:
                    continue
                if "pyvenv.cfg" in names:  # a Python virtual environment: installed libraries, not user files
                    continue
                if dp == cfg.projects_home:  # the projects home: each folder directly inside is one whole project (its parts are not split)
                    yield full, "project", "in the projects folder"; continue
                if names & cfg.markers or any(n.endswith((".xcodeproj", ".xcworkspace", ".sln")) for n in names):
                    yield full, "project", ", ".join(sorted(names & cfg.markers))[:80]; continue
                if _code_folder(cfg, names, full):
                    yield full, "project", "mostly code files"; continue
                keep.append(d)
            dn[:] = keep
            for f in fn:
                if f in (".DS_Store", "Icon\r", ".localized") or f.startswith("._"):
                    continue
                if any(fnmatch.fnmatchcase(f.lower(), x.lower()) for x in pats):
                    continue  # logs, locks, temporary and system files
                if f.startswith(".") and not (sk.get("keep_hidden_files_if_sensitive", True) and cfg.sensitive_rx.search(f)):
                    continue  # hidden files are kept only when sensitive, so the privacy check still sees them
                p = dp + "/" + f
                real = os.path.realpath(p)
                if real in seen:
                    continue
                seen.add(real)
                yield p, "file", None


def make_record(cfg, path, unit, reason):
    st = os.lstat(path)
    name = os.path.basename(path)
    r = {"path": path, "name": name, "unit": unit, "mtime": st.st_mtime, "birth": getattr(st, "st_birthtime", None)}
    if unit == "file":
        r["ext"] = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        r["size"] = st.st_size
        # iCloud / OneDrive placeholders: reading one waits for a download (on macOS it can hang, even at 0 bytes)
        r["cloud_only"] = int(platforms.cloud_only(st))
        r["sensitive"] = int(bool(cfg.sensitive_rx.search(path)))
        r["skip_content"] = r["cloud_only"] or (r["sensitive"] and not cfg["sensitive"].get("read_content", False)) or os.path.islink(path)
        if r["sensitive"]:
            r["tags"] = ["sensitive"]
        if r["cloud_only"]:
            r.setdefault("tags", []).append("iCloud only")
    else:
        r["ext"], r["kind"] = "", {"project": "Project", "package": "App/Package", "protected": "Protected folder"}[unit]
        r["protected"] = int(unit == "protected")
        r["extra"] = {"why": reason}
        if unit == "protected":
            r["inner_count"], r["size"] = None, None  # protected folders are never opened
        else:
            r["inner_count"], r["size"] = dir_stats(path)
    return r


def scan(cfg, cat, batch_size=150, full=False, log=print):
    started = time.time()
    known = {} if full else cat.known()
    active = plugins.active(cfg)
    log("plug-ins: " + ", ".join(f"{p.__module__.rsplit('.', 1)[-1]}.{p.__name__}" for p in active))
    todo, unchanged = [], []
    _status(phase="listing", found=0)
    for i, (path, unit, why) in enumerate(walk(cfg)):
        try:
            st = os.lstat(path)
        except OSError:
            continue
        k = known.get(path)
        if k and unit == "file" and k[0] == st.st_size and abs((k[1] or 0) - st.st_mtime) < 1:
            unchanged.append(path)
        else:
            todo.append((path, unit, why))
        if i % 5000 == 0:
            _status(phase="listing", found=i)
    cat.touch(unchanged, started)
    total = len(todo)
    log(f"found {total + len(unchanged)} items: {total} new/changed, {len(unchanged)} unchanged")
    done = errs = 0
    for b in range(0, total, batch_size):
        recs = []
        for path, unit, why in todo[b:b + batch_size]:
            try:
                recs.append(make_record(cfg, path, unit, why))
            except OSError:
                pass
        for p in active:
            try:
                p.run(recs, cfg)
            except Exception as ex:  # a broken plug-in never stops the scan
                log(f"plug-in {p.__name__} failed on a batch: {type(ex).__name__}: {ex}")
        now = time.time()
        for r in recs:
            r["scanned_at"] = r["seen_at"] = now
            errs += bool(r.get("errors"))
        cat.save(recs)
        done += len(recs)
        _status(phase="analysing", done=done, total=total, errors=errs, started=started)
    removed = cat.forget_missing(started)
    cat.set_meta("last_scan", {"at": time.time(), "took_s": round(time.time() - started), "analysed": done, "removed": removed})
    _status(phase="done", done=done, total=total, errors=errs, removed=removed, started=started)
    log(f"done: analysed {done}, errors {errs}, removed {removed} records of files that no longer exist, took {round(time.time() - started)}s")
