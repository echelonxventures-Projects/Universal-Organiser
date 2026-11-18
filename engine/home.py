"""Home dashboard and person pages: one place that says what matters today.

Actions are collected from alerts, recommendations, the triage queue, the action plan, unread pages and similar photos,
then ranked by a simple importance score (privacy and identity papers first, then money and space)."""
import time, datetime
from . import insights as I


def _gb(n):
    return f"{(n or 0) / 1073741824:.1f} GB"


def actions(cfg, cat, server_triage):
    out = []
    for a in I.alerts(cfg, cat):
        if a["dismissed"]:
            continue
        score = {"expiry": 95 if a["level"] == "important" else 70, "missing": 75, "overdue": 60}.get(a["kind"], 50)
        if a["kind"] == "expiry" and a.get("date") and a["date"] < (datetime.date.today() - datetime.timedelta(days=3 * 365)).isoformat():
            score = 58  # expired long ago: worth knowing, not urgent
        out.append({"score": score, "title": a["title"], "why": a["why"], "kind": "alert",
                    "link": f"/?open={a['id']}" if a.get("id") else f"/person?name={a['owner']}" if a.get("owner") not in (None, "owner unknown") else "/insights#alerts",
                    "button": "Open document" if a.get("id") else "See person" if a.get("owner") not in (None, "owner unknown") else "Open"})
    for r in I.recommendations(cfg, cat):
        if r["dismissed"] or not r["n"]:
            continue
        score = {"important": 90, "space": 40 + min(30, (r["size"] or 0) / 1073741824), "tidy": 35, "label": 55}.get(r["level"], 30)
        out.append({"score": score, "title": f"{r['title']} ({r['n']:,})", "why": r["why"] + (f" {_gb(r['size'])}." if r["level"] == "space" else ""),
                    "kind": "rec", "link": f"/?rec={r['id']}&rect={r['title']}", "button": "Show files"})
    t = server_triage(cfg, cat, "tosort", 1)
    imp = dict(t["buckets"]).get("important documents", 0)
    if imp:
        out.append({"score": 85, "title": f"{imp:,} important documents have no owner", "why": "IDs, money and certificates in To Sort. "
                    "Triage shows them one at a time; about 5 seconds each.", "kind": "triage", "link": "/triage", "button": "Start triage"})
    elif t["remaining"]:
        out.append({"score": 45, "title": f"{t['remaining']:,} files in To Sort have no owner", "why": "Label them in Triage, then file them with the Sorter.",
                    "kind": "triage", "link": "/triage", "button": "Start triage"})
    planned = cat.db.execute("SELECT count(*) FROM plan").fetchone()[0]
    if planned:
        out.append({"score": 50, "title": f"{planned:,} files wait in your action plan", "why": "Run them with the Sorter (preview first, undo after).",
                    "kind": "plan", "link": "/sorter", "button": "Open Sorter"})
    try:
        from .deepread import candidates
        n = len(candidates(cfg, cat))
        if n:
            out.append({"score": 30, "title": f"{n} scanned PDFs have unread pages", "why": "Run `uo read-all` (or the next `uo scan` does it).",
                        "kind": "read", "link": None, "button": None})
    except Exception:
        pass
    out.sort(key=lambda x: -x["score"])
    return out


def recent(cat, limit=6):
    rows = [{"t": r[0], "what": r[1], "by": r[2]} for r in cat.db.execute(
        "SELECT t, summary, by FROM changes WHERE action != 'undo' ORDER BY id DESC LIMIT ?", (limit,))]
    rows += [{"t": r[0], "what": r[1], "by": r[2]} for r in cat.db.execute(
        "SELECT t, summary, by FROM sort_runs ORDER BY id DESC LIMIT ?", (limit,))]
    return sorted(rows, key=lambda x: -x["t"])[:limit]


def people(cfg, cat, scope=("", [])):
    allowed = set(scope[1]) if scope[0] else None
    out = []
    for e in cfg.get("entities", []):
        if allowed is not None and e["name"] not in allowed:
            continue
        n, sz = cat.db.execute("SELECT count(*), coalesce(sum(size),0) FROM files WHERE entity=? AND coalesce(sensitive,0)=0", (e["name"],)).fetchone()
        out.append({"name": e["name"], "type": e["type"], "relation": e.get("relation"), "files": n, "size": sz})
    return out


from . import doctypes


def _sections(cfg):
    """Sections of a person's page: profile "person_sections", each listing document-type tags and topics."""
    return [(s["title"], doctypes.tagged(*s.get("tags", [])), s.get("topics", [])) for s in cfg.get("person_sections", [])]


def person(cfg, cat, name, scope=("", [])):
    e = next((x for x in cfg.get("entities", []) if x["name"] == name), None)
    if not e or (scope[0] and name not in scope[1]):
        return None
    cols = "id,name,path,kind,doc_type,topic,date,size,cloud_only"
    base = "FROM files WHERE entity=? AND unit='file' AND coalesce(sensitive,0)=0"
    q = lambda extra, p=(): [dict(r) for r in cat.db.execute(f"SELECT {cols} {base} {extra}", (name,) + tuple(p))]
    total = cat.db.execute(f"SELECT count(*), coalesce(sum(size),0) {base}", (name,)).fetchone()
    have = {r[0]: r[1] for r in cat.db.execute(f"SELECT doc_type, count(*) {base} AND doc_type IS NOT NULL GROUP BY 1", (name,))}
    expected = set(e.get("expect", (cfg.get("insights", {}).get("expected_docs") or {}).get(e["type"], [])))
    ids = [{"type": t, "n": have.get(t, 0), "expected": t in expected,
            "files": q("AND doc_type=? ORDER BY date DESC LIMIT 5", (t,))} for t in doctypes.tagged("id") if have.get(t) or t in expected]
    alerts = [a for a in I.alerts(cfg, cat) if a.get("owner") == name and not a["dismissed"]]
    sections = []
    for title, dts, tops in _sections(cfg):
        cond = "(" + " OR ".join(([f"doc_type IN ({','.join('?' * len(dts))})"] if dts else []) + ["topic = ? OR topic LIKE ?" for _ in tops]) + ")"
        params = list(dts) + [x for t in tops for x in (t, t + "/%")]
        n = cat.db.execute(f"SELECT count(*) {base} AND {cond}", (name, *params)).fetchone()[0]
        if n:
            sections.append({"title": title, "n": n, "files": q(f"AND {cond} ORDER BY date DESC LIMIT 6", params), "q": f"{name.split()[0]} {title.split()[0].lower()}"})
    topics = [list(r) for r in cat.db.execute(f"SELECT coalesce(topic,'(no topic)'), count(*) {base} GROUP BY 1 ORDER BY 2 DESC LIMIT 12", (name,))]
    years = [list(r) for r in cat.db.execute(f"SELECT year, count(*) {base} AND year IS NOT NULL GROUP BY 1 ORDER BY 1 DESC LIMIT 12", (name,))]
    return {"name": name, "type": e["type"], "relation": e.get("relation"), "files": total[0], "size": total[1], "ids": ids, "alerts": alerts,
            "sections": sections, "topics": topics, "years": years, "recent": q("ORDER BY coalesce(mtime,0) DESC LIMIT 8"),
            "suggested": cat.db.execute("SELECT count(*) FROM files WHERE entity IS NULL AND suggestions LIKE ?", (f'%"{name}"%',)).fetchone()[0]}
