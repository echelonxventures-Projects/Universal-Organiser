"""Analytics for the visual page: folder space map, duplicates, folder overlap, timeline, owner x topic.
Read-only, except the action plan: a staging list of intended actions (trash / archive) that nothing executes
until the sorter runs it with its own preview. Projects, packages and protected folders can never be planned."""
import os, json, time
from collections import defaultdict, Counter
from .config import HOME

PLAN_ACTIONS = {"trash": "Move to Trash", "archive": "Archive"}


def _scope_sql(scope):
    return ((" AND " + scope[0]) if scope[0] else ""), scope[1]


def _dup_hashes(cat):
    return {r[0] for r in cat.db.execute("SELECT hash FROM files WHERE hash IS NOT NULL AND unit='file' GROUP BY hash HAVING count(*)>1")}


def root_label(cfg, p):
    from . import platforms
    c = platforms.cloud_label(p)
    if c:
        return c
    return p.replace(HOME, "~") if p != HOME else "~"


def overview(cfg, cat, scope=("", [])):
    a, p = _scope_sql(scope)
    q = lambda sql, *x: cat.db.execute(sql, list(x) + p).fetchall()
    tot = q(f"SELECT count(*), coalesce(sum(size),0) FROM files f WHERE 1=1{a}")[0]
    kinds = [list(r) for r in q(f"SELECT coalesce(kind,'Other'), count(*), coalesce(sum(size),0) FROM files f WHERE 1=1{a} GROUP BY 1 ORDER BY 3 DESC")]
    cloud = q(f"SELECT count(*), coalesce(sum(size),0) FROM files f WHERE cloud_only=1{a}")[0]
    owned = q(f"SELECT count(*), coalesce(sum(size),0) FROM files f WHERE entity IS NOT NULL AND coalesce(kind,'') NOT IN ('Code','Font','Installer'){a}")[0]
    docs = q(f"SELECT count(*) FROM files f WHERE unit='file' AND coalesce(kind,'') NOT IN ('Code','Font','Installer'){a}")[0][0]
    files = q(f"SELECT count(*) FROM files f WHERE unit='file'{a}")[0][0]
    d = duplicates(cfg, cat, scope, limit=0)
    dup = [d["extra"], d["wasted"]]
    timeline = [list(r) for r in q(f"SELECT substr(date,1,4), CAST(substr(date,6,2) AS INTEGER), count(*), coalesce(sum(size),0) FROM files f "
                                   f"WHERE date IS NOT NULL AND unit='file'{a} GROUP BY 1,2 ORDER BY 1,2")]
    owners = [r[0] for r in q(f"SELECT entity FROM files f WHERE entity IS NOT NULL{a} GROUP BY 1 ORDER BY count(*) DESC LIMIT 14")]
    topics = [r[0] for r in q(f"SELECT topic FROM files f WHERE topic IS NOT NULL{a} GROUP BY 1 ORDER BY count(*) DESC LIMIT 14")]
    matrix = [list(r) for r in q(f"SELECT coalesce(entity,'(no owner)'), coalesce(topic,'(no topic)'), count(*), coalesce(sum(size),0) FROM files f "
                                 f"WHERE unit='file'{a} GROUP BY 1,2")]
    plan = cat.db.execute("SELECT action, count(*), coalesce(sum(f.size),0) FROM plan p JOIN files f ON f.id=p.file_id GROUP BY 1").fetchall()
    return {"total": list(tot), "files": files, "docs": docs, "kinds": kinds, "cloud": list(cloud), "owned": list(owned), "dup": list(dup),
            "timeline": timeline, "owners": owners, "topics": topics, "matrix": matrix,
            "plan": {r[0]: [r[1], r[2]] for r in plan}, "roots": [{"path": r, "name": root_label(cfg, r)} for r in cfg.roots]}


def tree(cfg, cat, path="", scope=("", []), max_files=250, expand=0.7):
    """Children of a folder, with any sub-folder holding more than `expand` of the space opened in place
    (one huge folder would otherwise fill the whole map and show nothing)."""
    t = _tree(cfg, cat, path, scope, max_files)
    t["expanded"] = []
    for _ in range(4):
        total = sum(d["size"] for d in t["dirs"]) + sum(f["size"] for f in t["files"]) + ((t["rest"] or {}).get("size") or 0)
        if not t["dirs"] or not total:
            break
        big = max(t["dirs"], key=lambda d: d["size"])
        if big["size"] <= expand * total:
            break
        sub = _tree(cfg, cat, big["path"], scope, max_files)
        if not sub["dirs"] and not sub["files"]:
            break
        t["dirs"].remove(big)
        t["expanded"].append(big["name"])
        for d in sub["dirs"]:
            d["name"] = big["name"] + "/" + d["name"]; t["dirs"].append(d)
        for f in sub["files"]:
            f["name"] = big["name"] + "/" + f["name"]; t["files"].append(f)
        if sub["rest"]:
            r = t["rest"] or {"n": 0, "size": 0}
            t["rest"] = {"n": r["n"] + sub["rest"]["n"], "size": r["size"] + sub["rest"]["size"]}
    t["dirs"].sort(key=lambda d: -d["size"])
    return t


