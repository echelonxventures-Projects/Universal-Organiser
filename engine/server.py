"""Local page: search, review, owner decisions, settings and accounts. Listens on 127.0.0.1 only.
Every request needs a signed-in session (cookie, SameSite=Strict, HttpOnly). Every API call also needs the
X-FE header and a local Host/Origin, so other web sites open in the browser cannot reach it.
Members only ever see the owners in their scope and never sensitive files. Only admins change anything,
and every change is logged with undo. Nothing here moves, renames or deletes a user file."""
import os, re, sys, json, time, secrets, socket, threading, subprocess, webbrowser, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from .config import ROOT, Config
from . import i18n as I18N
from .auth import Auth, AuthError
from . import hub as HB, setup as SU
from . import settings as S, reclassify, insights as I, analytics as AN, sorter as SO, similar as SIM, transcribe as TR, lan as LAN, query as QP, smartfolders as SF, deepread as DR, home as HM, tags as TG, overview as OV, projects as PJ, cleanup as CU

FACETS = ["kind", "entity", "doc_type", "topic", "year", "entity_type"]
FIELDS = ("id,path,name,kind,unit,size,date,year,entity,entity_type,entity_conf,suggestions,doc_type,doc_conf,topic,lifecycle,"
          "title,pages,tags,cloud_only,sensitive,protected,hash,inner_count")
TECH = "coalesce(f.kind,'') NOT IN ('Code','Font','Installer')"  # code, fonts, installers: technical, never need an owner
REVIEW_OWNER = "f.entity IS NULL AND (f.suggestions IS NOT NULL OR f.topic IS NOT NULL) AND coalesce(f.entity_conf,'') NOT LIKE 'you%' AND " + TECH
LOCK = threading.RLock()


def fts_query(q):
    words = re.findall(r"[\wऀ-ॿ]+", q.lower())
    return " AND ".join(f'"{w}"*' for w in words[:12])


def scope_of(user):
    """SQL limiting what a user may see."""
    if not user or user["role"] == "admin":
        return "", []
    ents = user.get("scope") or []
    if not ents:
        return "1=0", []
    return f"f.entity IN ({','.join('?' * len(ents))}) AND f.sensitive=0", list(ents)


def _where(q, filters, dups, review, scope, extra=None):
    where, params = [], []
    if extra:
        where.append("(" + extra[0] + ")"); params += extra[1]
    under = (filters or {}).get("under")
    if under:
        pre = under.rstrip("/") + "/"
        where.append("substr(f.path,1,?)=?"); params += [len(pre), pre]
    if (filters or {}).get("planned"):
        where.append("f.id IN (SELECT file_id FROM plan)")
    for k, v in (filters or {}).items():
        if k in FACETS and v:
            if v == "(none)":
                where.append(f"f.{k} IS NULL")
            else:
                where.append(f"f.{k}=?"); params.append(v)
    if dups:
        where.append("f.hash IN (SELECT hash FROM files WHERE hash IS NOT NULL GROUP BY hash HAVING count(*)>1)")
    if review == "owner":
        where.append(REVIEW_OWNER)
    elif review == "suggested":
        where.append("f.entity IS NULL AND f.suggestions IS NOT NULL AND coalesce(f.entity_conf,'') NOT LIKE 'you%' AND " + TECH)
    elif review == "sensitive":
        where.append("f.sensitive=1")
    elif review == "mine":
        where.append("f.entity_conf LIKE 'you%'")
    if scope[0]:
        where.append(scope[0]); params += scope[1]
    return where, params, fts_query(q or "")


def search(cat, q="", filters=None, limit=50, offset=0, dups=False, review=None, scope=("", []), ids_only=False, extra=None, parsed=None):
    where, params, fq = _where(q, filters, dups, review, scope, extra)
    order = ""
    if parsed is not None:  # plain-language + forgiving search
        where += parsed["where"]; params += parsed["params"]; fq = parsed["fts"]
        order = ("(" + " + ".join(parsed["boost"]) + "), ") if parsed["boost"] else ""  # most matched parts first
        oparams = parsed["bparams"]
    else:
        oparams = []
    cols = "f.id" if ids_only else ",".join("f." + c for c in FIELDS.split(","))
    w_and = ("AND " + " AND ".join(where)) if where else ""
    if fq:
        snip = "" if ids_only else ", snippet(fts,3,'[[',']]','…',18) AS snip"
        sql = f"SELECT {cols}{snip} FROM fts JOIN files f ON f.id=fts.rowid WHERE fts MATCH ? {w_and} ORDER BY {order}rank LIMIT ? OFFSET ?"
        args, csql, cargs = [fq] + params + oparams + [limit, offset], f"SELECT count(*) FROM fts JOIN files f ON f.id=fts.rowid WHERE fts MATCH ? {w_and}", [fq] + params
    else:
        w = ("WHERE " + " AND ".join(where)) if where else ""
        snip = "" if ids_only else ", f.snippet AS snip"
        sql = f"SELECT {cols}{snip} FROM files f {w} ORDER BY {order}{'f.hash,' if dups else ''} f.date DESC LIMIT ? OFFSET ?"
        args, csql, cargs = params + oparams + [limit, offset], f"SELECT count(*) FROM files f {w}", params
    try:
        if ids_only:
            return [r[0] for r in cat.db.execute(sql, args)]
        rows = [dict(r) for r in cat.db.execute(sql, args)]
        total = cat.db.execute(csql, cargs).fetchone()[0]
    except Exception as e:
        return [] if ids_only else {"results": [], "total": 0, "error": str(e)}
    for r in rows:
        for k in ("tags", "suggestions"):
            if r.get(k):
                try:
                    r[k] = json.loads(r[k])
                except ValueError:
                    pass
    return {"results": rows, "total": total}


def facets(cat, scope):
    w, p = (("WHERE " + scope[0]) if scope[0] else ""), scope[1]
    a = (" AND " + scope[0]) if scope[0] else ""
    out = {}
    for f in FACETS:
        out[f] = [[r[0] or "(none)", r[1]] for r in cat.db.execute(f"SELECT {f}, count(*) FROM files f {w} GROUP BY {f} ORDER BY 2 DESC LIMIT 80", p)]
    out["total"] = list(cat.db.execute(f"SELECT count(*), sum(size) FROM files f {w}", p).fetchone())
    out["last_scan"] = cat.get_meta("last_scan")
    one = lambda cond: cat.db.execute(f"SELECT count(*) FROM files f WHERE {cond}{a}", p).fetchone()[0]
    out["review"] = {"owner": one(REVIEW_OWNER),
                     "suggested": one("f.entity IS NULL AND f.suggestions IS NOT NULL AND coalesce(f.entity_conf,'') NOT LIKE 'you%' AND " + TECH),
                     "dups": one("f.hash IN (SELECT hash FROM files WHERE hash IS NOT NULL GROUP BY hash HAVING count(*)>1)"),
                     "sensitive": one("f.sensitive=1"), "mine": one("f.entity_conf LIKE 'you%'")}
    return out


