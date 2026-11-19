"""Agent side: send this computer's catalogue to a hub, so one search covers every computer at home.

  uo agent pair https://hub-name.local:8766 ABCD-EFGH [--name "Study PC"] [--fingerprint AA:BB:…] [--yes]
  uo agent sync [--full]        send what changed since the last sync (the first sync sends everything)
  uo agent run [--every 60]     scan + sync now and then every N minutes (leave running, or start it at login)
  uo agent status | forget

Files never leave this computer: only the catalogue records (names, sizes, dates, labels and the text the scan read).
Sensitive files (keys, passwords, IDs flagged as sensitive) are sent without any text.
The hub's certificate is pinned at pairing: the fingerprint is shown so you can compare it with the hub's Computers page.
"""
import gzip, hashlib, json, os, platform, socket, ssl, sys, time, urllib.parse, urllib.request

from .config import DATA
from .catalogue import LOCAL_SQL

VERSION = "1.3.0"
DIR = os.path.join(DATA, "agent")
STATE = os.path.join(DIR, "agent.json")
CA = os.path.join(DIR, "hub-ca.crt")
BATCH_BYTES = 2_000_000
MAX_TEXT = 200_000


def _load():
    return json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}


def _save(st):
    os.makedirs(DIR, exist_ok=True)
    try:
        os.chmod(DIR, 0o700)
    except OSError:
        pass
    tmp = STATE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)
    os.replace(tmp, STATE)


def _check_url(url):
    u = urllib.parse.urlparse(url.rstrip("/"))
    if u.scheme == "https" and u.hostname:
        return u
    if u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost"):
        return u  # same computer (tests, or a hub on this machine)
    raise SystemExit("The hub address must start with https:// (for example https://study-mac.local:8766).")