def _tree(cfg, cat, path="", scope=("", []), max_files=250):
    """Children of a folder: sub-folders aggregated, plus the largest files directly inside."""
    a, p = _scope_sql(scope)
    dups = _dup_hashes(cat)
    cols = "id,path,name,size,kind,unit,hash,cloud_only,entity,sensitive"
    if not path:
        # top level: the sub-folders of every root side by side (one root alone would fill the whole map)
        out = []
        for r in cfg.roots:
            label = root_label(cfg, r)
            groups, direct = defaultdict(list), []
            for row in cat.db.execute(f"SELECT {cols} FROM files f WHERE substr(f.path,1,?)=?{a}", [len(r) + 1, r + "/"] + p):
                rest = row["path"][len(r) + 1:]
                (groups[rest.split("/", 1)[0]] if "/" in rest else direct).append(row)
            for n, rows in groups.items():
                out.append(_agg(rows, dups, {"name": f"{label}/{n}", "path": f"{r}/{n}", "type": "dir"}))
            if direct:
                out.append(_agg(direct, dups, {"name": f"{label} (loose files)", "path": r, "type": "dir"}))
        return {"path": "", "crumbs": [], "dirs": sorted([d for d in out if d["n"]], key=lambda d: -d["size"]), "files": [], "rest": None}
    pre = path.rstrip("/") + "/"
    groups, direct = defaultdict(list), []
    for row in cat.db.execute(f"SELECT {cols} FROM files f WHERE substr(f.path,1,?)=?{a}", [len(pre), pre] + p):
        rest = row["path"][len(pre):]
        if "/" in rest:
            groups[rest.split("/", 1)[0]].append(row)
        else:
            direct.append(row)
    dirs = [_agg(rows, dups, {"name": n, "path": pre + n, "type": "dir"}) for n, rows in groups.items()]
    direct.sort(key=lambda r: -(r["size"] or 0))
    files = [{"id": r["id"], "name": r["name"], "path": r["path"], "size": r["size"] or 0, "kind": r["kind"] or "Other",
              "type": "unit" if r["unit"] != "file" else "file", "unit": r["unit"], "dup": int(r["hash"] in dups), "cloud": r["cloud_only"],
              "owner": r["entity"], "sensitive": r["sensitive"]} for r in direct[:max_files]]
    left = direct[max_files:]
    rest = {"n": len(left), "size": sum(r["size"] or 0 for r in left)} if left else None
    root = next((r for r in cfg.roots if pre.startswith(r + "/") or pre == r + "/"), None)
    crumbs = []
    if root:
        crumbs.append({"name": root_label(cfg, root), "path": root})
        cur = root
        for part in pre[len(root) + 1:].strip("/").split("/"):
            if part:
                cur = cur + "/" + part; crumbs.append({"name": part, "path": cur})
    return {"path": path, "crumbs": crumbs, "dirs": sorted(dirs, key=lambda d: -d["size"]), "files": files, "rest": rest}


def _agg(rows, dups, base):
    kinds, owners = Counter(), Counter()
    size = n = dupb = cloud = owned = 0
    for r in rows:
        s = r["size"] or 0
        size += s; n += 1
        kinds[r["kind"] or "Other"] += s
        if r["hash"] in dups:
            dupb += s
        cloud += r["cloud_only"] or 0
        if r["entity"]:
            owned += 1; owners[r["entity"]] += 1
    base.update(size=size, n=n, kinds=dict(kinds.most_common(6)), dup_bytes=dupb, cloud=cloud, owned=owned, owners=owners.most_common(3))
    return base


def _keeper(cfg, rows):
    """Suggest which copy to keep: inside the library, labelled, not in Downloads/Desktop, shortest path."""
    lib = cfg.library.lower()
    def score(r):
        pl = r["path"].lower()
        return (0 if pl.startswith(lib + "/") else 1, 0 if r["entity"] else 1, 1 if "/downloads/" in pl or "/desktop/" in pl else 0,
                r["cloud_only"] or 0, len(r["path"]))
    return min(rows, key=score)["id"]


def duplicates(cfg, cat, scope=("", []), limit=300):
    a, p = _scope_sql(scope)
    rows = cat.db.execute(f"SELECT id,path,name,size,kind,hash,entity,cloud_only FROM files f WHERE unit='file' AND hash IN "
                          f"(SELECT hash FROM files WHERE hash IS NOT NULL AND unit='file' GROUP BY hash HAVING count(*)>1){a}", p).fetchall()
    g = defaultdict(list)
    for r in rows:
        g[r["hash"]].append(r)
    groups = []
    for h, rs in g.items():
        if len(rs) < 2:
            continue
        keep = _keeper(cfg, rs)
        sz = max(r["size"] or 0 for r in rs)
        groups.append({"hash": h, "name": rs[0]["name"], "kind": rs[0]["kind"], "size": sz, "n": len(rs), "wasted": sz * (len(rs) - 1), "keep": keep,
                       "copies": [{"id": r["id"], "path": r["path"], "owner": r["entity"], "cloud": r["cloud_only"]} for r in sorted(rs, key=lambda r: r["id"] != keep)]})
    groups.sort(key=lambda x: -x["wasted"])
    return {"groups": groups[:limit], "total_groups": len(groups), "wasted": sum(x["wasted"] for x in groups),
            "extra": sum(x["n"] - 1 for x in groups)}


