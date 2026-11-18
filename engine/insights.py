"""Learning, recommendations, monthly pattern report and missing-document alerts.
Everything here only reads the catalogue. Thresholds and expectations come from the profile ('insights').
Proposals are suggestions: nothing is applied until a person approves it (and every approval can be undone)."""
import os, re, json, time, statistics, datetime as dt
from collections import Counter, defaultdict

TODAY = lambda: dt.date.today()
MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
CONF_OK = "(f.doc_conf IN ('high','medium','you'))"


def _ins(cfg):
    return cfg.get("insights", {})


def dismissed(cat):
    now = time.time()
    return {r[0] for r in cat.db.execute("SELECT key FROM dismissed WHERE until IS NULL OR until > ?", (now,))}


def dismiss(cat, key, by, days=None):
    cat.db.execute("INSERT OR REPLACE INTO dismissed VALUES(?,?,?,?)", (key, time.time(), by, time.time() + days * 86400 if days else None))
    cat.db.commit()


def undismiss(cat, key):
    cat.db.execute("DELETE FROM dismissed WHERE key=?", (key,)); cat.db.commit()


def _d(s):
    try:
        return dt.date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


# ------------------------------------------------------------------ recommendations
def synced_roots(cfg, cat):
    """Roots whose files are kept in a cloud (iCloud): seen from iCloud-only files there, or the iCloud root itself."""
    out = []
    for r in cfg.roots:
        from . import platforms
        if platforms.cloud_label(r) or cat.db.execute("SELECT 1 FROM files WHERE cloud_only=1 AND path LIKE ? LIMIT 1", (r + "/%",)).fetchone():
            out.append(r)
    return out


def rec_defs(cfg, cat):
    """Each recommendation is a named, read-only query. The search page can show its files with ?rec=<id>."""
    R = _ins(cfg).get("recommendations", {})
    lif = cfg.get("lifecycles", {})
    synced = synced_roots(cfg, cat)
    in_cloud = "(" + " OR ".join(["f.path LIKE ?"] * len(synced)) + ")" if synced else "0"
    cloud_p = [s + "/%" for s in synced]
    lc = []
    for name, span in lif.items():
        m = re.fullmatch(r"(\d+)d", span or "")
        if m:
            lc.append((name, int(m[1])))
    dl = os.path.join(os.path.expanduser("~"), "Downloads")
    defs = [
        {"id": "sensitive-in-cloud", "level": "important", "title": "Sensitive files stored in iCloud",
         "why": "Your rule: keys, passwords and recovery codes are never kept in iCloud. Move these to a local-only folder.",
         "where": f"f.sensitive=1 AND {in_cloud}", "params": cloud_p},
        {"id": "dup-copies", "level": "space", "title": "Identical copies",
         "why": "Same content stored more than once. Keep one copy of each.",
         "where": "f.hash IN (SELECT hash FROM files WHERE hash IS NOT NULL AND unit='file' GROUP BY hash HAVING count(*)>1)", "params": [],
         "extra_sql": "SELECT count(*)-count(DISTINCT hash), sum(size)-sum(size)/count(*)*count(DISTINCT hash) FROM files f WHERE {w}"},
        {"id": "large-old", "level": "space", "title": f"Large files not touched for {R.get('large_old_years', 2)}+ years",
         "why": f"Over {R.get('large_file_mb', 500)} MB each. Candidates for an external drive or deleting.",
         "where": "f.unit='file' AND f.size>? AND f.date < date('now', ?)", "params": [R.get("large_file_mb", 500) * 1048576, f"-{R.get('large_old_years', 2)} year"]},
        {"id": "installers", "level": "space", "title": "Installers and disk images",
         "why": "Usually not needed once the app is installed; can be downloaded again.",
         "where": "f.kind='Installer'", "params": []},
        {"id": "old-downloads", "level": "tidy", "title": f"Downloads older than {R.get('downloads_old_days', 180)} days",
         "why": "Downloads is a landing place. Older items should be filed or removed.",
         "where": "f.unit='file' AND f.path LIKE ? AND f.date < date('now', ?)", "params": [dl + "/%", f"-{R.get('downloads_old_days', 180)} day"]},
        {"id": "old-screenshots", "level": "tidy", "title": f"Screenshots older than {R.get('screenshot_old_months', 6)} months",
         "why": "Screenshots are mostly short-lived. Keep the useful ones, remove the rest.",
         "where": "f.doc_type='Screenshot' AND f.date < date('now', ?)", "params": [f"-{R.get('screenshot_old_months', 6)} month"]},
        {"id": "damaged", "level": "tidy", "title": "Files that could not be read",
         "why": "Damaged or incomplete (e.g. broken zip, unreadable image). Check, replace from backup, or remove.",
         "where": "f.errors IS NOT NULL", "params": []},
        {"id": "owner-suggested", "level": "label", "title": "Owner suggested, waiting for you",
         "why": "The engine found a likely owner but is not sure. One click each on the search page.",
         "where": "f.entity IS NULL AND f.suggestions IS NOT NULL AND coalesce(f.entity_conf,'') NOT LIKE 'you%' AND coalesce(f.kind,'') NOT IN ('Code','Font','Installer')", "params": []},
    ]
    for name, days in lc:
        defs.append({"id": f"lifecycle-{name.lower()}", "level": "tidy", "title": f"{name} files past {days} days",
                     "why": f"Their topic is marked {name} ({days} days). Review: keep, archive or remove.",
                     "where": "f.lifecycle=? AND f.date < date('now', ?)", "params": [name, f"-{days} day"]})
    return defs


