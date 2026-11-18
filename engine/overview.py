"""Bird's-eye Overview: one hierarchy API for every lens, with health, changes since the last visit and trends.

A node is a list of values from the top of a lens:
  folder : [root, sub-folder, sub-folder, …]           (real folders)
  person : [owner, topic, year]                         (owner '(no owner)' for files without one)
  topic  : [topic, owner, year]
  year   : [year, month, type]
  type   : [type, year, document type]
Health of a file: ok (has an owner, or is technical: code/fonts/installers), needs (no owner),
problem (sensitive file in a cloud-synced folder, damaged/unreadable, or an extra identical copy)."""
import os, time, json, datetime
from collections import defaultdict, Counter

TECH = ("Code", "Font", "Installer")
PAPERS = ("PDF", "Document", "Spreadsheet", "Presentation", "Email")


def wants_owner(r):
    """Owners matter for papers (and photos of papers); media is organised by date, archives and code are bundles."""
    return r["unit"] == "file" and (r["kind"] in PAPERS or (r["kind"] == "Photo" and r.get("doc_type") not in (None, "Screenshot")))
LENSES = {"person": ["entity", "topic", "year"], "topic": ["topic", "entity", "year"],
          "year": ["year", "month", "kind"], "type": ["kind", "year", "doc_type"]}
NONE = "(none)"
LABEL_NONE = {"entity": "(no owner)", "topic": "(no topic)", "year": "(no date)", "month": "(no date)", "kind": "Other", "doc_type": "(no type)"}
MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class Ctx:
    """Per-request facts used to judge health."""
    def __init__(self, cfg, cat, since):
        from .insights import synced_roots
        self.synced = [s + "/" for s in synced_roots(cfg, cat)]
        self.extra_copies = set()
        firsts = {}
        for fid, h in cat.db.execute("SELECT id, hash FROM files WHERE unit='file' AND hash IS NOT NULL AND hash IN "
                                     "(SELECT hash FROM files WHERE hash IS NOT NULL AND unit='file' GROUP BY hash HAVING count(*)>1) ORDER BY id"):
            if h in firsts:
                self.extra_copies.add(fid)
            else:
                firsts[h] = fid
        self.since = since or 0
        self.labelled = {r[0] for r in cat.db.execute("SELECT f.id FROM decisions d JOIN files f ON f.path=d.path WHERE d.t > ?", (self.since,))} if since else set()

    def sens(self, r):
        return bool(r["sensitive"]) and any(r["path"].startswith(s) for s in self.synced)

    def state(self, r):
        # duplicates are a space matter (Duplicates view), not a problem colour
        if self.sens(r) or r["errors"]:
            return "problem"
        return "needs" if (not r["entity"] and wants_owner(r)) else "ok"

    def is_new(self, r):
        return bool(self.since) and ((r["scanned_at"] or 0) > self.since or r["id"] in self.labelled)


COLS = "id,path,name,unit,kind,size,entity,topic,year,date,doc_type,sensitive,errors,cloud_only,scanned_at,mtime"


def _rows(cat, where="1=1", params=(), scope=("", [])):
    a = (" AND " + scope[0]) if scope[0] else ""
    return [dict(r) for r in cat.db.execute(f"SELECT {COLS} FROM files f WHERE {where}{a}", list(params) + scope[1])]


def _agg(rows, ctx):
    a = {"n": 0, "size": 0, "ok": 0, "needs": 0, "problem": 0, "new": 0, "papers": 0, "sens": 0, "damaged": 0}
    for r in rows:
        a["n"] += 1; a["size"] += r["size"] or 0
        a[ctx.state(r)] += 1
        a["new"] += ctx.is_new(r)
        a["papers"] += wants_owner(r)
        a["sens"] += ctx.sens(r)
        a["damaged"] += bool(r["errors"])
    return a


def _val(r, col):
    if col == "month":
        return r["date"][5:7] if r.get("date") else None
    if col == "topic" and r.get("topic"):
        return r["topic"]
    return r.get(col)


def _label(col, v):
    if v in (None, ""):
        return LABEL_NONE.get(col, NONE)
    if col == "month":
        return MONTHS[int(v)] if str(v).isdigit() and 0 < int(v) < 13 else v
    return str(v)


def roots_of(cfg):
    from .analytics import root_label
    return [(r, root_label(cfg, r)) for r in cfg.roots]