def _lift(x, y):
    """Two folders with the same tail (…/A/x/y and …/B/x/y) are parts of two copies of one tree: compare A and B instead."""
    a, b = x.split("/"), y.split("/")
    while len(a) > 2 and len(b) > 2 and a[-1] == b[-1]:
        a.pop(); b.pop()
    return "/".join(a), "/".join(b)


def overlap(cfg, cat, scope=("", []), limit=60, min_shared=2, min_size=1024):
    import bisect
    a_, p = _scope_sql(scope)
    by_hash, sizes = defaultdict(set), {}
    for h, path, s in cat.db.execute(f"SELECT hash, path, size FROM files f WHERE unit='file' AND size>=? AND hash IN "
                                     f"(SELECT hash FROM files WHERE hash IS NOT NULL AND unit='file' GROUP BY hash HAVING count(*)>1){a_}", [min_size] + p):
        by_hash[h].add(os.path.dirname(path)); sizes[h] = s or 0
    pairs = defaultdict(lambda: [set(), 0])
    for h, ds in by_hash.items():
        ds = sorted(ds)[:12]
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                k = tuple(sorted(_lift(ds[i], ds[j])))
                if k[0] == k[1] or k[1].startswith(k[0] + "/") or k[0].startswith(k[1] + "/"):
                    continue  # one folder inside the other: not two copies
                x = pairs[k]
                if h not in x[0]:
                    x[0].add(h); x[1] += sizes[h]
    allp = sorted(r[0] for r in cat.db.execute("SELECT path FROM files WHERE unit='file'"))
    def count_under(d):
        lo = bisect.bisect_left(allp, d + "/"); hi = bisect.bisect_left(allp, d + "/\U0010ffff")
        return hi - lo
    out = []
    for (x, y), (hs, b) in pairs.items():
        n = len(hs)
        if n < min_shared:
            continue
        na, nb = count_under(x), count_under(y)
        out.append({"a": x, "b": y, "shared": n, "shared_bytes": b, "na": na, "nb": nb, "pct": round(n / max(1, min(na, nb)), 3),
                    "a_only": max(0, na - n), "b_only": max(0, nb - n)})
    out.sort(key=lambda o: (o["a"].count("/") + o["b"].count("/"), -o["shared_bytes"]))  # parents first
    inside = lambda d, top: d == top or d.startswith(top + "/")
    kept = []
    for o in out:  # a pair of sub-folders inside an already listed pair tells the same story
        if not any((inside(o["a"], k["a"]) and inside(o["b"], k["b"])) or (inside(o["a"], k["b"]) and inside(o["b"], k["a"])) for k in kept):
            kept.append(o)
    kept.sort(key=lambda o: (-o["shared_bytes"], -o["pct"]))
    return {"pairs": kept[:limit], "total": len(kept)}


# ---- action plan (staging only) ----
def plannable(cat, ids):
    """Only ordinary files. Projects, packages and protected folders are never planned."""
    if not ids:
        return []
    out = []
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        out += [r[0] for r in cat.db.execute(f"SELECT id FROM files WHERE unit='file' AND coalesce(protected,0)=0 AND id IN ({','.join('?' * len(chunk))})", chunk)]
    return out


def plan_add(cat, ids, action, by):
    if action not in PLAN_ACTIONS:
        raise ValueError("unknown action")
    ok = plannable(cat, ids)
    now = time.time()
    cat.db.executemany("INSERT OR REPLACE INTO plan(file_id,path,action,target,by,t) SELECT id,path,?,NULL,?,? FROM files WHERE id=?",
                       [(action, by, now, i) for i in ok])
    cat.db.commit()
    return len(ok)


def plan_remove(cat, ids=None):
    if ids is None:
        n = cat.db.execute("DELETE FROM plan").rowcount
    else:
        n = sum(cat.db.execute("DELETE FROM plan WHERE file_id=?", (int(i),)).rowcount for i in ids)
    cat.db.commit()
    return n


def plan_list(cat, limit=1000):
    rows = cat.db.execute("SELECT p.file_id, p.action, p.by, p.t, f.path, f.size, f.kind, f.entity FROM plan p JOIN files f ON f.id=p.file_id "
                          "ORDER BY p.action, f.size DESC LIMIT ?", (limit,)).fetchall()
    summ = {r[0]: {"n": r[1], "size": r[2]} for r in cat.db.execute(
        "SELECT action, count(*), coalesce(sum(f.size),0) FROM plan p JOIN files f ON f.id=p.file_id GROUP BY 1")}
    return {"summary": summ, "labels": PLAN_ACTIONS, "items": [dict(r) for r in rows]}
