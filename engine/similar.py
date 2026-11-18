"""Near-duplicate photos (suggest only). On-device: a 64-bit difference hash finds candidates cheaply, Apple Vision's
image feature print confirms them. Groups are suggestions; nothing is changed unless a person plans an action.
Skips iCloud-only (no download) and sensitive files."""
import os, json, time, base64, struct, math, hashlib
from datetime import datetime
from collections import defaultdict
from .plugins.macos_vision import _parallel, HELPER

SCHEMA = """CREATE TABLE IF NOT EXISTS photo_features(file_id INTEGER PRIMARY KEY, mtime REAL, dhash TEXT, fp BLOB, w INTEGER, h INTEGER,
 taken TEXT, error TEXT)"""


def _cfg(cfg):
    return cfg.plugin("near_duplicate_photos")


def compute(cfg, cat, log=print, batch=200):
    """Fingerprint photos that are new or changed. Returns how many were done."""
    cat.db.execute(SCHEMA)
    if not os.path.exists(HELPER):
        log("helper missing"); return 0
    rows = cat.db.execute("SELECT f.id, f.path, f.mtime FROM files f LEFT JOIN photo_features p ON p.file_id=f.id "
                          "WHERE f.kind='Photo' AND f.unit='file' AND f.path NOT LIKE 'uo://%' AND coalesce(f.cloud_only,0)=0 AND coalesce(f.sensitive,0)=0 "
                          "AND (p.file_id IS NULL OR abs(p.mtime - f.mtime) > 1)").fetchall()
    total, done, t0 = len(rows), 0, time.time()
    log(f"photos to fingerprint: {total}")
    for i in range(0, total, batch):
        chunk = rows[i:i + batch]
        res = _parallel([r["path"] for r in chunk], ["sim"])
        for r in chunk:
            d = res.get(r["path"], {})
            fp = base64.b64decode(d["fp"]) if d.get("fp") else None
            cat.db.execute("INSERT OR REPLACE INTO photo_features VALUES(?,?,?,?,?,?,?,?)",
                           (r["id"], r["mtime"], d.get("dhash"), fp, d.get("w"), d.get("h"), d.get("taken"), d.get("error")))
        cat.db.commit()
        done += len(chunk)
        el = time.time() - t0
        log(f"  {done}/{total}  ({el / done * (total - done) / 60:.1f} min left)")
    return done


def _vec(b):
    return struct.unpack(f"{len(b) // 4}f", b) if b else None


def dist(a, b):
    return math.sqrt(sum((x - y) * (x - y) for x, y in zip(a, b)))


def _taken(t):
    try:
        return datetime.strptime(t[:19], "%Y:%m:%d %H:%M:%S").timestamp()
    except (TypeError, ValueError):
        return None


def candidate_pairs(rows, max_ham=12, burst_s=10):
    """Pairs worth comparing: similar layout hash, or shot within a few seconds of each other."""
    hs = [(r["file_id"], int(r["dhash"], 16)) for r in rows if r["dhash"]]
    pairs = set()
    for i in range(len(hs)):
        ai, ah = hs[i]
        for j in range(i + 1, len(hs)):
            if bin(ah ^ hs[j][1]).count("1") <= max_ham:
                pairs.add((ai, hs[j][0]))
    shots = sorted((t, r["file_id"]) for r in rows if (t := _taken(r["taken"])))
    for i in range(len(shots)):
        j = i + 1
        while j < len(shots) and shots[j][0] - shots[i][0] <= burst_s:
            pairs.add(tuple(sorted((shots[i][1], shots[j][1])))); j += 1
    return pairs


