"""Home Wi-Fi access for phones and tablets (opt-in, off by default).

- Listens only on this computer's home-network address (never 0.0.0.0) and only answers private addresses.
- HTTPS with a private certificate authority made on this computer (openssl). The phone trusts it once; the page on the
  computer shows its fingerprint so the person can check it is the right one.
- Same accounts and family scopes, plus: each new phone or tablet must be approved on the computer with a 6-digit code.
"""
import os, re, socket, ipaddress, subprocess, shutil, hashlib, secrets, time, json

SCHEMA = """CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, username TEXT, label TEXT, code TEXT, status TEXT,
 created REAL, last_seen REAL, ip TEXT)"""


def lan_ip():
    """Address of this computer on the home network (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))  # TEST-NET address: only picks the route
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    a = ipaddress.ip_address(ip)
    return ip if a.is_private and not a.is_loopback else None


def host_names(ip, port):
    hn = socket.gethostname().split(".")[0]
    return {f"{ip}:{port}", f"{hn}.local:{port}", f"{hn.lower()}.local:{port}"}


DEFAULT_VPN_NETWORKS = ["100.64.0.0/10", "fd7a:115c:a1e0::/48"]  # Tailscale's ranges; WireGuard set-ups usually use private ones


def client_allowed(addr, extra_networks=()):
    """Private home-network addresses, plus the VPN ranges named in the profile when away-from-home access is on."""
    try:
        a = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if a.is_multicast or a.is_unspecified:
        return False
    if a.is_private:
        return True
    for n in extra_networks:
        try:
            if a in ipaddress.ip_network(n, strict=False):
                return True
        except ValueError:
            continue
    return False


def vpn_ip(remote_cfg):
    """This computer's address on your own VPN (never a public address). 'auto' asks Tailscale if it is installed."""
    b = (remote_cfg or {}).get("bind", "auto")
    if b and b != "auto":
        return b
    for exe in (shutil.which("tailscale"), "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if exe and os.path.exists(exe):
            try:
                out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=10).stdout.split()
            except (OSError, subprocess.TimeoutExpired):
                continue
            if out:
                return out[0]
    return None


# ---------------------------------------------------------------- certificates
def _openssl():
    return shutil.which("openssl") or ("/usr/bin/openssl" if os.path.exists("/usr/bin/openssl") else None)


def ensure_certs(store, ip, extra_ips=(), extra_names=()):
    """Private CA (10 years) + server certificate for this address (renewed when the address changes)."""
    tool = _openssl()
    if not tool:
        raise RuntimeError("openssl is needed for Wi-Fi access and was not found on this computer")
    d = os.path.join(store, "tls"); os.makedirs(d, exist_ok=True)
    os.chmod(d, 0o700)
    ca_key, ca_crt = os.path.join(d, "ca.key"), os.path.join(d, "ca.crt")
    key, crt, meta = os.path.join(d, "server.key"), os.path.join(d, "server.crt"), os.path.join(d, "server.json")
    run = lambda *a, **k: subprocess.run([tool, *a], capture_output=True, text=True, timeout=60, check=True, **k)
    if not (os.path.exists(ca_key) and os.path.exists(ca_crt)):
        run("req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", "3650", "-keyout", ca_key, "-out", ca_crt,
            "-subj", "/CN=Universal Organiser home certificate authority", "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    hn = socket.gethostname().split(".")[0]
    want = {"ip": ip, "host": hn}
    if extra_ips or extra_names:
        want.update(extra_ips=sorted(extra_ips), extra_names=sorted(extra_names))
    have = json.load(open(meta)) if os.path.exists(meta) else {}
    if have != want or not os.path.exists(crt):
        csr, ext = os.path.join(d, "server.csr"), os.path.join(d, "server.ext")
        run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", csr, "-subj", f"/CN={ip}")
        with open(ext, "w") as f:
            san = ",".join([f"IP:{ip}"] + [f"IP:{x}" for x in extra_ips] + [f"DNS:{hn}.local"] + [f"DNS:{x}" for x in extra_names])
            f.write(f"subjectAltName={san}\nextendedKeyUsage=serverAuth\nkeyUsage=digitalSignature,keyEncipherment\n"
                    "basicConstraints=CA:FALSE\n")
        run("x509", "-req", "-in", csr, "-CA", ca_crt, "-CAkey", ca_key, "-CAcreateserial", "-days", "397", "-out", crt, "-extfile", ext)
        json.dump(want, open(meta, "w"))
        for p in (csr, ext):
            os.remove(p)
    for p in (ca_key, key):
        os.chmod(p, 0o600)
    return {"cert": crt, "key": key, "ca": ca_crt, "fingerprint": fingerprint(ca_crt)}


def fingerprint(ca_crt):
    import ssl
    der = ssl.PEM_cert_to_DER_cert(open(ca_crt).read())
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def tls_context(certs):
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certs["cert"], certs["key"])
    return ctx


