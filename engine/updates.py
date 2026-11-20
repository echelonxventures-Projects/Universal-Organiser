"""Update check and update.

Where new versions come from (Settings → Plug-ins & AI → Updates; profile `updates`):
  * GitHub (the default): the newest published release of `updates.repo`. One HTTPS request a day to api.github.com that
    carries only the program name and version. A private repository needs a GitHub token with read access to it
    (`uo update --token`, or Settings → Updates). The token is kept in its own file in the data folder, readable only by
    you, never in the profile, never shown again, and only ever sent to api.github.com.
  * A folder or web address (`updates.feed`): a shared folder, a USB stick or your own web space holding what
    `uo package --feed FOLDER` writes there: latest.json, the program zip and SHA256SUMS. Nothing needs GitHub.
  * Other computers paired with this one (`uo agent pair …`) get the new version from this computer at their next sync,
    over their already-pinned connection: they need neither internet access nor a token.

Update: SHA256SUMS must carry the publisher's signature (SHA256SUMS.sig, checked against the keys built into the program,
see signing.py), the program zip must match it, then the release's own installer runs over this copy: program
files are replaced; your profile, catalogue, logs and keys are kept. A git checkout updates with git pull instead.
Admins see “Version X is ready” on Home and press Update now; with `updates.auto` on, it installs by itself once
nobody has used the page for 30 minutes, and restarts.
"""
import hashlib, json, os, re, shutil, ssl, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, zipfile

from .config import DATA, ROOT
from .setup import VERSION

DEFAULT_REPO = "echelonxventures-Projects/Universal-Organiser"
CACHE = os.path.join(DATA, "logs", "update-check.json")
TOKEN_FILE = os.path.join(DATA, "update-token")
DAY = 86400
GITHUB_API = "api.github.com"
PACKAGE_KEEP = ("engine", "helpers", "profiles/base.json", "profiles/presets", "profiles/regions", "install", "docs",
                "uo", "uo.cmd", "fe", "fe.cmd", "README.md", "LICENSE", "CHANGELOG.md", "SECURITY.md")


def settings(cfg):
    u = (cfg.get("updates") if cfg else None) or {}
    return {"check": bool(u.get("check", True)), "auto": bool(u.get("auto", False)),
            "repo": (u.get("repo") or DEFAULT_REPO).strip().strip("/"), "feed": str(u.get("feed") or "").strip(),
            "allow_unsigned": bool(u.get("allow_unsigned", False))}


def source(cfg):
    s = settings(cfg)
    return ("feed", s["feed"]) if s["feed"] else ("github", s["repo"])


def source_label(cfg):
    kind, where = source(cfg)
    return f"GitHub ({where})" if kind == "github" else where


def parse(v):
    """'v1.10.2' → (1, 10, 2); anything unreadable sorts lowest."""
    m = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?", str(v or "").strip())
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


# ---- the GitHub token (private repositories)
def token():
    t = os.environ.get("UO_UPDATE_TOKEN", "").strip()
    if t:
        return t
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def set_token(cfg, tok):
    """Check the token can read the repository, then keep it (mode 600). Empty: forget it."""
    tok = (tok or "").strip()
    if not tok:
        try:
            os.remove(TOKEN_FILE)
        except FileNotFoundError:
            pass
        _save({})
        return "GitHub token removed."
    if not re.fullmatch(r"[A-Za-z0-9_\-]{20,255}", tok):
        raise ValueError("That does not look like a GitHub token (it starts with github_pat_ or ghp_).")
    repo = settings(cfg)["repo"]
    try:
        with _get(f"https://{GITHUB_API}/repos/{repo}", tok=tok) as r:
            json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ValueError({401: "GitHub does not accept this token (wrong or expired).",
                          404: f"This token cannot see {repo}. Give it read access to that repository (Contents: read)."}
                         .get(e.code, f"GitHub said HTTP {e.code}."))
    except (urllib.error.URLError, OSError) as e:
        raise ValueError(f"Could not reach GitHub ({getattr(e, 'reason', e)}).")
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(tok)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    _save({})  # the next check uses it
    return f"GitHub token saved: it can read {repo}."


# ---- network
BUNDLES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/ca-bundle.pem")


def _ctx():
    """Normal certificate checking. Python from python.org on macOS starts with no root certificates (until its
    “Install Certificates” step), so fall back to the system's own bundle — still full verification, never disabled."""
    ctx = ssl.create_default_context()
    if not ctx.cert_store_stats().get("x509_ca"):
        for b in BUNDLES:
            if os.path.exists(b):
                ctx.load_verify_locations(cafile=b)
                break
    return ctx