def rec_where(cfg, cat, rid):
    for d in rec_defs(cfg, cat):
        if d["id"] == rid:
            return d["where"], d["params"]
    return None


def recommendations(cfg, cat, scope=("", [])):
    gone, out = dismissed(cat), []
    a = (" AND " + scope[0]) if scope[0] else ""
    for d in rec_defs(cfg, cat):
        w = d["where"] + a
        p = d["params"] + scope[1]
        n, size = cat.db.execute(f"SELECT count(*), sum(size) FROM files f WHERE {w}", p).fetchone()
        x = {"id": d["id"], "level": d["level"], "title": d["title"], "why": d["why"], "n": n, "size": size or 0,
             "dismissed": ("rec:" + d["id"]) in gone}
        if d.get("extra_sql") and n:
            x["extra"], x["size"] = cat.db.execute(d["extra_sql"].format(w=w), p).fetchone()
        if n:
            out.append(x)
    return out


# ------------------------------------------------------------------ learning: proposals
def _rel(cfg, path):
    pl = path.lower()
    for r in cfg.roots:
        if pl.startswith(r.lower() + "/"):
            return pl[len(r) + 1:]
    return pl


def _tokens(s, minlen, stop):
    return {t for t in re.findall(r"[a-zऀ-ॿ][a-zऀ-ॿ0-9]+", s.lower()) if len(t) >= minlen and t not in stop and not t.isdigit()}


