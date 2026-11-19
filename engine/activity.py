"""Who used it: sign-ins (and failed attempts), sign-outs and pages opened, per account and device, kept 90 days inside
the encrypted catalogue. Only admins see it (Settings → Who used it). Changes people made are already recorded in
`changes` (labels, rules, settings) and `sort_runs` (moves); this view shows them beside the sign-ins.
Nothing here ever leaves this computer."""
import threading, time

SCHEMA = """CREATE TABLE IF NOT EXISTS access_log(id INTEGER PRIMARY KEY, t REAL, username TEXT, event TEXT, detail TEXT,
  ip TEXT, device TEXT);
CREATE INDEX IF NOT EXISTS access_log_t ON access_log(t);"""
KEEP_DAYS = 90
PAGE_EVERY = 600  # one "opened" entry per person, page and device every 10 minutes
_seen, _lock, _pruned = {}, threading.Lock(), [0.0]


def _db(cat):
    cat.db.executescript(SCHEMA)
    return cat.db


def record(cat, event, username, detail="", ip="", device=""):
    """event: signin | signin-failed | signout | page"""
    db = _db(cat)
    now = time.time()
    db.execute("INSERT INTO access_log(t,username,event,detail,ip,device) VALUES(?,?,?,?,?,?)",
               (now, (username or "")[:64], event, (detail or "")[:200], (ip or "")[:64], (device or "")[:80]))
    if now - _pruned[0] > 86400:
        db.execute("DELETE FROM access_log WHERE t < ?", (now - KEEP_DAYS * 86400,))
        _pruned[0] = now
    db.commit()


def page(cat, username, path, ip, device):
    key = (username, path, device)
    now = time.time()
    with _lock:
        if now - _seen.get(key, 0) < PAGE_EVERY:
            return
        _seen[key] = now
    record(cat, "page", username, path, ip, device)


def summary(cat, users, limit=300):
    """Accounts with their last sign-in and 30-day counts, the latest events, and the latest changes and sorter runs."""
    db = _db(cat)
    since = time.time() - 30 * 86400
    counts = {}
    for u, ev, n in db.execute("SELECT username, event, count(*) FROM access_log WHERE t >= ? GROUP BY 1, 2", (since,)):
        counts.setdefault(u, {})[ev] = n
    last_dev = {u: (d, ip, t) for u, d, ip, t in db.execute(
        "SELECT username, device, ip, max(t) FROM access_log WHERE event='signin' GROUP BY username")}
    accounts = []
    for u in users:
        c = counts.get(u["username"], {})
        d = last_dev.get(u["username"])
        accounts.append({"username": u["username"], "display": u.get("display"), "role": u.get("role"),
                         "last_login": u.get("last_login"), "signins_30d": c.get("signin", 0),
                         "failed_30d": c.get("signin-failed", 0), "pages_30d": c.get("page", 0),
                         "last_device": d[0] if d else None, "last_ip": d[1] if d else None})
    known = {u["username"] for u in users}
    unknown_failed = sum(n for u, c in counts.items() if u not in known for e, n in c.items() if e == "signin-failed")
    events = [dict(zip(("t", "username", "event", "detail", "ip", "device"), r)) for r in db.execute(
        "SELECT t, username, event, detail, ip, device FROM access_log ORDER BY t DESC LIMIT ?", (limit,))]
    changes = [dict(zip(("t", "by", "what", "summary", "n", "undone"), r)) for r in db.execute(
        "SELECT t, by, action, summary, n, undone FROM changes ORDER BY t DESC LIMIT 60")]
    try:
        runs = [dict(zip(("t", "by", "summary", "moved", "undone"), r)) for r in db.execute(
            "SELECT t, by, summary, moved, undone FROM sort_runs ORDER BY t DESC LIMIT 20")]
    except Exception:
        runs = []
    return {"accounts": accounts, "events": events, "changes": changes, "runs": runs, "keep_days": KEEP_DAYS,
            "unknown_failed_30d": unknown_failed}