def fingerprint_of(pem):
    der = ssl.PEM_cert_to_DER_cert(pem)
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def _ctx(url):
    if urllib.parse.urlparse(url).scheme == "http":
        return None
    if not os.path.exists(CA):
        raise SystemExit("Not paired with a hub yet: run  uo agent pair <hub address> <code>")
    ctx = ssl.create_default_context(cafile=CA)  # trusts only the hub's own certificate authority
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _call(url, path, body=None, token=None, ctx=None, timeout=120):
    data, headers = None, {"X-FE": "1", "User-Agent": f"UniversalOrganiser-agent/{VERSION}"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
        if len(data) > 64_000:
            data = gzip.compress(data, 6)
            headers["Content-Encoding"] = "gzip"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url.rstrip("/") + path, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error")
        except Exception:
            msg = None
        raise SystemExit(f"The hub said: {msg or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit(f"Could not reach the hub at {url}: {getattr(e, 'reason', e)}")


def _fetch_ca(u):
    """Download the hub's certificate authority over TLS without trusting it yet (it is checked by fingerprint)."""
    raw = ssl.create_default_context()
    raw.check_hostname, raw.verify_mode = False, ssl.CERT_NONE
    req = urllib.request.Request(f"{u.scheme}://{u.netloc}/ca.crt", headers={"User-Agent": f"UniversalOrganiser-agent/{VERSION}"})
    with urllib.request.urlopen(req, context=raw, timeout=30) as r:
        pem = r.read().decode()
    if "BEGIN CERTIFICATE" not in pem:
        raise SystemExit("The hub did not send a certificate. Is “Home Wi-Fi” access switched on at the hub?")
    return pem


def pair(url, code, name=None, fingerprint=None, yes=False, ask=input):
    u = _check_url(url)
    url = f"{u.scheme}://{u.netloc}"
    name = name or socket.gethostname().split(".")[0]
    ctx = None
    if u.scheme == "https":
        pem = _fetch_ca(u)
        fp = fingerprint_of(pem)
        if fingerprint:
            if fp.replace(":", "").upper() != fingerprint.replace(":", "").replace(" ", "").upper():
                raise SystemExit("The hub's certificate fingerprint does not match the one you typed. Nothing was paired.\n"
                                 f"  got: {fp}")
        elif not yes:
            print("Hub certificate fingerprint:\n  " + fp)
            print("Compare it with the hub (Computers page → Add a computer).")
            if ask("Same fingerprint? [y/N] ").strip().lower() not in ("y", "yes"):
                raise SystemExit("Not paired.")
        os.makedirs(DIR, exist_ok=True)
        with open(CA, "w") as f:
            f.write(pem)
        ctx = _ctx(url)
    r = _call(url, "/api/agent/pair", {"code": code, "name": name, "os": platform.system(), "version": VERSION}, ctx=ctx)
    st = {"hub": url, "name": r["name"], "machine": r["machine"], "token": r["token"], "paired": time.time(), "last_sync": None}
    _save(st)
    print(f"Paired as “{r['name']}” with {url}. Run  uo agent sync  to send this computer's catalogue.")
    return st


def _rows(cat, since):
    q = f"SELECT f.*, t.body AS text FROM files f LEFT JOIN fts t ON t.rowid=f.id WHERE {LOCAL_SQL.replace('path', 'f.path')}"
    p = []
    if since:
        q += " AND coalesce(f.scanned_at,0) >= ?"
        p.append(since)
    for r in cat.db.execute(q, p):
        d = dict(r)
        d.pop("id", None)
        if d.get("sensitive"):
            d["text"], d["snippet"] = "", None
        elif d.get("text") and len(d["text"]) > MAX_TEXT:
            d["text"] = d["text"][:MAX_TEXT]
        for k in ("suggestions", "tags", "extra"):
            if isinstance(d.get(k), str) and d[k][:1] in "[{":
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    pass
        yield d


def sync(cfg, cat, full=False, log=print):
    st = _load()
    if not st.get("token"):
        raise SystemExit("Not paired with a hub yet: run  uo agent pair <hub address> <code>")
    url, tok = st["hub"], st["token"]
    ctx = _ctx(url)
    started = time.time()
    since = None if full or not st.get("last_sync") else st["last_sync"] - 5
    s = _call(url, "/api/agent/begin", {}, tok, ctx)["sync"]
    sent, batch, size = 0, [], 0
    for d in _rows(cat, since):
        n = len(json.dumps(d, ensure_ascii=False, default=str))
        if batch and size + n > BATCH_BYTES or len(batch) >= 1500:
            _call(url, "/api/agent/push", {"sync": s, "records": batch}, tok, ctx); sent += len(batch); batch, size = [], 0
            log(f"  sent {sent:,} records")
        batch.append(d); size += n
    if batch:
        _call(url, "/api/agent/push", {"sync": s, "records": batch}, tok, ctx); sent += len(batch)
    paths = [r[0] for r in cat.db.execute(f"SELECT path FROM files WHERE {LOCAL_SQL}")]
    e = _call(url, "/api/agent/end", {"sync": s, "paths": paths}, tok, ctx, timeout=600)
    st["last_sync"] = started
    _save(st)
    gone = f", removed {e['removed']:,} that are gone" if e.get("removed") else ""
    log(f"sync done: {sent:,} new/changed records sent; the hub now holds {e['files']:,} of this computer's files{gone}")
    return {"sent": sent, **e}


def status():
    st = _load()
    if not st.get("token"):
        return "Not paired with a hub."
    ls = time.strftime("%Y-%m-%d %H:%M", time.localtime(st["last_sync"])) if st.get("last_sync") else "never"
    return f"Paired as “{st['name']}” with {st['hub']}; last sync {ls}."


def forget():
    for p in (STATE, CA):
        if os.path.exists(p):
            os.remove(p)
    return "This computer forgot the hub. (Remove it on the hub's Computers page too, to delete its records there.)"


def paired():
    return bool(_load().get("token"))