def proposals(cfg, cat):
    ins, gone = _ins(cfg), dismissed(cat)
    fc, mn = ins.get("folder_consensus", {}), ins.get("mining", {})
    ents = {e["name"]: e for e in cfg.get("entities", [])}
    tops = {t["name"]: t for t in cfg.get("topics", [])}
    gl = cfg.get("group_labels") or {}
    labels = set(gl.values())
    # folders made by date or for unsorted/duplicate files say nothing about who a file belongs to
    no_owner_groups = [v.lower() for k, v in gl.items() if k in ("Media", "Unsorted", "Duplicates", "Testing")]
    out = []
    # 1) folder consensus: a folder where nearly every file with an owner has the same owner
    fold = defaultdict(lambda: {"owned": Counter(), "none": []})
    for fid, p, e, conf in cat.db.execute("SELECT id,path,entity,entity_conf FROM files WHERE unit='file'"):
        f = fold[os.path.dirname(p)]
        if e:
            f["owned"][e] += 1
        elif not (conf or "").startswith("you"):
            f["none"].append(fid)
    for d, f in fold.items():
        tot = sum(f["owned"].values())
        if not f["none"] or not tot:
            continue
        owner, n = f["owned"].most_common(1)[0]
        cover = tot / (tot + len(f["none"]))
        base = os.path.basename(d)
        parts = [x.lower() for x in d.split("/")]
        generic = base in labels or base.lower() in ("downloads", "desktop", "documents") or any(g in parts for g in no_owner_groups)
        if n >= fc.get("min_owned", 3) and n / tot >= fc.get("purity", 0.9) and cover >= fc.get("coverage", 0.5) and not generic and owner in ents:
            key = f"folder:{d}:{owner}"
            if key not in gone:
                out.append({"key": key, "kind": "label", "title": f"Set owner {owner} on {len(f['none'])} file(s) in a folder that is mostly {owner}'s",
                            "evidence": f"{n} of {tot} files with an owner in this folder belong to {owner}; {len(f['none'])} have none.",
                            "folder": d, "owner": owner, "ids": f["none"], "n": len(f["none"]), "confidence": round(n / tot * cover, 2)})
    # 2) learn from your own decisions: a word in file/folder names that marks one owner or topic
    stop = set((mn.get("stopwords") or "").split())
    minlen, support, prec = mn.get("min_len", 4), mn.get("min_support", 3), mn.get("precision", 0.9)
    files = cat.db.execute("SELECT id,path,entity,entity_conf,topic FROM files WHERE unit='file'").fetchall()
    decided = cat.db.execute("SELECT path,fields FROM decisions").fetchall()
    if decided:
        dec = {p: json.loads(fl) for p, fl in decided}
        for field, pool, existing in (("entity", ents, lambda n: ents[n].get("aliases", [])), ("topic", tops, lambda n: tops[n].get("keywords", []))):
            by_val = defaultdict(Counter)
            for p, fl in dec.items():
                v = fl.get(field)
                if v and v in pool:
                    for t in _tokens(_rel(cfg, p), minlen, stop):
                        by_val[v][t] += 1
            for v, toks in by_val.items():
                have = " ".join(existing(v)).lower()
                for t, sup in toks.items():
                    if sup < support or t in have:
                        continue
                    rxw = re.compile(r"\b" + re.escape(t) + r"\b")
                    a = b = 0; gain = []
                    for fid, p, e, conf, tp in files:
                        if not rxw.search(_rel(cfg, p)):
                            continue
                        cur = e if field == "entity" else tp
                        if cur == v:
                            a += 1
                        elif cur:
                            b += 1
                        else:
                            gain.append(fid)
                    if a and a / (a + b) >= prec and gain:
                        what = "owner" if field == "entity" else "topic"
                        key = f"word:{field}:{v}:{t}"
                        if key not in gone:
                            out.append({"key": key, "kind": "rule", "field": field, "value": v, "word": t,
                                        "title": f"Teach a rule: files named with “{t}” → {what} {v}",
                                        "evidence": f"You set {what} {v} on {sup} file(s) containing “{t}”. Of all files containing it with {'an' if what == 'owner' else 'a'} {what}, "
                                                    f"{a} of {a + b} are {v}. The rule would label {len(gain)} more.",
                                        "n": len(gain), "ids": gain, "confidence": round(a / (a + b), 2)})
    out.sort(key=lambda x: (-x["confidence"], -x["n"]))
    return out


# ------------------------------------------------------------------ alerts: missing / expiring / overdue
def _parse_date(s, order="dmy"):
    s = s.strip().lower().replace(",", " ")
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", s)
    try:
        if m:
            a, b, y = int(m[1]), int(m[2]), int(m[3])
            y += 2000 if y < 100 else 0
            d, mo = (a, b) if order == "dmy" else (b, a)
            return dt.date(y, mo, d)
        m = re.fullmatch(r"(\d{1,2})[ -]?([a-z]{3,9})[ -]*(\d{4})", s)
        if m and m[2][:3] in MONTHS:
            return dt.date(int(m[3]), MONTHS[m[2][:3]], int(m[1]))
    except ValueError:
        return None
    return None


