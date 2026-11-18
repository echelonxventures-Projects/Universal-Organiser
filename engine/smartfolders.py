"""Smart folders: saved views that update themselves (nothing is moved).

A definition is a small JSON object with whitelisted keys only:
  doc_types [..] / topics [..]   - files of any of these document types OR topics (sub-topics included)
  year "current" | "previous" | "YYYY",  recent_days N (added or changed in the last N days),  no_owner true,
  q "...", filters {facet: value}   - a saved search (opened on the search page as typed)
"""
import json, time, datetime

SCHEMA = "CREATE TABLE IF NOT EXISTS smart_folders(id INTEGER PRIMARY KEY, name TEXT, def TEXT, builtin INTEGER, t REAL, by TEXT)"
from . import doctypes


def defaults():
    """Built-in smart folders, made from document-type tags so each region pack fills them with its own documents."""
    T = doctypes.tagged
    return [
        ("Identity documents", {"doc_types": T("id")}),
        ("Tax & salary", {"doc_types": T("tax"), "topics": ["Finance/Tax"]}),
        ("Insurance", {"doc_types": T("insurance"), "topics": ["Insurance"]}),
        ("Medical", {"doc_types": T("medical"), "topics": ["Medical"]}),
        ("Property & rent", {"doc_types": [n for n in T("property") if n not in T("vehicle")], "topics": ["Property"]}),
        ("Education", {"doc_types": T("education"), "topics": ["Education"]}),
        ("Travel this year", {"doc_types": T("travel"), "topics": ["Travel"], "year": "current"}),
        ("Added in the last 30 days", {"recent_days": 30}),
        ("Important papers without an owner", {"doc_types": T("paper"), "no_owner": True}),
    ]


KEYS = {"doc_types", "topics", "year", "recent_days", "no_owner", "q", "filters"}


def ensure(cat):
    cat.db.execute(SCHEMA)
    if not cat.db.execute("SELECT 1 FROM smart_folders WHERE builtin=1 LIMIT 1").fetchone():
        for n, d in defaults():
            cat.db.execute("INSERT INTO smart_folders(name,def,builtin,t,by) VALUES(?,?,1,?,?)", (n, json.dumps(d), time.time(), "engine"))
        cat.db.commit()


def get(cat, sid):
    ensure(cat)
    r = cat.db.execute("SELECT id,name,def,builtin FROM smart_folders WHERE id=?", (sid,)).fetchone()
    if not r:
        return None
    d = dict(r); d["def"] = json.loads(d["def"])
    return d


def where(cfg, sf):
    """SQL for the structured part of a definition (a saved search's q/filters are applied by the page)."""
    d, w, p = sf["def"], [], []
    anyof = []
    if d.get("doc_types"):
        anyof.append(f"f.doc_type IN ({','.join('?' * len(d['doc_types']))})"); p += d["doc_types"]
    for t in d.get("topics") or []:
        anyof.append("(f.topic = ? OR f.topic LIKE ?)"); p += [t, t + "/%"]
    if anyof:
        w.append("(" + " OR ".join(anyof) + ")")
    y = d.get("year")
    if y:
        this = datetime.date.today().year
        w.append("f.year = ?"); p.append(str(this if y == "current" else this - 1 if y == "previous" else y))
    if d.get("recent_days"):
        w.append("f.mtime >= ?"); p.append(time.time() - 86400 * int(d["recent_days"]))
    if d.get("no_owner"):
        w.append("f.entity IS NULL")
    return (" AND ".join(w) or "1=1"), p


def listing(cfg, cat, scope=("", []), counter=None):
    ensure(cat)
    out = []
    a = (" AND " + scope[0]) if scope[0] else ""
    for r in cat.db.execute("SELECT id,name,def,builtin FROM smart_folders ORDER BY builtin DESC, id"):
        d = {"id": r[0], "name": r[1], "def": json.loads(r[2]), "builtin": r[3]}
        if d["def"].get("q") or d["def"].get("filters"):
            d["n"] = counter(d["def"]) if counter else None
        else:
            w, p = where(cfg, d)
            d["n"] = cat.db.execute(f"SELECT count(*) FROM files f WHERE f.unit='file' AND {w}{a}", p + scope[1]).fetchone()[0]
        out.append(d)
    return out


def save(cat, name, definition, by):
    ensure(cat)
    name = (name or "").strip()[:80]
    if not name:
        raise ValueError("Give the smart folder a name.")
    d = {k: v for k, v in (definition or {}).items() if k in KEYS}
    if not d:
        raise ValueError("Nothing to save.")
    cur = cat.db.execute("INSERT INTO smart_folders(name,def,builtin,t,by) VALUES(?,?,0,?,?)", (name, json.dumps(d, ensure_ascii=False), time.time(), by))
    cat.db.commit()
    return cur.lastrowid


def delete(cat, sid):
    ensure(cat)
    cat.db.execute("DELETE FROM smart_folders WHERE id=? AND builtin=0", (sid,)); cat.db.commit()