def detail(cat, fid, scope):
    a = (" AND " + scope[0]) if scope[0] else ""
    r = cat.db.execute(f"SELECT * FROM files f WHERE f.id=?{a}", [fid] + scope[1]).fetchone()
    if not r:
        return {}
    d = dict(r)
    for k in ("tags", "suggestions", "extra"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    body = cat.db.execute("SELECT body FROM fts WHERE rowid=?", (fid,)).fetchone()
    d["text"] = (body[0] if body else "")[:6000]
    d["archive"] = [list(x) for x in cat.db.execute("SELECT name,size FROM archive_items WHERE file_id=? LIMIT 300", (fid,))]
    d["copies"] = [x[0] for x in cat.db.execute(f"SELECT f.path FROM files f WHERE f.hash=? AND f.id!=?{a}", [d["hash"], fid] + scope[1])] if d.get("hash") else []
    d["decision"] = cat.decision_for(d["path"], d.get("hash"))
    if d.get("kind") in ("Audio", "Video"):
        d["transcript"] = TR.get(cat, fid)
        if d["transcript"]:
            d["text"] = d["text"].split("\n[transcript]\n")[0]
    return d




_DICT = None


def _dictionary():
    """Ordinary English words (system word list), so a one-word 'name' like "Information" is not shown as a holder."""
    global _DICT
    if _DICT is None:
        _DICT = set()
        for p in ("/usr/share/dict/words", "/usr/share/dict/american-english"):
            if os.path.exists(p):
                with open(p, errors="ignore") as f:
                    _DICT = {w.strip().lower() for w in f}
                break
    return _DICT


def triage(cfg, cat, where="tosort", limit=8, scope=("", []), under=None):
    """Files waiting for an owner, most valuable first."""
    from .plugins.classify import holder_names
    from .sorter import group_label
    cond, params = ["f.unit='file'", "f.entity IS NULL", "coalesce(f.entity_conf,'') NOT LIKE 'you%'", "coalesce(f.sensitive,0)=0", TECH,
                    "f.id NOT IN (SELECT CAST(substr(key,8) AS INTEGER) FROM dismissed WHERE key LIKE 'triage:%' AND (until IS NULL OR until>?))"], [time.time()]
    if under:
        pre = under.rstrip("/") + "/"
        cond.append("substr(f.path,1,?)=?"); params += [len(pre), pre]
    elif where == "tosort":
        pre = cfg.library + "/" + group_label(cfg, "Unsorted") + "/"
        cond.append("substr(f.path,1,?)=?"); params += [len(pre), pre]
    if scope[0]:
        cond.append(scope[0]); params += scope[1]
    from . import doctypes
    important = doctypes.tagged("important")
    imp = ",".join("?" * len(important)) or "NULL"
    prio = (f"CASE WHEN f.doc_type IN ({imp}) AND f.doc_conf IN ('high','medium') AND f.kind IN ('PDF','Document','Spreadsheet','Presentation','Photo') "
            "THEN 0 WHEN f.suggestions IS NOT NULL THEN 1 "
            "WHEN f.kind IN ('PDF','Document','Spreadsheet','Presentation','Photo') THEN 2 WHEN f.kind IN ('Archive','Video','Audio','Email') THEN 3 ELSE 4 END")
    w = " AND ".join(cond)
    rows = cat.db.execute(f"SELECT f.id,f.path,f.name,f.kind,f.ext,f.size,f.date,f.doc_type,f.doc_conf,f.topic,f.suggestions,f.cloud_only,f.snippet,"
                          f"{prio} AS bucket FROM files f WHERE {w} ORDER BY bucket, f.date DESC LIMIT ?", important + params + [limit]).fetchall()
    counts = dict(cat.db.execute(f"SELECT {prio} AS b, count(*) FROM files f WHERE {w} GROUP BY b", important + params).fetchall())
    out = []
    for r in rows:
        d = dict(r)
        d["suggestions"] = json.loads(d["suggestions"]) if d["suggestions"] else []
        body = (cat.db.execute("SELECT body FROM fts WHERE rowid=?", (d["id"],)).fetchone() or [""])[0] or ""
        body = body.split("\n[transcript]\n")[0]
        ents = cfg.get("entities", [])
        from .plugins.classify import entity_in_name
        d["holder"] = [h for h in holder_names(body, d["doc_type"])
                       if len(h.split()) >= 2 or any(entity_in_name(e, h) for e in ents) or (h.lower() not in _dictionary() and h.lower().rstrip("s") not in _dictionary())]
        d["holder_known"] = [e["name"] for e in ents if any(entity_in_name(e, h) for h in d["holder"])]
        d["excerpt"] = body[:1500]
        d["preview"] = d["kind"] in ("Photo", "PDF") and not d["cloud_only"]
        out.append(d)
    names = ["important documents", "owner suggested", "documents & photos", "archives & media", "code, installers & other"]
    return {"items": out, "remaining": sum(counts.values()), "buckets": [[names[b], counts.get(b, 0)] for b in range(5)], "where": where}


def options(cfg):
    return {"entities": [{"name": e["name"], "type": e["type"]} for e in cfg.get("entities", [])],
            "topics": [t["name"] for t in cfg.get("topics", [])],
            "doc_types": [r["name"] for r in cfg.get("doc_types", [])]}


def label_fields(cfg, want):
    """Turn the page's request {entity?, topic?, doc_type?} into catalogue columns. '' clears a value."""
    out, ents, tops = {}, {e["name"]: e for e in cfg.get("entities", [])}, {t["name"]: t for t in cfg.get("topics", [])}
    if "entity" in want:
        v = want["entity"]
        if v and v not in ents:
            raise ValueError("unknown owner")
        out.update(entity=v or None, entity_type=ents[v]["type"] if v else None, entity_conf="you" if v else "you: no owner",
                   entity_why="set by you", suggestions=None)
    if "topic" in want:
        v = want["topic"]
        if v and v not in tops:
            raise ValueError("unknown topic")
        out.update(topic=v or None, lifecycle=tops[v].get("lifecycle") if v else None)
    if "doc_type" in want:
        v = want["doc_type"]
        if v and v not in {r["name"] for r in cfg.get("doc_types", [])}:
            raise ValueError("unknown document type")
        out.update(doc_type=v or None, doc_conf="you" if v else None)
    if not out:
        raise ValueError("nothing to change")
    return out


def describe(want, n):
    parts = [f"{ {'entity': 'owner', 'topic': 'topic', 'doc_type': 'document type'}[k] } → {v or 'none'}" for k, v in want.items()]
    return f"Set {', '.join(parts)} on {n:,} file{'s' if n != 1 else ''}"


def serve(cfg, cat, port=None, lan=False, browser=True):
    state = {"cfg": cfg, "job": None}
    ui = cfg.get("ui", {})
    auth = Auth(cat, idle_hours=ui.get("idle_hours", 4))
    setup_token = secrets.token_urlsafe(24)
    devices = LAN.Devices(cat)
    lanst = {"srv": None, "servers": [], "url": None, "fingerprint": None, "hosts": set(), "error": None, "ip": None, "vpn_ip": None,
             "vpn_url": None, "networks": []}
    hub = HB.Hub(cat)
    pages = {n: os.path.join(ROOT, "engine", n) for n in ("search.html", "settings.html", "login.html", "insights.html", "analytics.html", "sorter.html", "triage.html", "home.html", "person.html", "browse.html", "overview.html", "projects.html", "cleanup.html", "computers.html", "welcome.html")}

    class H(BaseHTTPRequestHandler):
        REMOTE = False  # True for the home Wi-Fi (HTTPS) server
        server_version = "UniversalOrganiser"
        sys_version = ""

        def log_message(self, *a):
            pass

        # ---- helpers ----
        def _send(self, code, body=b"", ctype="application/json", headers=()):
            b = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if ctype == "text/html":
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                 "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'")
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _json(self, obj, code=200, headers=()):
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str), headers=headers)

        def _err(self, msg, code=400):
            self._json({"error": msg}, code)

        def _local(self):
            if self.REMOTE:  # phones/tablets: private address, our own host name, same-origin
                host = self.headers.get("Host") or ""
                if not LAN.client_allowed(self.client_address[0], lanst["networks"]) or host not in lanst["hosts"]:
                    return False
                o = self.headers.get("Origin")
                return not o or urllib.parse.urlparse(o).netloc in lanst["hosts"]
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in ("127.0.0.1", "localhost"):
                return False
            o = self.headers.get("Origin")
            if o and urllib.parse.urlparse(o).hostname not in ("127.0.0.1", "localhost"):
                return False
            return True

        def _sid(self, name="fe_s"):
            c = SimpleCookie(self.headers.get("Cookie") or "")
            return c[name].value if name in c else None

        def _user(self):
            u = auth.session(self._sid())
            if u and self.REMOTE and not devices.approved(self._sid("fe_d"), u["username"]):
                return None  # a removed or unapproved device is signed out at once
            return u

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 4_000_000:
                raise ValueError("too large")
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _lang(self):
            """This device's choice (cookie), else the computer's default (Settings), else the browser's language."""
            langs = I18N.languages()
            c = SimpleCookie(self.headers.get("Cookie") or "")
            if "uo_lang" in c and c["uo_lang"].value in langs:
                return c["uo_lang"].value
            pref = (state["cfg"].get("ui") or {}).get("language") or "auto"
            if pref in langs:
                return pref
            for part in (self.headers.get("Accept-Language") or "").split(","):
                code = part.split(";")[0].strip().lower().split("-")[0]
                if code in langs:
                    return code
            return "en"

        def _page(self, name):
            with open(pages[name], encoding="utf-8") as f:
                html = f.read()
            with open(os.path.join(ROOT, "engine", "a11y.js"), encoding="utf-8") as f:  # accessibility for every page
                js = "<script>\n" + f.read() + "\n</script>\n"
            i = html.rfind("</body>")
            html = html[:i] + js + html[i:] if i >= 0 else html + js
            head = I18N.head(self._lang())  # language: before the page's own text appears
            j = html.find("<head>")
            html = html[:j + 6] + head + html[j + 6:] if j >= 0 else head + html
            self._send(200, html, "text/html")

        def _redirect(self, to):
            self.send_response(303); self.send_header("Location", to); self.send_header("Content-Length", "0"); self.end_headers()

        # ---- routing ----
        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def _route(self, method):
            if not self._local():
                return self._send(403, "forbidden", "text/plain")
            u = urllib.parse.urlparse(self.path)
            qs = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            path = u.path
            if method == "GET" and path == "/api/thumb":
                return self._thumb(qs)
            with LOCK:
                try:
                    self._handle(method, path, qs)
                except (AuthError, ValueError, KeyError) as e:
                    self._err(str(e))
                except Exception as e:  # never leak a traceback to the page
                    self._err(f"internal error: {type(e).__name__}", 500)

        def _thumb(self, qs):
            """Photo/PDF preview. Permission check under the lock; making the preview (sips) outside it, so pages stay responsive."""
            with LOCK:
                user = self._user()
                if not user:
                    return self._send(401, "sign in", "text/plain")
                scope = scope_of(user)
                w = (" AND " + scope[0]) if scope[0] else ""
                try:
                    fid = int(qs.get("id", 0))
                except ValueError:
                    return self._send(400, "bad id", "text/plain")
                r = cat.db.execute(f"SELECT f.path, f.mtime FROM files f WHERE f.id=? AND f.kind IN ('Photo','PDF') AND coalesce(f.cloud_only,0)=0 "
                                   f"AND coalesce(f.sensitive,0)=0{w}", [fid] + scope[1]).fetchone()
            if not r or not os.path.exists(r[0]):
                return self._send(404, "no preview", "text/plain")
            tdir = os.path.join(cat.folder, "thumbs"); os.makedirs(tdir, exist_ok=True)
            out = os.path.join(tdir, f"{fid}-{int(r[1] or 0)}.jpg")
            if not os.path.exists(out):
                tmp = out + f".{threading.get_ident()}.tmp.jpg"
                from . import platforms
                try:
                    if platforms.thumbnail(r[0], tmp):
                        os.replace(tmp, out)
                except subprocess.TimeoutExpired:
                    pass
            if not os.path.exists(out):
                # no converter on this OS: small JPEG/PNG originals are sent as they are
                ext = os.path.splitext(r[0])[1].lower()
                if ext in (".jpg", ".jpeg", ".png") and os.path.getsize(r[0]) <= 3_000_000:
                    with open(r[0], "rb") as fh:
                        return self._send(200, fh.read(), "image/png" if ext == ".png" else "image/jpeg")
                return self._send(404, "no preview", "text/plain")
            with open(out, "rb") as fh:
                return self._send(200, fh.read(), "image/jpeg")

        def _handle(self, method, path, qs):
            user = self._user()
            is_api = path.startswith("/api/")
            if is_api and self.headers.get("X-FE") != "1" and not (method == "GET" and path == "/api/thumb"):
                return self._send(403, "forbidden", "text/plain")
            if path.startswith("/api/agent/"):
                return self._agent(method, path)
            if method == "GET" and path == "/login":
                return self._page("login.html")
            if method == "GET" and path == "/device-setup" and lanst["fingerprint"]:
                return self._send(200, LAN.SETUP_PAGE.replace("__FP__", lanst["fingerprint"]), "text/html")
            if method == "GET" and path == "/favicon.ico":  # no icon; say so without an error in the browser console
                return self._send(204, b"", "image/x-icon")
            if method == "GET" and path == "/ca.crt" and lanst["fingerprint"]:
                with open(os.path.join(cat.folder, "tls", "ca.crt"), "rb") as fh:
                    return self._send(200, fh.read(), "application/x-x509-ca-cert",
                                      headers=[("Content-Disposition", 'attachment; filename="Universal-Organiser-home-CA.crt"')])
            if path == "/api/login-state" and method == "GET":
                return self._json({"has_users": auth.has_users(), "remote": self.REMOTE,
                                   "setup_ok": not self.REMOTE and qs.get("t") == setup_token and not auth.has_users(),
                                   "profile": state["cfg"].get("profile")})
            if path == "/api/setup" and method == "POST":
                b = self._body()
                if self.REMOTE or auth.has_users() or b.get("t") != setup_token:
                    return self._err("Setup is only allowed once, from the link printed by 'uo serve'.", 403)
                if b.get("password") != b.get("password2"):
                    return self._err("The two passwords differ.")
                auth.add(b.get("username"), b.get("display"), "admin", [], b.get("password"))
                sid = auth.login(b.get("username"), b.get("password"))
                return self._json({"ok": True}, headers=[("Set-Cookie", self._cookie(sid))])
            if path == "/api/login" and method == "POST":
                b = self._body()
                sid = auth.login(b.get("username"), b.get("password"))
                if self.REMOTE:  # a phone/tablet: the device itself must be approved on the computer
                    u = auth.session(sid)
                    d = devices.request(self._sid("fe_d"), u["username"], LAN.label_from_agent(self.headers.get("User-Agent")), self.client_address[0])
                    dev_cookie = ("Set-Cookie", f"fe_d={d['id']}; Path=/; Max-Age=31536000; HttpOnly; Secure; SameSite=Strict")
                    if d["status"] != "approved":
                        auth.logout(sid)
                        if d["status"] == "revoked":
                            return self._json({"error": "This device was removed on the computer."}, 403, headers=[dev_cookie])
                        return self._json({"pending": True, "code": d["code"], "error": "Approve this device on the computer first."}, 403,
                                          headers=[dev_cookie])
                    return self._json({"ok": True}, headers=[("Set-Cookie", self._cookie(sid)), dev_cookie])
                return self._json({"ok": True}, headers=[("Set-Cookie", self._cookie(sid))])
            if not user:
                return self._err("Please sign in.", 401) if is_api else self._redirect("/login")
            admin = user["role"] == "admin"
            scope = scope_of(user)
            cfg = state["cfg"]
            if method == "GET":
                if path == "/":
                    return self._page("search.html")
                if path == "/settings":
                    return self._page("settings.html") if admin else self._redirect("/")
                if path == "/api/me":
                    return self._json({"user": user["username"], "display": user["display"], "role": user["role"],
                                       "scope": user["scope"], "options": options(cfg), "profile": cfg.get("profile")})
                if path == "/api/facets":
                    return self._json(facets(cat, scope))
                if path == "/api/search":
                    ex = I.rec_where(cfg, cat, qs["rec"]) if qs.get("rec") else None
                    if qs.get("smart"):
                        sf = SF.get(cat, int(qs["smart"]))
                        ex2 = SF.where(cfg, sf) if sf else ("0", [])
                        ex = (ex2[0] + (" AND (" + ex[0] + ")" if ex else ""), ex2[1] + (ex[1] if ex else []))
                    pq = None
                    if qs.get("q") and qs.get("literal") != "1":
                        QP.VOCAB.ensure(cat)
                        pq = QP.parse(cfg, cat, qs["q"], ignore=tuple((qs.get("ignore") or "").split(",")))
                    res = search(cat, qs.get("q", ""), {k: qs.get(k) for k in FACETS + ["under", "planned"]}, limit=min(int(qs.get("limit", 50)), 200),
                                 offset=int(qs.get("offset", 0)), dups=qs.get("dups") == "1", review=qs.get("review") or None,
                                 scope=scope, extra=ex, parsed=pq)
                    if pq:
                        res["understood"] = {"chips": pq["chips"], "also": pq["also"]}
                    return self._json(res)
                if path == "/analytics":
                    return self._page("analytics.html")
                if path == "/api/analytics/overview":
                    return self._json(AN.overview(cfg, cat, scope))
                if path == "/api/analytics/tree":
                    if qs.get("raw") == "1":  # folder browser: the real hierarchy, nothing opened automatically
                        return self._json(AN.tree(cfg, cat, qs.get("path", ""), scope, expand=1.01))
                    return self._json(AN.tree(cfg, cat, qs.get("path", ""), scope))
                if path == "/api/analytics/dups":
                    return self._json(AN.duplicates(cfg, cat, scope))
                if path == "/api/analytics/overlap":
                    return self._json(AN.overlap(cfg, cat, scope))
                if path == "/api/analytics/similar":
                    key = (user["username"], cat.db.execute("SELECT count(*), max(rowid) FROM dismissed").fetchone()[:],
                           cat.db.execute("SELECT count(*) FROM photo_features").fetchone()[0] if cat.db.execute(
                               "SELECT 1 FROM sqlite_master WHERE name='photo_features'").fetchone() else 0)
                    c = state.get("simcache")
                    if not c or c[0] != key or time.time() - c[1] > 600:
                        state["simcache"] = c = (key, time.time(), SIM.groups(cfg, cat, scope))
                    return self._json(c[2])
                if path == "/api/plan":
                    return self._json(AN.plan_list(cat)) if admin else self._err("Only an admin can do that.", 403)
                if path == "/home":
                    if admin and not cfg.get("setup_done") and not self.REMOTE:
                        return self._redirect("/welcome")  # a new install: the set-up wizard first
                    return self._page("overview.html")  # the bird's-eye Overview is Home
                if path in ("/actions", "/person", "/browse"):
                    return self._page({"/actions": "home.html"}.get(path, path[1:] + ".html"))
                if path == "/projects":
                    return self._page("projects.html") if admin else self._redirect("/home")
                if path == "/cleanup":
                    return self._page("cleanup.html") if admin else self._redirect("/home")
                if path == "/api/cleanup":
                    if not admin:
                        return self._err("Only an admin can do that.", 403)
                    return self._json({"review": cat.get_meta("cleanup_cache"), "held": CU.held(cat), "job": state.get("cujob")})
                if path == "/api/projects":
                    if not admin:
                        return self._err("Only an admin can do that.", 403)
                    quick = PJ.listing(cfg, cat)
                    cache = cat.get_meta("projects_cache") or {}
                    for d in quick:
                        d.update({k: v for k, v in (cache.get("items", {}).get(d["path"]) or {}).items() if k in ("cloud_files", "cloud_bytes", "git", "changed")})
                    return self._json({"items": quick, "checked_at": cache.get("at"), "job": state.get("pjjob")})
                if path == "/api/ov/node":
                    lens = qs.get("lens", "folder")
                    if lens not in ("folder", "person", "topic", "year", "type"):
                        return self._err("unknown lens")
                    key = json.loads(qs.get("key") or "[]")
                    if not isinstance(key, list) or len(key) > 40:
                        return self._err("bad key")
                    since = (cat.get_meta("visit:" + user["username"]) or {}).get("prev")
                    return self._json(OV.node(cfg, cat, lens, key, scope, since))
                if path == "/api/ov/strip":
                    since = (cat.get_meta("visit:" + user["username"]) or {}).get("prev")
                    return self._json(OV.health_strip(cfg, cat, scope, since))
                if path == "/api/ov/stamp":
                    return self._json(OV.stamp(cat))
                if path == "/api/home":
                    return self._json({"actions": HM.actions(cfg, cat, triage)[:10] if admin else [], "people": HM.people(cfg, cat, scope),
                                       "recent": HM.recent(cat) if admin else [], "smart": SF.listing(cfg, cat, scope),
                                       "totals": list(cat.db.execute(f"SELECT sum({TECH} AND unit='file'), coalesce(sum(size),0), sum(entity IS NOT NULL AND {TECH} AND unit='file') FROM files f "
                                                                     f"WHERE 1=1{(' AND ' + scope[0]) if scope[0] else ''}", scope[1]).fetchone()),
                                       "tags": state.get("tagjob"), "platform": cfg.platform})
                if path == "/api/person":
                    p = HM.person(cfg, cat, qs.get("name", ""), scope)
                    return self._json(p) if p else self._err("No such person (or not yours to see).", 404)
                if path == "/api/tags":
                    if not admin:
                        return self._err("Only an admin can do that.", 403)
                    pl = TG.plan(cfg, cat)
                    return self._json({"files": pl["files"], "tagged": pl["tagged"], "tags": pl["tags"][:40], "job": state.get("tagjob")})
                if path == "/api/smart":
                    def cnt(d):
                        pq = None
                        if d.get("q"):
                            QP.VOCAB.ensure(cat); pq = QP.parse(cfg, cat, d["q"])
                        return search(cat, d.get("q", ""), d.get("filters") or {}, limit=1, scope=scope, parsed=pq)["total"]
                    return self._json(SF.listing(cfg, cat, scope, cnt))
                if path == "/api/deepread/status":
                    return self._json(state.get("drjob"))
                if path == "/api/file":
                    return self._json(detail(cat, int(qs.get("id", 0)), scope))
                if path == "/triage" and not admin:
                    return self._redirect("/")
                if path == "/sorter" and not admin:
                    return self._redirect("/")
                if path == "/insights" and not admin:
                    return self._redirect("/")
                if not admin:
                    return self._err("Only an admin can do that.", 403)
                if path in ("/welcome", "/computers"):
                    return self._page(path[1:] + ".html")
                if path == "/api/welcome":
                    m = SU._load()
                    return self._json({"presets": SU.presets(), "regions": SU.region_list(), "folders": SU.detect_folders(),
                                       "library": m.get("library") or SU.default_library(), "os": SU.platforms.SYSTEM,
                                       "hostname": socket.gethostname().split(".")[0], "setup_done": bool(cfg.get("setup_done")),
                                       "current": {k: m.get(k) for k in ("preset", "region", "role", "roots", "library", "profile")} |
                                                  {"access": (m.get("access") or {}).get("mode"),
                                                   "people": [{"name": e["name"], "type": e["type"]} for e in m.get("entities", [])]},
                                       "entity_types": cfg.get("entity_types"), "checks": self._checks(), "version": SU.VERSION})
                if path == "/api/doctor":
                    return self._json(self._checks())
                if path == "/api/update":
                    from . import updates
                    info, due = updates.cached(cfg)
                    if due and not state.get("update_checking"):
                        state["update_checking"] = True
                        def bg():
                            try:
                                updates.check(state["cfg"])
                            finally:
                                state["update_checking"] = False
                        threading.Thread(target=bg, daemon=True).start()
                    on = bool((cfg.get("updates") or {}).get("check", True))
                    return self._json({"check": on, "info": info, "job": state.get("update_job")})
                if path == "/api/hub":
                    st = state["lan"][0]
                    return self._json({"enabled": bool((cfg.get("hub") or {}).get("enabled")), "machines": hub.list(), "access": access_mode(),
                                       "url": st["url"] and st["url"].replace("/device-setup", ""), "vpn_url": st["vpn_url"] and st["vpn_url"].replace("/device-setup", ""),
                                       "fingerprint": st["fingerprint"], "error": st["error"], "hostname": socket.gethostname().split(".")[0],
                                       "port": ui.get("lan", {}).get("port", 8766), "running": bool(st["servers"])})
                if path == "/api/scan/status":
                    p = os.path.join(SU.DATA, "logs", "scan-status.json")
                    j = state.get("scanjob") or {}
                    return self._json({"job": {k: v for k, v in j.items() if k != "thread"},
                                       "status": json.load(open(p)) if os.path.exists(p) else None})
                if path == "/insights":
                    return self._page("insights.html")
                if path == "/sorter":
                    return self._page("sorter.html")
                if path == "/api/sort/options":
                    lib = cfg.library
                    groups = [os.path.join(lib, g) for g in sorted(os.listdir(lib)) if os.path.isdir(os.path.join(lib, g))] if os.path.isdir(lib) else []
                    return self._json({"default": SO.sources(cfg), "choices": [p for p in groups + cfg.roots if p not in SO.sources(cfg)],
                                       "plan": cat.db.execute("SELECT count(*) FROM plan").fetchone()[0], "library": lib,
                                       "layout": cfg.get("layout_preset"), "local_only": SO.expand(SO._sc(cfg).get("local_only_folder", "")),
                                       "naming": cfg.get("naming_preset") or "original",
                                       "naming_template": (cfg["presets"].get("naming") or {}).get(cfg.get("naming_preset") or "original")})
                if path == "/api/sort/status":
                    j = state.get("sortjob")
                    return self._json(None if not j else {k: v for k, v in j.items() if k != "thread"})
                if path == "/api/languages":
                    if not state.get("langs") or time.time() - state["langs"][0] > 300:
                        state["langs"] = (time.time(), TR.languages())
                    return self._json(state["langs"][1])
                if path == "/api/transcribe/status":
                    j = state.get("trjob")
                    return self._json(j or None)
                if path == "/triage":
                    return self._page("triage.html")
                if path == "/api/triage":
                    return self._json(triage(cfg, cat, qs.get("where", "tosort"), min(int(qs.get("limit", 8)), 30), scope, under=qs.get("under")))
                if path == "/api/sort/runs":
                    return self._json(SO.runs(cat))
                if path == "/api/insights/summary":
                    al = [x for x in I.alerts(cfg, cat) if not x["dismissed"]]
                    return self._json({"alerts": len(al), "important": sum(x["level"] == "important" for x in al),
                                       "proposals": len(I.proposals(cfg, cat)),
                                       "recs": sum(not r["dismissed"] for r in I.recommendations(cfg, cat))})
                if path == "/api/insights/recs":
                    return self._json(I.recommendations(cfg, cat))
                if path == "/api/insights/alerts":
                    return self._json(I.alerts(cfg, cat))
                if path == "/api/insights/proposals":
                    return self._json([{k: v for k, v in x.items() if k != "ids"} for x in I.proposals(cfg, cat)])
                if path == "/api/insights/reports":
                    t = time.localtime()
                    return self._json({"current": f"{t.tm_year}-{t.tm_mon:02d}", "saved": I.saved_reports(cat)})
                if path == "/api/insights/report":
                    m = qs.get("month") or ""
                    if not re.fullmatch(r"\d{4}-\d{2}", m):
                        return self._err("month must be YYYY-MM")
                    saved = cat.get_meta("report:" + m)
                    return self._json(saved if saved and qs.get("fresh") != "1" else I.report(cfg, cat, m))
                if path == "/api/lan":
                    st = state["lan"][0]
                    return self._json({"enabled": bool(st["srv"]), "url": st["url"], "fingerprint": st["fingerprint"], "ip": st["ip"],
                                       "error": st["error"], "remote": self.REMOTE})
                if path == "/api/devices":
                    return self._json(devices.list())
                if path == "/api/changes":
                    return self._json(cat.changes())
                if path == "/api/settings":
                    return self._json(S.current(cfg))
                if path == "/api/settings/versions":
                    return self._json(S.versions())
                if path == "/api/users":
                    return self._json(auth.list())
                if path == "/api/rules/status":
                    j = state["job"]
                    return self._json(None if not j else {k: v for k, v in j.items() if k != "result"} |
                                      ({"result": {k: v for k, v in j["result"].items() if k != "updates"}} if j.get("result") else {}))
                return self._send(404, "not found", "text/plain")
            # POST
            b = self._body()
            if path == "/api/logout":
                auth.logout(self._sid())
                return self._json({"ok": True}, headers=[("Set-Cookie", "fe_s=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")])
            if path == "/api/password":
                auth.logout(auth.login(user["username"], b.get("old")))  # checks the current password
                auth.update(user["username"], pw=b.get("new"))
                return self._json({"ok": True})
            if path in ("/api/cleanup/analyse", "/api/cleanup/hold", "/api/cleanup/restore"):
                if not admin:
                    return self._err("Only an admin can do that.", 403)
                if self.REMOTE:
                    return self._err("Do this on the computer itself.", 403)
                if state.get("cujob", {}).get("phase") == "running":
                    return self._err("Already working; wait for it to finish.")
                if path == "/api/cleanup/restore":
                    return self._json(CU.restore(cfg, cat, str(b.get("path", "")), user["username"]))
                paths = [str(p) for p in (b.get("paths") or [])][:500]
                job = state["cujob"] = {"phase": "running", "what": path.rsplit("/", 1)[-1], "done": 0, "total": len(paths), "step": "", "results": []}
                c, who = cfg, user["username"]

                def cwork():
                    try:
                        from .catalogue import Catalogue
                        cc = Catalogue(cat.folder)
                        if job["what"] == "hold":
                            for i, p in enumerate(paths):
                                job.update(done=i, step=os.path.basename(p))
                                job["results"].append(CU.hold(c, cc, p, who))
                        CU.analyse(c, cc, progress=lambda d, t, s: job.update(step="comparing: " + s))
                        cc.db.close(); job.update(done=len(paths), phase="done")
                    except Exception as e:
                        job.update(phase="failed", error=f"{type(e).__name__}: {e}")
                threading.Thread(target=cwork, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/projects/status":
                if not admin:
                    return self._err("Only an admin can do that.", 403)
                p = str(b.get("path", ""))
                if not cat.db.execute("SELECT 1 FROM files WHERE unit='project' AND path=?", (p,)).fetchone():
                    return self._err("Not a catalogued project.")
                return self._json(PJ.set_status(cfg, cat, p, str(b.get("status", "")), user["username"]))
            if path in ("/api/projects/refresh", "/api/projects/stop", "/api/projects/resume"):
                if not admin:
                    return self._err("Only an admin can do that.", 403)
                if self.REMOTE:
                    return self._err("Do this on the computer itself.", 403)
                if path == "/api/projects/resume":
                    return self._json(PJ.resume_sync(cfg, cat, str(b.get("path", "")), user["username"]))
                if state.get("pjjob", {}).get("phase") == "running":
                    return self._err("Already working on projects; wait for it to finish.")
                known = {r[0] for r in cat.db.execute("SELECT path FROM files WHERE unit='project'")}
                paths = [p for p in (b.get("paths") or []) if p in known]  # only real catalogued projects, never from the page alone
                job = state["pjjob"] = {"phase": "running", "what": path.rsplit("/", 1)[-1], "done": 0, "total": len(paths), "step": "", "results": []}
                c, who = cfg, user["username"]

                def work():
                    try:
                        from .catalogue import Catalogue
                        cc = Catalogue(cat.folder)
                        if job["what"] == "refresh":
                            items = {}
                            for d in PJ.listing(c, cc, deep=True):
                                if d["eligible"]:
                                    items[d["path"]] = {k: d.get(k) for k in ("cloud_files", "cloud_bytes", "git", "changed")}
                                job.update(done=len(items), step=d["name"])
                            cc.set_meta("projects_cache", {"at": time.time(), "items": items})
                        else:
                            for i, p in enumerate(paths):
                                job.update(done=i, step=os.path.basename(p))
                                r = PJ.stop_sync(c, cc, p, who, progress=lambda m: job.update(step=os.path.basename(p) + ": " + m))
                                job["results"].append(r)
                            job.update(done=len(paths))
                        cc.db.close(); job.update(phase="done")
                    except Exception as e:
                        job.update(phase="failed", error=f"{type(e).__name__}: {e}")
                threading.Thread(target=work, daemon=True).start()
                return self._json({"ok": True, "n": len(paths)})
            if path == "/api/ov/visit":
                return self._json({"since": OV.visit(cat, user["username"])})
            if path == "/api/reveal-folder":
                if self.REMOTE:
                    return self._err("“Show in Finder” works only on the computer itself.")
                pth = str(b.get("path") or "")
                if not SO._under(pth, cfg.roots) or not os.path.isdir(pth):
                    return self._err("Not a folder in your scanned places.")
                from . import platforms
                platforms.reveal(pth)
                return self._json({"ok": True})
            if path == "/api/reveal":
                if self.REMOTE:
                    return self._err("“Show in Finder” works only on the computer itself.")
                d = detail(cat, int(b.get("id", 0)), scope)
                if d and os.path.lexists(d["path"]):
                    from . import platforms
                    platforms.reveal(d["path"])
                return self._json({"ok": bool(d)})
            if not admin:
                return self._err("Only an admin can do that.", 403)
            if path in ("/api/welcome/save", "/api/access", "/api/hub/enable", "/api/scan/start", "/api/doctor/fix",
                        "/api/update/install") and self.REMOTE:
                return self._err("Do this on the computer itself.", 403)
            if path == "/api/welcome/save":
                try:
                    SU.init_profile(b, user["username"])
                except ValueError as e:
                    return self._err(str(e))
                state["cfg"] = cfg = Config()
                stop_lan()
                err = start_lan() if access_mode() in ("lan", "remote") else None
                return self._json({"ok": True, "lan_error": err})
            if path == "/api/access":
                mode = b.get("mode")
                if mode not in SU.ACCESS:
                    return self._err("mode must be local, lan or remote")
                SU.patch_profile({"access": {"mode": mode}, "ui": {"lan": {"enabled": mode != "local"}}}, user["username"])
                state["cfg"] = cfg = Config()
                stop_lan()
                err = start_lan() if mode != "local" else None
                return self._json({"ok": not err, "error": err})
            if path == "/api/hub/enable":
                on = bool(b.get("enabled"))
                patch = {"hub": {"enabled": on}, "role": "hub" if on else "standalone"}
                if on and access_mode() == "local":
                    patch.update(access={"mode": "lan"}, ui={"lan": {"enabled": True}})
                SU.patch_profile(patch, user["username"])
                state["cfg"] = cfg = Config()
                err = start_lan() if on else None
                return self._json({"ok": not err, "error": err})
            if path == "/api/hub/code":
                if not (cfg.get("hub") or {}).get("enabled"):
                    return self._err("Turn the hub on first.")
                return self._json(hub.new_code(user["username"]))
            if path == "/api/hub/remove":
                return self._json({"removed": hub.remove(str(b.get("id") or ""))})
            if path == "/api/scan/start":
                j = state.get("scanjob")
                if j and j.get("phase") == "running":
                    return self._err("A scan is already running.")
                job = state["scanjob"] = {"phase": "running", "started": time.time(), "by": user["username"]}

                def scanwork():
                    from .catalogue import Catalogue
                    from .scan import scan
                    from . import insights as I2
                    c2 = Catalogue(cat.folder)  # its own connection: the page keeps answering while it runs
                    try:
                        scan(state["cfg"], c2, log=lambda m: None)
                        I2.auto(state["cfg"], c2, lambda m: None)
                        job.update(phase="done")
                    except Exception as e:
                        job.update(phase="failed", error=f"{type(e).__name__}: {e}")
                    finally:
                        c2.db.close()
                threading.Thread(target=scanwork, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/update/check":
                from . import updates
                return self._json({"info": updates.check(cfg, force=True)})
            if path == "/api/update/install":
                from . import updates
                job = state.get("update_job")
                if job and job["phase"] == "running":
                    return self._err("An update is already running.")
                job = state["update_job"] = {"phase": "running", "log": [], "by": user["username"]}

                def run_update():
                    try:
                        ver = updates.install(cfg, log=lambda m: job["log"].append(str(m)))
                        if not ver:
                            job["phase"] = "current"
                        elif os.name == "nt":
                            job["phase"] = "restart"  # Windows: close this window and start Universal Organiser again
                        else:
                            job["phase"] = "restarting"
                            time.sleep(1.5)  # let the page read this before the server restarts with the new program
                            argv = [a for a in sys.argv if a != "--no-browser"] + ["--no-browser"]
                            os.execv(sys.executable, [sys.executable, "-I"] + argv)
                    except SystemExit as e:
                        job["phase"], job["error"] = "failed", str(e)
                    except Exception as e:
                        job["phase"], job["error"] = "failed", f"{type(e).__name__}: {e}"
                threading.Thread(target=run_update, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/doctor/fix":
                c = next((x for x in SU.checks(cfg) if x["id"] == b.get("id")), None)
                if not c or c["status"] == "ok":
                    return self._json({"ok": True})
                if c.get("fn") != "build_helper":  # installers that need your password run in a terminal, never from the page
                    return self._err("Run this in a terminal: " + (" ".join(c["cmd"]) if c.get("cmd") else c["fix"]))
                try:
                    SU.build_helper(lambda m: None)
                except Exception as e:
                    return self._err(str(e))
                return self._json({"ok": True})
            if path == "/api/label":
                want = {k: b["set"][k] for k in ("entity", "topic", "doc_type") if k in (b.get("set") or {})}
                fields = label_fields(cfg, want)
                if b.get("ids") is not None:
                    ids = [int(i) for i in b["ids"]][:50000]
                else:
                    qy = b.get("query") or {}
                    ex = None
                    if qy.get("rec"):
                        ex = I.rec_where(cfg, cat, qy["rec"])
                        if not ex:
                            return self._err("unknown recommendation")
                    ids = search(cat, qy.get("q", ""), {k: qy.get(k) for k in FACETS + ["under", "planned"]}, limit=50000, dups=bool(qy.get("dups")),
                                 review=qy.get("review") or None, ids_only=True, extra=ex)
                summary = describe(want, len(ids))
                if b.get("preview"):
                    return self._json({"n": len(ids), "summary": summary + ". Labels only: nothing is moved or renamed."})
                cid = cat.decide(ids, fields, user["username"], summary)
                return self._json({"ok": True, "change": cid, "summary": summary})
            if path in ("/api/plan/add", "/api/plan/remove"):
                if path == "/api/plan/remove":
                    return self._json({"ok": True, "n": AN.plan_remove(cat, None if b.get("all") else [int(i) for i in b.get("ids", [])])})
                if b.get("ids") is not None:
                    ids = [int(i) for i in b["ids"]][:50000]
                else:
                    qy = b.get("query") or {}
                    ex = I.rec_where(cfg, cat, qy["rec"]) if qy.get("rec") else None
                    ids = search(cat, qy.get("q", ""), {k: qy.get(k) for k in FACETS + ["under", "planned"]}, limit=50000,
                                 dups=bool(qy.get("dups")), review=qy.get("review") or None, ids_only=True, extra=ex)
                ok = AN.plannable(cat, ids)
                act = AN.PLAN_ACTIONS.get(b.get("action"))
                if not act:
                    return self._err("unknown action")
                if b.get("preview"):
                    sz = sum(r[0] or 0 for r in cat.db.execute(f"SELECT size FROM files WHERE id IN ({','.join(map(str, ok))})")) if ok else 0
                    skipped = len(ids) - len(ok)
                    return self._json({"n": len(ok), "size": sz, "summary": f"Add {len(ok):,} file(s) to the plan: {act}."
                                       + (f" {skipped:,} skipped (projects, apps, protected folders are never planned)." if skipped else "")
                                       + " Nothing happens to the files now; the plan runs only when you start the sorter, with its own preview."})
                return self._json({"ok": True, "n": AN.plan_add(cat, ok, b["action"], user["username"])})
            if path == "/api/transcribe":
                if state.get("trjob", {}).get("phase") == "running":
                    return self._err("A transcript is already being made; try again in a moment.")
                lang = b.get("language") or None
                if lang and not re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}", lang):
                    return self._err("bad language")
                rows = TR.candidates(cfg, cat, ids=[int(b.get("id", 0))], force=bool(lang))
                if not rows:
                    return self._err("Nothing to transcribe (already done, iCloud-only, sensitive, or not audio/video).")
                job = state["trjob"] = {"phase": "running", "id": rows[0]["id"], "started": time.time()}
                c = cfg

                def work():
                    try:
                        if lang and lang not in (state.get("langs") or (0, {"installed": []}))[1].get("installed", []):
                            job.update(step=f"downloading {lang} from Apple")
                            res = TR.install_language(c, lang, cat)
                            state.pop("langs", None)
                            if res.get("error"):
                                job.update(phase="failed", error=res["error"]); return
                        job.update(step="transcribing")
                        with LOCK:
                            TR.mark_used(cat, lang or ",".join(c.plugin("transcribe").get("languages", [])))
                        TR.run(c, cat, rows, log=lambda m: None, lock=LOCK, language=lang)
                        job.update(phase="done")
                    except Exception as e:
                        job.update(phase="failed", error=f"{type(e).__name__}: {e}")
                threading.Thread(target=work, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/move":
                moves, why = SO.manual_moves(cfg, cat, b.get("ids"), None, b.get("dest")) if b.get("ids") else ([], None)
                if why:
                    return self._err(why)
                for fo in (b.get("folders") or []) + ([b["folder"]] if b.get("folder") else []):
                    m2, why = SO.manual_moves(cfg, cat, None, fo, b.get("dest"))
                    if why:
                        return self._err(why)
                    moves += [m for m in m2 if m["id"] not in {x["id"] for x in moves}]
                if not moves:
                    return self._err("Already there.")
                if b.get("preview"):
                    return self._json({"n": len(moves), "size": sum(m["size"] for m in moves), "dest": b.get("dest"),
                                       "summary": f"Move {len(moves):,} file(s) to {b.get('dest', '').replace(os.path.expanduser('~'), '~')}. "
                                                  "You can undo it from Sorter → Past runs."})
                res = SO.run(cfg, cat, moves, user["username"])
                return self._json(res)
            if path in ("/api/tags/apply", "/api/tags/remove"):
                if state.get("tagjob", {}).get("phase") == "running":
                    return self._err("Already working on tags.")
                job = state["tagjob"] = {"phase": "running", "done": 0, "total": 0, "what": "apply" if path.endswith("apply") else "remove"}
                c = cfg

                def work():
                    try:
                        from .catalogue import Catalogue
                        cc = Catalogue(cat.folder)  # its own connection; the page stays usable
                        prog = lambda d, t: job.update(done=d, total=t)
                        r = TG.apply(c, cc, progress=prog) if job["what"] == "apply" else TG.remove_all(cc, progress=prog)
                        cc.db.close(); job.update(phase="done", result=r)
                    except Exception as e:
                        job.update(phase="failed", error=str(e))
                threading.Thread(target=work, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/smart/save":
                return self._json({"ok": True, "id": SF.save(cat, b.get("name"), b.get("def"), user["username"])})
            if path == "/api/smart/delete":
                SF.delete(cat, int(b.get("id", 0))); return self._json({"ok": True})
            if path == "/api/deepread":
                if state.get("drjob", {}).get("phase") == "running":
                    return self._err("Already reading a file; try again in a moment.")
                fid = int(b.get("id", 0))
                row = cat.db.execute("SELECT cloud_only, sensitive FROM files WHERE id=?", (fid,)).fetchone()
                if not row or row["sensitive"]:
                    return self._err("This file cannot be read (sensitive or unknown).")
                job = state["drjob"] = {"phase": "running", "id": fid, "step": "downloading from iCloud" if row["cloud_only"] else "reading every page"}
                c = cfg

                def work():
                    try:
                        if row["cloud_only"]:
                            r = DR.download_and_read(c, cat, fid, log=lambda m: None, lock=LOCK)
                        else:
                            r = {"pages": DR.read_all_pages(c, cat, DR.candidates(c, cat, [fid]), log=lambda m: None, lock=LOCK)}
                        job.update(phase="done", result=r)
                    except Exception as e:
                        job.update(phase="failed", error=str(e))
                threading.Thread(target=work, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/sort/plan":
                extra = [x for x in (b.get("sources") or []) if isinstance(x, str)]
                bad = [x for x in extra if not SO._under(x, cfg.roots) or SO._under(x, cfg.protect)]
                if bad:
                    return self._err("Not allowed as a source: " + ", ".join(bad))
                p = SO.build_plan(cfg, cat, extra_sources=extra, include_plan=b.get("include_plan", True),
                                  tidy=bool(b.get("tidy")), archive_old=bool(b.get("archive_old")), rename=bool(b.get("rename")))
                state["sortplan"] = p
                light = [{k: m.get(k) for k in ("id", "src", "dst", "dest_dir", "action", "why", "size", "needs_ok", "owner", "topic", "kind", "conf", "rename")}
                         for m in p["moves"][:20000]]
                return self._json({**{k: v for k, v in p.items() if k != "moves"}, "moves": light, "total_moves": len(p["moves"])})
            if path == "/api/sort/run":
                p = state.get("sortplan")
                if not p:
                    return self._err("Build the plan first.")
                if state.get("sortjob", {}).get("phase") == "running":
                    return self._err("A sort is already running.")
                if time.time() - p["built_at"] > 1800:
                    return self._err("The plan is older than 30 minutes; build it again.")
                want = {int(i) for i in b.get("ids", [])}
                moves = [m for m in p["moves"] if m["id"] in want]   # paths come from the server's plan, never from the page
                if not moves:
                    return self._err("Nothing selected.")
                job = state["sortjob"] = {"phase": "running", "done": 0, "total": len(moves), "started": time.time()}
                state["sortplan"] = None
                c, who = cfg, user["username"]

                def work():
                    try:
                        res = SO.run(c, cat, moves, who, lambda d, t: job.update(done=d, total=t), lock=LOCK)
                        job.update(phase="done", result=res)
                    except Exception as e:
                        job.update(phase="failed", error=f"{type(e).__name__}: {e}")
                threading.Thread(target=work, daemon=True).start()
                return self._json({"ok": True, "n": len(moves)})
            if path == "/api/sort/undo":
                return self._json(SO.undo(cfg, cat, int(b.get("run", 0)), user["username"]))
            if path == "/api/lan":
                if self.REMOTE:
                    return self._err("Switch Wi-Fi access on or off on the computer itself.", 403)
                st, start, stop, save, _ = state["lan"]
                if b.get("enabled"):
                    err = start()
                    if err:
                        return self._err(err)
                else:
                    stop()
                save(bool(b.get("enabled")), user["username"])
                return self._json({"ok": True, "url": st["url"], "fingerprint": st["fingerprint"]})
            if path == "/api/devices/set":
                if b.get("status") not in ("approved", "revoked", "removed"):
                    return self._err("bad status")
                if self.REMOTE and b.get("status") == "approved":
                    return self._err("Approve devices on the computer itself.", 403)
                devices.set(str(b.get("id", "")), b["status"])
                return self._json({"ok": True})
            if path == "/api/insights/dismiss":
                k = str(b.get("key") or "")[:400]
                if not k:
                    return self._err("no key")
                I.dismiss(cat, k, user["username"], int(b["days"]) if b.get("days") else None)
                return self._json({"ok": True})
            if path == "/api/insights/undismiss":
                I.undismiss(cat, str(b.get("key") or ""))
                return self._json({"ok": True})
            if path == "/api/insights/proposal":
                pr = next((x for x in I.proposals(cfg, cat) if x["key"] == b.get("key")), None)
                if not pr:
                    return self._err("This proposal no longer applies (already done or data changed).")
                if pr["kind"] == "label":
                    want = {"entity": pr["owner"]}
                    summary = describe(want, pr["n"]) + " (learned from folder)"
                    if b.get("preview"):
                        return self._json({"n": pr["n"], "summary": summary + ". Labels only: nothing is moved."})
                    cid = cat.decide(pr["ids"], label_fields(cfg, want), user["username"], summary)
                    return self._json({"ok": True, "change": cid, "summary": summary})
                vals = S.current(cfg)["values"]
                word = "\\b" + re.escape(pr["word"]) + "\\b"
                if pr["field"] == "entity":
                    tgt = next(e for e in vals["entities"] if e["name"] == pr["value"]); tgt.setdefault("aliases", []).append(word)
                    what = f"name word “{pr['word']}” for owner {pr['value']}"
                else:
                    tgt = next(t for t in vals["topics"] if t["name"] == pr["value"]); tgt.setdefault("keywords", []).append(word)
                    what = f"keyword “{pr['word']}” for topic {pr['value']}"
                if b.get("preview"):
                    return self._json({"n": pr["n"], "summary": f"Add {what} to your settings (kept as a new version). "
                                                                   f"Then you see which files the rule would label before anything is applied."})
                errs = S.validate(vals, cfg)
                if errs:
                    return self._json({"errors": errs}, 400)
                S.save(vals, user["username"])
                state["cfg"] = Config()
                return self._json({"ok": True, "next": "rules", "summary": f"Added {what}"})
            if path == "/api/undo":
                n = cat.undo(int(b.get("id", 0)), user["username"])
                return self._json({"ok": True, "n": n})
            if path == "/api/settings/preview":
                errs = S.validate(b, cfg)
                return self._json({"errors": errs, "changes": [] if errs else S.diff(b, cfg)})
            if path == "/api/settings/save":
                errs = S.validate(b, cfg)
                if errs:
                    return self._json({"errors": errs}, 400)
                kept = S.save(b, user["username"])
                state["cfg"] = Config()
                return self._json({"ok": True, "kept": kept})
            if path == "/api/settings/restore":
                kept = S.restore(b.get("name"), user["username"])
                state["cfg"] = Config()
                return self._json({"ok": True, "kept": kept})
            if path == "/api/rules/start":
                if state["job"] and state["job"].get("phase") == "running":
                    return self._err("Already running.")
                job = state["job"] = {"phase": "running", "done": 0, "total": 0, "started": time.time()}
                c = state["cfg"]

                def work():
                    try:
                        from .catalogue import Catalogue
                        reader = Catalogue(cat.folder)  # its own connection: the page stays usable meanwhile
                        res = reclassify.compute(c, reader, lambda d, t: job.update(done=d, total=t))
                        reader.db.close()
                        job.update(phase="ready", result=res)
                    except Exception as e:
                        job.update(phase="failed", error=f"{type(e).__name__}: {e}")

                threading.Thread(target=work, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/rules/apply":
                j = state["job"]
                if not j or j.get("phase") != "ready":
                    return self._err("Preview the rules first.")
                cid = reclassify.apply(cat, j["result"], user["username"])
                state["job"] = {"phase": "applied", "change": cid}
                return self._json({"ok": True, "change": cid})
            if path == "/api/users/add":
                auth.add(b.get("username"), b.get("display"), b.get("role", "member"), b.get("scope", []), b.get("password"))
                return self._json({"ok": True})
            if path == "/api/users/update":
                auth.update(b.get("username"), display=b.get("display"), role=b.get("role"), scope=b.get("scope"), pw=b.get("password") or None)
                return self._json({"ok": True})
            if path == "/api/users/remove":
                if b.get("username") == user["username"]:
                    return self._err("You cannot remove your own account while signed in.")
                auth.remove(b.get("username"))
                return self._json({"ok": True})
            return self._send(404, "not found", "text/plain")

        def _checks(self):
            return [{k: v for k, v in c.items() if k != "fn"} | {"fixable": c.get("fn") == "build_helper"} for c in SU.checks(state["cfg"])]

        def _agent(self, method, path):
            """Records from paired computers. Token auth (no cookie); only when this computer is a hub."""
            if not (state["cfg"].get("hub") or {}).get("enabled"):
                return self._err("This computer is not a hub. Turn the hub on in its Computers page.", 403)
            if method != "POST":
                return self._json({"hub": socket.gethostname().split(".")[0], "version": SU.VERSION})
            n = int(self.headers.get("Content-Length") or 0)
            if n > HB.MAX_BODY:
                return self._err("too large", 413)
            b = HB.load_body(self.rfile.read(n) if n else b"", self.headers.get("Content-Encoding"))
            ip = self.client_address[0]
            if path == "/api/agent/pair":
                return self._json(hub.pair(b.get("code"), b.get("name"), b.get("os"), b.get("version"), ip))
            tok = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            m = hub.machine_for(tok, ip)
            if not m:
                return self._err("This computer is not paired (or was removed on the hub).", 401)
            if path == "/api/agent/begin":
                return self._json(hub.begin(m))
            if path == "/api/agent/push":
                return self._json(hub.push(m, float(b.get("sync") or time.time()), b.get("records") or []))
            if path == "/api/agent/end":
                return self._json(hub.end(m, float(b.get("sync") or time.time()), b.get("paths") or []))
            return self._err("unknown", 404)

        def _cookie(self, sid):
            return f"fe_s={sid}; Path=/; HttpOnly; SameSite=Strict" + ("; Secure" if self.REMOTE else "")

    class HR(H):
        REMOTE = True

    class QuietTLSServer(ThreadingHTTPServer):
        def handle_error(self, request, client_address):  # broken or non-HTTPS connections from the network: ignore quietly
            import ssl, sys as _s
            if isinstance(_s.exc_info()[1], (ssl.SSLError, ConnectionError, TimeoutError, OSError)):
                return
            super().handle_error(request, client_address)

    def access_mode():
        c = state["cfg"]
        mode = (c.get("access") or {}).get("mode")
        if not mode:
            mode = "lan" if (c.get("ui", {}).get("lan", {}).get("enabled")) else "local"
        return mode

    def start_lan():
        """Start the HTTPS server for phones, tablets and other computers: on the home network, and on your own VPN
        when away-from-home access is on. Returns an error text, or None."""
        if lanst["servers"]:
            return None
        c = state["cfg"]
        ip = LAN.lan_ip()
        rem = (c.get("access") or {}).get("remote") or {}
        remote_on = access_mode() == "remote"
        vip = LAN.vpn_ip(rem) if remote_on else None
        if remote_on and not vip:
            lanst["error"] = "Away-from-home access is on, but no VPN address was found (install Tailscale or WireGuard, or set access.remote.bind)."
        if not ip and not vip:
            lanst["error"] = "No home network address found (is Wi-Fi on?)"; return lanst["error"]
        lp = ui.get("lan", {}).get("port", 8766)
        names = list(rem.get("names", [])) if remote_on else []
        try:
            certs = LAN.ensure_certs(cat.folder, ip or vip, [vip] if (vip and ip) else [], names)
            ctx = LAN.tls_context(certs)
            started = []
            for addr in [a for a in (ip, vip) if a]:
                s2 = QuietTLSServer((addr, lp), HR)
                s2.socket = ctx.wrap_socket(s2.socket, server_side=True, do_handshake_on_connect=False)
                threading.Thread(target=s2.serve_forever, daemon=True).start()
                started.append(s2)
        except Exception as e:
            for x in locals().get("started", []):
                x.shutdown(); x.server_close()
            lanst["error"] = f"{type(e).__name__}: {e}"; return lanst["error"]
        hosts = set()
        for addr in [a for a in (ip, vip) if a]:
            hosts |= LAN.host_names(addr, lp)
        hosts |= {f"{n}:{lp}" for n in names}
        nets = (rem.get("networks") or LAN.DEFAULT_VPN_NETWORKS) if remote_on else []
        lanst.update(srv=started[0], servers=started, ip=ip, vpn_ip=vip, networks=nets,
                     url=f"https://{ip or vip}:{lp}/device-setup", vpn_url=(f"https://{vip}:{lp}/device-setup" if vip else None),
                     fingerprint=certs["fingerprint"], hosts=hosts, error=lanst["error"] if remote_on and not vip else None)
        return None

    def stop_lan():
        for x in lanst["servers"]:
            x.shutdown(); x.server_close()
        lanst.update(srv=None, servers=[], url=None, vpn_url=None, hosts=set())

    def save_lan(enabled, by):
        mode = access_mode()
        new = ("remote" if mode == "remote" else "lan") if enabled else "local"
        SU.patch_profile({"ui": {"lan": {"enabled": bool(enabled)}}, "access": {"mode": new}}, by)
        state["cfg"] = Config()

    state["lan"] = (lanst, start_lan, stop_lan, save_lan, devices)

    port = port or ui.get("port", 8765)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    except OSError:
        print(f"Port {port} is in use: the page is probably already open at http://127.0.0.1:{port}/")
        return
    try:
        I.auto(cfg, cat)
    except Exception as e:
        print("monthly report skipped:", e)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    if auth.has_users():
        url = base + "/login"
        print("Catalogue page (this computer only):", url)
    else:
        url = f"{base}/login?t={setup_token}"
        print("First run: create the admin account here (this link works once, on this computer only):\n ", url)
    if access_mode() in ("lan", "remote") or lan:
        err = start_lan()
        print("Phones, tablets, other computers: " + (f"{lanst['url']}\n  certificate fingerprint {lanst['fingerprint']}" if not err else "not started: " + err))
        if lanst.get("vpn_url"):
            print("Away from home (your VPN): " + lanst["vpn_url"])
        elif lanst.get("error"):
            print("  note: " + lanst["error"])
    print("Press Ctrl+C to stop.", flush=True)
    if browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_lan()