def groups(cfg, cat, scope=("", []), threshold=None):
    cat.db.execute(SCHEMA)
    pc = _cfg(cfg)
    thr = threshold if threshold is not None else pc.get("max_distance", 0.3)
    thr_screen = pc.get("max_distance_screens", 0.05)
    a = (" AND " + scope[0]) if scope[0] else ""
    rows = cat.db.execute(f"SELECT p.file_id, p.dhash, p.fp, p.w, p.h, p.taken, f.path, f.size, f.hash, f.entity, f.date, f.ext, f.doc_type FROM photo_features p "
                          f"JOIN files f ON f.id=p.file_id WHERE p.fp IS NOT NULL AND coalesce(p.w,0)*coalesce(p.h,0) >= ?{a}",
                          [pc.get("min_pixels", 128 * 128)] + scope[1]).fetchall()
    by = {r["file_id"]: r for r in rows}
    vec = {}
    pairs = candidate_pairs(rows, pc.get("max_hamming", 12), pc.get("burst_seconds", 10))
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x]); x = parent[x]
        return x
    close = {}
    for x, y in pairs:
        if x not in by or y not in by:
            continue
        vx = vec.setdefault(x, _vec(by[x]["fp"])); vy = vec.setdefault(y, _vec(by[y]["fp"]))
        if not vx or not vy or len(vx) != len(vy):
            continue
        d = dist(vx, vy)
        # screenshots and app screens look alike even when their content differs: they must be (almost) identical
        screen = any(by[z]["doc_type"] in ("Screenshot",) or (by[z]["ext"] in ("png", "gif", "bmp", "webp") and not by[z]["taken"]) for z in (x, y))
        if d <= (thr_screen if screen else thr):
            close[(x, y)] = d
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx
    comp = defaultdict(set)
    for x, y in close:
        for z in (x, y):
            comp[find(z)].add(z)
    lib0 = cfg.library.lower() + "/"
    def quality(i):
        r = by[i]; pl = r["path"].lower()
        return (-(r["w"] or 0) * (r["h"] or 0), -(r["size"] or 0), 0 if pl.startswith(lib0) else 1, len(r["path"]))
    # no chaining: a group is a seed (best quality first) plus only the photos close to that seed itself
    g = {}
    for members in comp.values():
        left = sorted(members, key=quality)
        while left:
            seed = left.pop(0)
            limit = thr_screen if (by[seed]["doc_type"] == "Screenshot" or (by[seed]["ext"] in ("png", "gif", "bmp", "webp") and not by[seed]["taken"])) else thr
            near = [z for z in left if dist(vec[seed], vec.setdefault(z, _vec(by[z]["fp"]))) <= limit]
            if near:
                g[seed] = [seed] + near
                for z in near:
                    left.remove(z)
                    close.setdefault(tuple(sorted((seed, z))), dist(vec[seed], vec[z]))
    from .insights import dismissed
    gone = dismissed(cat)
    lib = cfg.library.lower() + "/"
    out = []
    for members in g.values():
        ids = sorted(set(members))
        key = "sim:" + hashlib.sha1(",".join(map(str, ids)).encode()).hexdigest()[:16]
        if key in gone:
            continue
        items = [by[i] for i in ids]
        def score(r):
            pl = r["path"].lower()
            return (-(r["w"] or 0) * (r["h"] or 0), -(r["size"] or 0), 0 if pl.startswith(lib) else 1,
                    1 if "/downloads/" in pl or "/desktop/" in pl else 0, len(r["path"]))
        best = min(items, key=score)
        ds = [d for (x, y), d in close.items() if x in ids and y in ids] or [0.0]
        identical = len({r["hash"] for r in items}) == 1
        out.append({"key": key, "best": best["file_id"], "n": len(items), "identical": identical,
                    "level": "identical files" if identical else "look identical" if min(ds) <= 0.05 else "same moment" if min(ds) <= 0.2 else "very similar",
                    "closest": round(min(ds), 3), "spread": round(max(ds), 3),
                    "save": sum(r["size"] or 0 for r in items) - (best["size"] or 0),
                    "items": [{"id": r["file_id"], "path": r["path"], "size": r["size"], "w": r["w"], "h": r["h"], "date": r["date"],
                               "owner": r["entity"], "same_file": r["hash"] == best["hash"]} for r in sorted(items, key=score)]})
    out.sort(key=lambda x: -x["save"])
    return {"groups": out, "photos": len(rows), "candidates": len(pairs), "threshold": thr,
            "pending": cat.db.execute("SELECT count(*) FROM files f LEFT JOIN photo_features p ON p.file_id=f.id WHERE f.kind='Photo' AND f.unit='file' AND f.path NOT LIKE 'uo://%' "
                                      "AND coalesce(f.cloud_only,0)=0 AND coalesce(f.sensitive,0)=0 AND p.file_id IS NULL").fetchone()[0]}