def alerts(cfg, cat, scope=("", [])):
    ins, gone, today, out = _ins(cfg), dismissed(cat), TODAY(), []
    a = (" AND " + scope[0]) if scope[0] else ""
    ents = cfg.get("entities", [])
    # 1) expected documents per owner type
    have = defaultdict(set)
    # existence check: a document recognised only by its name still counts (a missed alert is cheaper than a false one)
    for e, t in cat.db.execute(f"SELECT f.entity, f.doc_type FROM files f WHERE f.entity IS NOT NULL AND f.doc_type IS NOT NULL{a}", scope[1]):
        have[e].add(t)
    allowed = set(scope[1]) if scope[0] else None
    for e in ents:
        if allowed is not None and e["name"] not in allowed:
            continue
        want = e.get("expect", (ins.get("expected_docs") or {}).get(e["type"], []))
        for t in want:
            if t not in have[e["name"]]:
                out.append({"key": f"missing:{e['name']}:{t}", "kind": "missing", "level": "important", "owner": e["name"], "doc_type": t,
                            "title": f"No {t} found for {e['name']}",
                            "why": f"Expected for every {e['type']} owner. If it exists, label it (owner + document type) so it is found; "
                                   f"if it is only on paper, scan it."})
    # 2) annual documents per financial / calendar year
    ys, due, back = ins.get("year_start_month", 1), ins.get("annual_due_month", 12), ins.get("annual_lookback_years", 5)
    fy = lambda d: d.year if d.month >= ys else d.year - 1
    label = lambda y: f"{y}-{str(y + 1)[2:]}" if ys != 1 else str(y)
    for e in ents:
        if allowed is not None and e["name"] not in allowed:
            continue
        for t in e.get("expect_yearly", (ins.get("annual_docs") or {}).get(e["type"], [])):
            years = set()
            for (d,) in cat.db.execute(f"SELECT f.date FROM files f WHERE f.entity=? AND f.doc_type=? AND {CONF_OK}", (e["name"], t)):
                dd = _d(d)
                if dd:
                    years.add(fy(dd))
            if not years:
                continue
            # a year's document normally arrives after that year ends; it is overdue once the due month has passed
            last_due = fy(today) - 1 if (today.month >= due or today.month < ys) else fy(today) - 2
            for y in range(max(min(years), last_due - back + 1), last_due + 1):
                # a document dated in the following year usually belongs to this year (e.g. a return filed in July)
                if y not in years and (y + 1) not in years:
                    out.append({"key": f"annual:{e['name']}:{t}:{y}", "kind": "missing", "level": "important", "owner": e["name"], "doc_type": t,
                                "title": f"{t} for {label(y)} not found ({e['name']})",
                                "why": f"Found for other years ({', '.join(label(x) for x in sorted(years)[-4:])}), not for {label(y)}."})
    # 3) expiring / expired (latest document of each owner + type)
    pats = [re.compile(p, re.I) for p in ins.get("expiry_patterns", [])]
    warn = ins.get("expiry_warn_days", 180)
    types = ins.get("expiry_doc_types", [])
    if types and pats:
        latest = {}
        q = (f"SELECT f.id,f.entity,f.doc_type,f.path,x.body FROM files f JOIN fts x ON x.rowid=f.id WHERE f.doc_type IN ({','.join('?' * len(types))}) "
             f"AND {CONF_OK}{a}")
        for fid, e, t, p, body in cat.db.execute(q, types + scope[1]):
            ds = [d for pat in pats for m in pat.finditer((body or "")[:20000]) if (d := _parse_date(m.group(1), ins.get("date_order", "dmy")))]
            ds = [d for d in ds if 1990 < d.year < 2100]
            if ds:
                k = (e or "owner unknown", t)
                d = max(ds)
                if k not in latest or d > latest[k][0]:
                    latest[k] = (d, fid, p)
        for (e, t), (d, fid, p) in latest.items():
            left = (d - today).days
            if left <= warn:
                st = "expired" if left < 0 else "expires"
                out.append({"key": f"expiry:{e}:{t}:{d}", "kind": "expiry", "level": "important" if left < 60 else "soon", "owner": e, "doc_type": t,
                            "id": fid, "date": d.isoformat(), "title": f"{t} ({e}) {st} {d.strftime('%d %b %Y')}",
                            "why": (f"Expired {-left} days ago, and no newer one was found." if left < 0 else f"{left} days left.") +
                                   " Read from the document text; check the date on the document."})
    # 4) learned rhythm: owner + type that arrive regularly, now overdue
    S = ins.get("series", {})
    rows = defaultdict(list)
    for e, t, d in cat.db.execute(f"SELECT f.entity,f.doc_type,f.date FROM files f WHERE f.entity IS NOT NULL AND f.doc_type IS NOT NULL AND {CONF_OK}{a}", scope[1]):
        dd = _d(d)
        if dd:
            rows[(e, t)].append(dd)
    for (e, t), ds in rows.items():
        ds = sorted(set(ds))
        if len(ds) < S.get("min_docs", 4):
            continue
        gaps = [(b - a_).days for a_, b in zip(ds, ds[1:]) if (b - a_).days > 3]
        if len(gaps) < 3:
            continue
        g = statistics.median(gaps)
        if not S.get("min_gap_days", 20) <= g <= S.get("max_gap_days", 400):
            continue
        regular = sum(0.5 * g <= x <= 1.6 * g for x in gaps) / len(gaps)
        if regular < S.get("regularity", 0.75):
            continue
        since = (today - ds[-1]).days
        if since > S.get("overdue_factor", 2.0) * g and since < S.get("active_years", 2) * 365:
            out.append({"key": f"rhythm:{e}:{t}:{ds[-1]}", "kind": "overdue", "level": "soon", "owner": e, "doc_type": t,
                        "title": f"{t} for {e}: none since {ds[-1].strftime('%b %Y')}",
                        "why": f"Usually arrives about every {round(g)} days ({len(ds)} found, {round(regular * 100)}% on rhythm). "
                               f"Last one is {since} days old."})
    for x in out:
        x["dismissed"] = x["key"] in gone
    order = {"important": 0, "soon": 1}
    out.sort(key=lambda x: (x["dismissed"], order.get(x["level"], 2), x["title"]))
    return out