class _KeepTokenHome(urllib.request.HTTPRedirectHandler):
    """GitHub sends downloads on to its file storage: the token never goes along to another host."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


def _get(url, timeout=15, tok=None, accept="application/vnd.github+json"):
    headers = {"User-Agent": f"UniversalOrganiser/{VERSION}", "Accept": accept}
    if tok and urllib.parse.urlsplit(url).netloc == GITHUB_API:
        headers["Authorization"] = "Bearer " + tok
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ctx()), _KeepTokenHome)
    return opener.open(urllib.request.Request(url, headers=headers), timeout=timeout)


def _feed_open(feed, name, timeout=300):
    """A file of a folder or web-address update source."""
    if not re.fullmatch(r"[\w.+-]+", name):
        raise ValueError(f"unsafe file name in latest.json: {name!r}")
    if re.match(r"https://", feed, re.I):
        return _get(feed.rstrip("/") + "/" + urllib.parse.quote(name), timeout=timeout, accept="*/*")
    if re.match(r"\w+://", feed):
        raise ValueError("a web address for updates must start with https://")
    return open(os.path.join(os.path.expanduser(feed), name), "rb")


def check_feed(feed):
    """Error text for an update source that cannot be used, else None (Settings checks it before saving)."""
    if not feed:
        return None
    if re.match(r"\w+://", feed) and not re.match(r"https://", feed, re.I):
        return "A web address for updates must start with https://."
    if not re.match(r"https://", feed, re.I) and not os.path.isdir(os.path.expanduser(feed)):
        return f"The folder {feed} does not exist (or is not reachable from this computer)."
    return None


# ---- the check
def _load():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def _key(cfg):
    kind, where = source(cfg)
    return f"{kind}:{where}:{'token' if kind == 'github' and token() else ''}"


def check(cfg, force=False):
    """{current, latest, newer, url, notes, checked, error?}; None when checking is turned off."""
    s = settings(cfg)
    if not s["check"] and not force:
        return None
    c = _load()
    key = _key(cfg)
    if not force and c.get("key") == key and time.time() - c.get("checked", 0) < DAY:
        return _view(c, cfg)
    kind, where = source(cfg)
    c = {"key": key, "kind": kind, "where": where, "checked": time.time()}
    try:
        if kind == "feed":
            with _feed_open(where, "latest.json", timeout=30) as r:
                rel = json.loads(r.read())
            zname = str(rel.get("zip") or "")
            if not re.fullmatch(r"[\w.+-]+\.zip", zname):
                raise ValueError("latest.json names no program zip")
            c.update(latest=str(rel.get("version", "")).lstrip("v"), url=rel.get("url") or where,
                     notes=str(rel.get("notes") or "")[:4000], published=rel.get("published"),
                     assets={zname: {"name": zname}, "SHA256SUMS": {"name": "SHA256SUMS"},
                             "SHA256SUMS.sig": {"name": "SHA256SUMS.sig"}})
        else:
            with _get(f"https://{GITHUB_API}/repos/{where}/releases/latest", tok=token()) as r:
                rel = json.loads(r.read())
            c.update(latest=rel.get("tag_name", "").lstrip("v"), url=rel.get("html_url"), notes=(rel.get("body") or "")[:4000],
                     published=rel.get("published_at"),
                     assets={a["name"]: {"url": a.get("browser_download_url"), "api": a.get("url")} for a in rel.get("assets", [])})
    except urllib.error.HTTPError as e:
        if kind == "github" and e.code == 404:
            c["error"] = ("no published release yet, or the token cannot see this repository" if token() else
                          "no published release yet, or the repository is private (add a GitHub token: Settings → Updates)")
        elif e.code == 401:
            c["error"] = "GitHub does not accept the saved token (wrong or expired): add a new one in Settings → Updates"
        else:
            c["error"] = f"the update source said HTTP {e.code}"
    except FileNotFoundError:
        c["error"] = f"no latest.json in {where} (make one there with: uo package --feed \"{where}\")"
    except (urllib.error.URLError, OSError) as e:
        c["error"] = f"could not reach {'GitHub' if kind == 'github' else where} ({getattr(e, 'reason', e)})"
    except (ValueError, KeyError, TypeError) as e:
        c["error"] = f"the update source sent something unreadable ({e})"
    _save(c)
    return _view(c, cfg)


def cached(cfg):
    """(what the last check found or None, whether a new check is due) — never waits for the network."""
    if not settings(cfg)["check"]:
        return None, False
    c = _load()
    if c.get("key") != _key(cfg):
        return None, True
    return _view(c, cfg), time.time() - c.get("checked", 0) >= DAY


def _view(c, cfg=None):
    latest = c.get("latest")
    return {"current": VERSION, "latest": latest, "newer": bool(latest) and parse(latest) > parse(VERSION),
            "url": c.get("url"), "notes": c.get("notes"), "checked": c.get("checked"), "error": c.get("error"),
            "git": os.path.isdir(os.path.join(ROOT, ".git")), "source": source_label(cfg)}


# ---- download and install
def _download(c, name, dest):
    a = (c.get("assets") or {}).get(name)
    if a is None:
        raise KeyError(name)
    if c.get("kind") == "feed":
        src = _feed_open(c["where"], name)
    elif isinstance(a, dict) and token() and a.get("api"):  # private repository: the asset through the API
        src = _get(a["api"], timeout=300, tok=token(), accept="application/octet-stream")
    else:
        src = _get(a["url"] if isinstance(a, dict) else a, timeout=300, accept="*/*")
    with src as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_sums(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return {ln.split()[1].lstrip("*"): ln.split()[0].lower() for ln in f if len(ln.split()) == 2}


def _signed(c, spath, tmp, allow_unsigned, log):
    """SHA256SUMS, once its signature checks out (or when unsigned updates were explicitly allowed)."""
    from . import signing
    gpath = os.path.join(tmp, "SHA256SUMS.sig")
    try:
        _download(c, "SHA256SUMS.sig", gpath)
    except (KeyError, urllib.error.URLError, OSError, ValueError):
        gpath = None
    if gpath:
        with open(spath, "rb") as f, open(gpath, "rb") as g:
            if signing.verify(f.read(), g.read()):
                log("signature ok (signed by the publisher)")
                return spath
        raise SystemExit("The release's signature is not valid: it was not signed by the publisher. Nothing was changed.")
    if allow_unsigned:
        log("note: this update is not signed (unsigned updates are allowed in the profile)")
        return spath
    raise SystemExit("The release is not signed by the publisher, so it was not installed. Nothing was changed. "
                     "(Your own unsigned update folder: set updates.allow_unsigned = true, or sign it with uo package --sign.)")


def _installer_cmd(src, dest):
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(src, "install", "install.ps1"),
                "-Dir", dest, "-Yes", "-NoStart"]
    return ["sh", os.path.join(src, "install", "install.sh"), "--dir", dest, "--yes", "--no-start", "--no-link"]


def install_zip(zpath, expected, log=print, dest=None):
    """Check a program zip against its SHA-256, unpack it safely and run its own installer over `dest` (this copy)."""
    dest = dest or ROOT
    if not expected or sha256_of(zpath) != expected.lower():
        raise SystemExit("The download does not match the release's checksum. Nothing was changed.")
    log("checksum ok")
    out = tempfile.mkdtemp(prefix="uo-unpack-")
    try:
        with zipfile.ZipFile(zpath) as z:
            for n in z.namelist():  # never write outside the temporary folder
                if n.startswith(("/", "\\")) or ":" in n or ".." in n.replace("\\", "/").split("/"):
                    raise SystemExit("The download contains unsafe paths. Nothing was changed.")
            z.extractall(out)
        src = next((os.path.join(out, d) for d in os.listdir(out) if os.path.isdir(os.path.join(out, d, "install"))), out)
        if not os.path.isdir(os.path.join(src, "install")):
            raise SystemExit("The download has no installer in it. Nothing was changed.")
        log("installing (program files only; your profile, catalogue and logs stay)…")
        r = subprocess.run(_installer_cmd(src, dest), capture_output=True, text=True, timeout=1800)
        log("\n".join(l for l in (r.stdout + r.stderr).splitlines()[-15:]))
        if r.returncode:
            raise SystemExit("The installer stopped with an error (see above). Your data was not touched.")
    finally:
        shutil.rmtree(out, ignore_errors=True)


def install(cfg, log=print):
    """Bring this copy to the newest release. Returns the new version, or raises SystemExit with the reason."""
    if os.path.isdir(os.path.join(ROOT, ".git")):
        r = subprocess.run(["git", "-C", ROOT, "pull", "--ff-only"], capture_output=True, text=True, timeout=300)
        log((r.stdout + r.stderr).strip())
        if r.returncode:
            raise SystemExit("Update failed (see above). Nothing of yours was changed.")
        return "git"
    info = check(cfg, force=True)
    if info.get("error"):
        raise SystemExit(f"Could not check for updates: {info['error']}.")
    if not info["newer"]:
        log(f"Universal Organiser {VERSION} is the newest version.")
        return None
    c = _load()
    ver = info["latest"]
    assets = c.get("assets") or {}
    zname = next((n for n in assets if n.endswith(".zip") and ver in n), None)
    if not zname or "SHA256SUMS" not in assets:
        raise SystemExit(f"Release {ver} has no program zip with checksums; download it from {info['url']} and run its installer.")
    tmp = tempfile.mkdtemp(prefix="uo-update-")
    try:
        zpath, spath = os.path.join(tmp, zname), os.path.join(tmp, "SHA256SUMS")
        log(f"downloading {zname} from {source_label(cfg)}…")
        try:
            _download(c, zname, zpath)
            _download(c, "SHA256SUMS", spath)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise SystemExit(f"The download failed ({getattr(e, 'reason', e)}). Nothing was changed.")
        sums_ok = _signed(c, spath, tmp, settings(cfg)["allow_unsigned"], log)
        install_zip(zpath, read_sums(sums_ok).get(zname), log)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    c["installed"] = ver
    _save(c)
    log(f"Updated to {ver}.")
    return ver


# ---- making packages (offline copies, update folders, and what this computer gives its paired computers)
def build_zip(out):
    """Zip of the program files only (no profile, catalogue, logs or keys)."""
    tmp = out + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for k in PACKAGE_KEEP:
            p = os.path.join(ROOT, k)
            if not os.path.exists(p):
                continue
            files = [p] if os.path.isfile(p) else sorted(os.path.join(dp, f) for dp, dn, fn in os.walk(p) for f in fn
                                                         if "__pycache__" not in dp)
            for f in files:
                rel = os.path.relpath(f, ROOT).replace(os.sep, "/")
                if f.endswith((".pyc", ".new", ".part")) or rel in ("helpers/macos/fehelper", "helpers/macos/fetrash"):
                    continue
                z.write(f, "universal-organiser/" + rel)
    os.replace(tmp, out)
    return out


def own_package():
    """(path, sha256) of this computer's own program as a zip, made once per version (for paired computers)."""
    d = os.path.join(DATA, "exports")
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"universal-organiser-{VERSION}.zip")
    if not os.path.exists(out):
        build_zip(out)
    return out, sha256_of(out)