def node(cfg, cat, lens, key, scope=("", []), since=None, max_files=300):
    ctx = Ctx(cfg, cat, since)
    if lens == "folder":
        return _folder(cfg, cat, key, scope, ctx, max_files)
    cols = LENSES[lens]
    depth = len(key)
    w, p = ["unit='file'"], []
    for col, v in zip(cols, key):
        if col == "month":
            w.append("substr(date,6,2) = ?" if v not in (None, NONE) else "date IS NULL"); p += [v] if v not in (None, NONE) else []
        elif v in (None, NONE):
            w.append(f"{col} IS NULL")
        else:
            w.append(f"{col} = ?"); p.append(v)
    rows = _rows(cat, " AND ".join(w), p, scope)
    crumbs = [{"label": "Everything", "key": []}] + [{"label": _label(c, v), "key": key[:i + 1]} for i, (c, v) in enumerate(zip(cols, key))]
    children, files = [], []
    if depth < len(cols):
        col = cols[depth]
        groups = defaultdict(list)
        for r in rows:
            groups[_val(r, col)].append(r)
        for v, rs in groups.items():
            children.append({"key": key + [v if v not in (None, "") else NONE], "label": _label(col, v), **_agg(rs, ctx)})
        children.sort(key=lambda c: (c["label"].startswith("("), -c["size"]) if col not in ("year", "month") else (c["label"].startswith("("), str(c["key"][-1])), reverse=False)
        if col in ("year", "month"):
            children.sort(key=lambda c: (c["label"].startswith("("), -int(c["key"][-1]) if str(c["key"][-1]).isdigit() else 0))
    else:
        files = rows
    return _finish(cfg, cat, lens, key, crumbs, children, files, rows, ctx, max_files)


def _folder(cfg, cat, key, scope, ctx, max_files):
    crumbs = [{"label": "Everything", "key": []}]
    if not key:
        children = []
        for r, label in roots_of(cfg):
            rs = _rows(cat, "substr(path,1,?)=?", (len(r) + 1, r + "/"), scope)
            if rs:
                children.append({"key": [r], "label": label, **_agg(rs, ctx)})
        children.sort(key=lambda c: -c["size"])
        allrows = _rows(cat, scope=scope)
        return _finish(cfg, cat, "folder", key, crumbs, children, [], allrows, ctx, max_files)
    path = key[-1]
    root = next((r for r, _ in roots_of(cfg) if path == r or path.startswith(r + "/")), None)
    if root:
        crumbs.append({"label": dict(roots_of(cfg))[root], "key": [root]})
        cur = root
        for part in path[len(root) + 1:].split("/") if path != root else []:
            cur += "/" + part; crumbs.append({"label": part, "key": [cur]})
    pre = path + "/"
    rows = _rows(cat, "substr(path,1,?)=?", (len(pre), pre), scope)
    groups, direct = defaultdict(list), []
    for r in rows:
        rest = r["path"][len(pre):]
        (groups[pre + rest.split("/", 1)[0]] if "/" in rest else direct).append(r)
    children = [{"key": [k], "label": os.path.basename(k), "dir": True, **_agg(rs, ctx)} for k, rs in groups.items()]
    children.sort(key=lambda c: -c["size"])
    return _finish(cfg, cat, "folder", key, crumbs, children, direct, rows, ctx, max_files)


def _finish(cfg, cat, lens, key, crumbs, children, files, rows, ctx, max_files):
    files = sorted(files, key=lambda r: -(r["size"] or 0))
    flist = [{"id": r["id"], "name": r["name"], "path": r["path"], "kind": r["kind"], "size": r["size"] or 0, "owner": r["entity"],
              "topic": r["topic"], "doc_type": r["doc_type"], "date": r["date"], "unit": r["unit"], "cloud": r["cloud_only"],
              "state": ctx.state(r), "new": ctx.is_new(r)} for r in files[:max_files]]
    rest = {"n": len(files) - max_files, "size": sum(r["size"] or 0 for r in files[max_files:])} if len(files) > max_files else None
    return {"lens": lens, "key": key, "crumbs": crumbs, "children": children, "files": flist, "rest": rest, "panel": panel(cfg, cat, rows, ctx)}