# ------------------------------------------------------------------ monthly pattern report
def _month_bounds(ym):
    y, m = map(int, ym.split("-"))
    start = dt.date(y, m, 1)
    end = dt.date(y + (m == 12), m % 12 + 1, 1)
    return start, end


def _prev(ym, k=1):
    y, m = map(int, ym.split("-"))
    m -= k
    while m < 1:
        m += 12; y -= 1
    return f"{y}-{m:02d}"


def snapshot(cat):
    q = lambda s: cat.db.execute(s).fetchone()
    tot = q("SELECT count(*), sum(size) FROM files")
    return {"files": tot[0], "bytes": tot[1] or 0,
            "needs_owner": q("SELECT count(*) FROM files WHERE entity IS NULL AND (suggestions IS NOT NULL OR topic IS NOT NULL) AND coalesce(entity_conf,'') NOT LIKE 'you%' AND coalesce(kind,'') NOT IN ('Code','Font','Installer')")[0],
            "dup_extra": q("SELECT count(*)-count(DISTINCT hash) FROM files WHERE hash IN (SELECT hash FROM files WHERE hash IS NOT NULL AND unit='file' GROUP BY hash HAVING count(*)>1)")[0],
            "cloud_only": q("SELECT count(*) FROM files WHERE cloud_only=1")[0], "labelled": q("SELECT count(*) FROM decisions")[0],
            "owned_pct": round(100 * q("SELECT count(*) FROM files WHERE unit='file' AND entity IS NOT NULL AND coalesce(kind,'') NOT IN ('Code','Font','Installer')")[0]
                               / max(1, q("SELECT count(*) FROM files WHERE unit='file' AND coalesce(kind,'') NOT IN ('Code','Font','Installer')")[0])),
            "by_kind": dict(cat.db.execute("SELECT kind, sum(size) FROM files GROUP BY kind").fetchall()), "at": time.time()}