def write_feed(folder, notes="", sign_key=None):
    """latest.json + the program zip + SHA256SUMS in `folder`: an update source for `updates.feed`."""
    folder = os.path.expanduser(folder)
    os.makedirs(folder, exist_ok=True)
    zname = f"universal-organiser-{VERSION}.zip"
    zpath = build_zip(os.path.join(folder, zname))
    digest = sha256_of(zpath)
    with open(os.path.join(folder, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{digest}  {zname}\n")
    sig = os.path.join(folder, "SHA256SUMS.sig")
    if sign_key:
        from . import signing
        signing.sign_file(os.path.join(folder, "SHA256SUMS"), sign_key)
    elif os.path.exists(sig):
        os.remove(sig)  # an old signature would not match the new checksums
    with open(os.path.join(folder, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"version": VERSION, "zip": zname, "sha256": digest, "notes": notes,
                   "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=1, ensure_ascii=False)
    for old in os.listdir(folder):  # older zips are not needed any more
        if old.startswith("universal-organiser-") and old.endswith(".zip") and old != zname:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
    return zpath, digest


# ---- after an update: start again on the new program
def restart(log=print):
    """Replace this process with the newly installed program (same command line, no new browser window)."""
    argv = [a for a in sys.argv if a != "--no-browser"] + ["--no-browser"]
    cmd = [sys.executable, "-I"] + argv
    if os.name == "nt":  # Windows has no real exec: start the new one (it waits for the port), then leave
        env = dict(os.environ, UO_WAIT_PORT="60")
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        os.makedirs(os.path.join(DATA, "logs"), exist_ok=True)
        logf = open(os.path.join(DATA, "logs", "restart.log"), "a")
        subprocess.Popen(cmd, env=env, creationflags=flags, stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
                         close_fds=True, cwd=ROOT)
        os._exit(0)
    os.execv(sys.executable, cmd)