# ---------------------------------------------------------------- devices
class Devices:
    def __init__(self, cat):
        self.cat = cat
        cat.db.execute(SCHEMA); cat.db.commit()

    def get(self, did):
        if not did:
            return None
        r = self.cat.db.execute("SELECT * FROM devices WHERE id=?", (did,)).fetchone()
        return dict(r) if r else None

    def request(self, did, username, label, ip):
        """A sign-in from a phone. Returns the device row (new ones start as 'pending' with a 6-digit code)."""
        d = self.get(did)
        if d and d["username"] != username:
            d = None  # a device belongs to one person; another person on it needs its own approval
        if not d:
            did = secrets.token_urlsafe(24)
            code = f"{secrets.randbelow(10**6):06d}"
            self.cat.db.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?,?)", (did, username, label[:120], code, "pending", time.time(), time.time(), ip))
            self.cat.db.commit()
            d = self.get(did)
        else:
            self.cat.db.execute("UPDATE devices SET last_seen=?, ip=? WHERE id=?", (time.time(), ip, did)); self.cat.db.commit()
        return d

    def approved(self, did, username):
        d = self.get(did)
        return bool(d and d["status"] == "approved" and d["username"] == username)

    def list(self):
        return [dict(r) for r in self.cat.db.execute("SELECT id,username,label,code,status,created,last_seen,ip FROM devices ORDER BY created DESC")]

    def set(self, did, status):
        if status == "removed":
            self.cat.db.execute("DELETE FROM devices WHERE id=?", (did,))
        else:
            self.cat.db.execute("UPDATE devices SET status=? WHERE id=?", (status, did))
        self.cat.db.commit()


def label_from_agent(ua):
    ua = ua or ""
    for k, v in (("iPad", "iPad"), ("iPhone", "iPhone"), ("Android", "Android"), ("Macintosh", "Mac"), ("Windows", "Windows PC"), ("Linux", "Linux")):
        if k in ua:
            b = "Safari" if "Safari" in ua and "Chrome" not in ua else "Chrome" if "Chrome" in ua else "Firefox" if "Firefox" in ua else "browser"
            return f"{v} · {b}"
    return "Unknown device"


SETUP_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Set up this device · Universal Organiser</title><style>
:root{--bg:#f4f5f2;--s:#fff;--i:#1d2320;--m:#5d6862;--l:#dde1dc;--a:#2d6a4f}@media (prefers-color-scheme:dark){:root{--bg:#121614;--s:#1a201d;--i:#e4ebe6;--m:#97a49c;--l:#2b342f;--a:#7cc3a0;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--i);font:15px/1.55 -apple-system,system-ui,sans-serif;padding:20px 16px}
.c{max-width:560px;margin:0 auto;background:var(--s);border:1px solid var(--l);border-radius:12px;padding:20px}
h1{font-size:19px;margin:0 0 8px}h2{font-size:15px;margin:18px 0 6px}ol{padding-left:20px}li{margin:4px 0}code{font:12.5px ui-monospace,Menlo,monospace;overflow-wrap:anywhere}
a.b{display:inline-block;background:var(--a);color:var(--s);padding:10px 14px;border-radius:8px;text-decoration:none;margin:6px 0}.m{color:var(--m);font-size:13px}
</style></head><body><div class="c"><h1>Set up this phone or tablet</h1>
<p class="m">This page comes from the computer at home. Do this once per device.</p>
<h2>1. Check the fingerprint</h2><p>It must match the one shown on the computer (Settings → Accounts → Phones &amp; tablets):</p><p><code>__FP__</code></p>
<h2>2. Install the certificate</h2><a class="b" href="/ca.crt">Download certificate</a>
<ol><li><b>iPhone / iPad:</b> Settings → <i>Profile Downloaded</i> → Install. Then Settings → General → About → Certificate Trust Settings → turn on “Universal Organiser home certificate authority” (older installs: “FileEngine home certificate authority”).</li>
<li><b>Android:</b> Settings → Security → Encryption &amp; credentials → Install a certificate → CA certificate → choose the downloaded file.</li></ol>
<h2>3. Sign in</h2><a class="b" href="/login">Open the Universal Organiser</a><p class="m">The first sign-in from this device shows a 6-digit code. Approve it on the computer, then sign in again.</p>
</div></body></html>"""