def report(cfg, cat, ym=None):
    today = TODAY()
    ym = ym or f"{today.year}-{today.month:02d}"
    start, end = _month_bounds(ym)
    s, e = start.isoformat(), end.isoformat()
    q = lambda sql, *p: cat.db.execute(sql, p).fetchall()
    def group(col, a, b):
        return [[r[0] or "(none)", r[1], r[2] or 0] for r in q(f"SELECT {col}, count(*), sum(size) FROM files WHERE unit='file' AND date>=? AND date<? GROUP BY 1 ORDER BY 2 DESC LIMIT 12", a, b)]
    cur = q("SELECT count(*), sum(size) FROM files WHERE unit='file' AND date>=? AND date<?", s, e)[0]
    prev_s, _ = _month_bounds(_prev(ym))
    prev = q("SELECT count(*), sum(size) FROM files WHERE unit='file' AND date>=? AND date<?", prev_s.isoformat(), s)[0]
    y_s, _ = _month_bounds(_prev(ym, 12))
    avg = q("SELECT count(*)/12.0, sum(size)/12.0 FROM files WHERE unit='file' AND date>=? AND date<?", y_s.isoformat(), s)[0]
    trend = []
    for k in range(11, -1, -1):
        m = _prev(ym, k); a_, b_ = _month_bounds(m)
        n, sz = q("SELECT count(*), sum(size) FROM files WHERE unit='file' AND date>=? AND date<?", a_.isoformat(), b_.isoformat())[0]
        trend.append([m, n, sz or 0])
    folders = [[os.path.dirname(r[0]).replace(os.path.expanduser("~"), "~"), r[1]] for r in q(
        "SELECT path, count(*) FROM files WHERE unit='file' AND date>=? AND date<? GROUP BY substr(path,1,length(path)-length(name)-1) ORDER BY 2 DESC LIMIT 8", s, e)]
    new_dups = q("SELECT count(*) FROM files f WHERE f.unit='file' AND f.date>=? AND f.date<? AND f.hash IN "
                 "(SELECT hash FROM files WHERE hash IS NOT NULL GROUP BY hash HAVING count(*)>1)", s, e)[0][0]
    changes = q("SELECT count(*), coalesce(sum(n),0) FROM changes WHERE t>=? AND t<? AND action!='undo'",
                time.mktime(start.timetuple()), time.mktime(end.timetuple()))[0]
    snap_prev = cat.get_meta("snap:" + _prev(ym))
    snap_now = snapshot(cat) if ym == f"{today.year}-{today.month:02d}" else cat.get_meta("snap:" + ym)
    notes = []
    if avg[0] and cur[0] > 2 * avg[0]:
        notes.append(f"Busy month: {cur[0]:,} files, more than double the 12-month average ({avg[0]:.0f}).")
    elif avg[0] and cur[0] < 0.4 * avg[0] and end <= today:
        notes.append(f"Quiet month: {cur[0]:,} files against a 12-month average of {avg[0]:.0f}.")
    k = group("kind", s, e)
    if k and cur[0] and k[0][1] / cur[0] > 0.6:
        notes.append(f"Mostly {k[0][0].lower()}s ({k[0][1]:,} of {cur[0]:,}).")
    un = q("SELECT count(*) FROM files WHERE unit='file' AND date>=? AND date<? AND entity IS NULL", s, e)[0][0]
    if cur[0] and un / cur[0] > 0.5:
        notes.append(f"{un:,} of this month's files have no owner yet.")
    if new_dups:
        notes.append(f"{new_dups:,} files dated this month have an identical copy somewhere.")
    if snap_prev and snap_now:
        dg = (snap_now["bytes"] - snap_prev["bytes"]) / 1073741824
        notes.append(f"Catalogue size changed by {dg:+.1f} GB since last month's snapshot.")
    rep = {"month": ym, "generated": time.time(), "partial": end > today,
           "files": cur[0], "bytes": cur[1] or 0, "prev_files": prev[0], "prev_bytes": prev[1] or 0,
           "avg_files": round(avg[0] or 0, 1), "avg_bytes": avg[1] or 0,
           "by_kind": k, "by_owner": group("entity", s, e), "by_topic": group("topic", s, e), "by_doc_type": group("doc_type", s, e),
           "trend": trend, "folders": folders, "new_dups": new_dups, "label_changes": list(changes),
           "snapshot": snap_now, "snapshot_prev": snap_prev, "notes": notes,
           "alerts": len([x for x in alerts(cfg, cat) if not x["dismissed"]]),
           "recs": [[r["title"], r["n"]] for r in recommendations(cfg, cat) if not r["dismissed"]][:8]}
    return rep


def auto(cfg, cat, log=print):
    """Once a month: keep a snapshot and the report for the month that just ended."""
    if not _ins(cfg).get("auto_report", True):
        return
    today = TODAY()
    this = f"{today.year}-{today.month:02d}"
    if not cat.get_meta("snap:" + this):
        cat.set_meta("snap:" + this, snapshot(cat))
    last = _prev(this)
    if not cat.get_meta("report:" + last):
        cat.set_meta("report:" + last, report(cfg, cat, last))
        log(f"monthly pattern report for {last} saved")


def saved_reports(cat):
    return [r[0][7:] for r in cat.db.execute("SELECT k FROM meta WHERE k LIKE 'report:%' ORDER BY k DESC")]
