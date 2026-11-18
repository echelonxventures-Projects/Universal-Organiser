"""Owner and topic as macOS Finder tags, so Finder and Spotlight can show and find them.
Only the tags metadata is written (file contents and modified date stay the same). The engine remembers exactly which
tags it added, so removing them never touches tags you set yourself. Never on sensitive or iCloud-only files."""
import os, json, time, plistlib, subprocess
from . import platforms

XATTR = "com.apple.metadata:_kMDItemUserTags"
SCHEMA = "CREATE TABLE IF NOT EXISTS finder_tags(file_id INTEGER PRIMARY KEY, path TEXT, tags TEXT, t REAL)"


def read(path):
    r = subprocess.run(["/usr/bin/xattr", "-px", XATTR, path], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    try:
        return list(plistlib.loads(bytes.fromhex("".join(r.stdout.split()))))
    except Exception:
        return []


def write(path, tags):
    if not tags:
        return subprocess.run(["/usr/bin/xattr", "-d", XATTR, path], capture_output=True).returncode in (0, 1)
    data = plistlib.dumps(tags, fmt=plistlib.FMT_BINARY).hex()
    return subprocess.run(["/usr/bin/xattr", "-wx", XATTR, data, path], capture_output=True).returncode == 0


def _name(t):
    return t.split("\n")[0]


def wanted(r):
    return [x for x in (r["entity"], r["topic"]) if x]


def plan(cfg, cat):
    cat.db.execute(SCHEMA)
    ours = {r[0]: json.loads(r[1]) for r in cat.db.execute("SELECT file_id, tags FROM finder_tags")}
    rows = cat.db.execute("SELECT id, path, entity, topic FROM files WHERE unit='file' AND coalesce(sensitive,0)=0 AND coalesce(cloud_only,0)=0 AND path NOT LIKE 'uo://%' "
                          "AND (entity IS NOT NULL OR topic IS NOT NULL OR id IN (SELECT file_id FROM finder_tags))").fetchall()
    todo = [r for r in rows if sorted(wanted(r)) != sorted(ours.get(r["id"], []))]
    return {"files": len(todo), "tagged": len(ours), "rows": todo,
            "tags": sorted({t for r in todo for t in wanted(r)})}


def apply(cfg, cat, rows=None, progress=lambda d, t: None):
    if platforms.SYSTEM != "macos":
        raise ValueError("Finder tags are a macOS feature.")
    cat.db.execute(SCHEMA)
    rows = rows if rows is not None else plan(cfg, cat)["rows"]
    ours = {r[0]: json.loads(r[1]) for r in cat.db.execute("SELECT file_id, tags FROM finder_tags")}
    done = skipped = 0
    for i, r in enumerate(rows):
        progress(i, len(rows))
        p = r["path"]
        if not os.path.exists(p) or platforms.cloud_only(os.lstat(p)):
            skipped += 1; continue
        mine_old = set(ours.get(r["id"], []))
        cur = [t for t in read(p) if _name(t) not in mine_old]          # keep the person's own tags
        add = [t for t in wanted(r) if t not in {_name(x) for x in cur}]
        if write(p, cur + add):
            if add:
                cat.db.execute("INSERT OR REPLACE INTO finder_tags VALUES(?,?,?,?)", (r["id"], p, json.dumps(add, ensure_ascii=False), time.time()))
            else:
                cat.db.execute("DELETE FROM finder_tags WHERE file_id=?", (r["id"],))
            done += 1
        else:
            skipped += 1
        if i % 200 == 0:
            cat.db.commit()
    cat.db.commit()
    progress(len(rows), len(rows))
    return {"tagged": done, "skipped": skipped}


def remove_all(cat, progress=lambda d, t: None):
    cat.db.execute(SCHEMA)
    # use the file's current path: tags travel with a file when the sorter moves it
    rows = cat.db.execute("SELECT t.file_id, coalesce(f.path, t.path), t.tags FROM finder_tags t LEFT JOIN files f ON f.id=t.file_id").fetchall()
    n = 0
    for i, (fid, p, tags) in enumerate(rows):
        progress(i, len(rows))
        mine = set(json.loads(tags))
        if os.path.exists(p):
            write(p, [t for t in read(p) if _name(t) not in mine])
        cat.db.execute("DELETE FROM finder_tags WHERE file_id=?", (fid,)); n += 1
    cat.db.commit()
    return {"removed": n}