def panel(cfg, cat, rows, ctx):
    """'This place': what is inside and what is wrong here."""
    a = _agg(rows, ctx)
    docs = [r for r in rows if wants_owner(r)]
    c = lambda key: [[k or "(none)", n] for k, n in Counter(key(r) for r in rows).most_common(6)]
    issues = []
    nd = sum(1 for r in docs if not r["entity"])
    if nd:
        issues.append({"kind": "needs", "n": nd, "text": f"{nd:,} papers have no owner"})
    sens = sum(1 for r in rows if r["sensitive"] and any(r["path"].startswith(s) for s in ctx.synced))
    if sens:
        issues.append({"kind": "problem", "n": sens, "text": f"{sens} sensitive files in iCloud-synced folders"})
    dup = sum(1 for r in rows if r["id"] in ctx.extra_copies)
    if dup:
        issues.append({"kind": "problem", "n": dup, "text": f"{dup:,} extra identical copies"})
    err = sum(1 for r in rows if r["errors"])
    if err:
        issues.append({"kind": "problem", "n": err, "text": f"{err} damaged or unreadable files"})
    cl = sum(1 for r in rows if r["cloud_only"])
    if cl:
        issues.append({"kind": "info", "n": cl, "text": f"{cl:,} stored in iCloud only (content not read)"})
    return {**a, "docs": len(docs), "owned": sum(1 for r in docs if r["entity"]), "issues": issues,
            "types": c(lambda r: r["kind"]), "owners": c(lambda r: r["entity"]), "topics": c(lambda r: r["topic"]),
            "years": sorted(([k, n] for k, n in Counter(r["year"] for r in rows if r["year"]).items()), key=lambda x: x[0])[-12:]}


# ---------------------------------------------------------------- monitor
def health_strip(cfg, cat, scope=("", []), since=None):
    from . import insights as I
    a = (" AND " + scope[0]) if scope[0] else ""
    q = lambda sql, p=(): cat.db.execute(sql + a, list(p) + scope[1]).fetchone()
    paper = f"(unit='file' AND (kind IN {PAPERS} OR (kind='Photo' AND doc_type IS NOT NULL AND doc_type!='Screenshot')))"
    docs, owned = q(f"SELECT sum({paper}), sum({paper} AND entity IS NOT NULL) FROM files f WHERE 1=1")
    size, cloud = q("SELECT coalesce(sum(size),0), sum(cloud_only) FROM files f WHERE 1=1")
    new = q("SELECT count(*) FROM files f WHERE scanned_at > ?", (since or time.time(),))[0] if since else 0
    out = {"docs": docs or 0, "owned": owned or 0, "pct": round(100 * (owned or 0) / max(1, docs or 0)), "needs": (docs or 0) - (owned or 0),
           "size": size, "cloud": cloud or 0, "alerts": sum(1 for x in I.alerts(cfg, cat, scope) if not x["dismissed"]) if not scope[0] else None,
           "last_scan": (cat.get_meta("last_scan") or {}).get("at"), "new": new, "since": since}
    today = datetime.date.today()
    prev = f"{today.year if today.month > 1 else today.year - 1}-{(today.month - 2) % 12 + 1:02d}"
    snap = cat.get_meta("snap:" + prev)
    if snap and not scope[0]:
        out["trend"] = {"size": out["size"] - snap.get("bytes", 0), "needs": out["needs"] - snap.get("needs_owner", out["needs"]),
                        "labelled": cat.db.execute("SELECT count(*) FROM decisions").fetchone()[0] - snap.get("labelled", 0),
                        "owned_pct": (out["pct"] - snap["owned_pct"]) if "owned_pct" in snap else None, "vs": prev}
    return out


def visit(cat, user):
    """Remember this visit; return the previous one (for 'changes since your last visit')."""
    k = "visit:" + user
    v = cat.get_meta(k) or {}
    now = time.time()
    if now - v.get("now", 0) > 1800:  # a new visit after 30 minutes away
        v = {"prev": v.get("now"), "now": now}
    else:
        v["now"] = now
    cat.set_meta(k, v)
    return v.get("prev")


def stamp(cat):
    return [(cat.get_meta("last_scan") or {}).get("at"), cat.db.execute("SELECT max(id) FROM changes").fetchone()[0],
            cat.db.execute("SELECT max(id) FROM sort_runs").fetchone()[0]]
