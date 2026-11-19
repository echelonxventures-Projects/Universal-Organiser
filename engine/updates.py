"""Update check and update.

  Check: at most once a day the page asks GitHub for the newest published release of Universal Organiser (one HTTPS
  request to api.github.com; it carries only the program name and version in its User-Agent — nothing about you or your
  files). Admins see “Version X is ready” on Home. Turn it off: Settings → Plug-ins & AI → Check for updates
  (profile: updates.check = false). Other sources: updates.repo = "owner/name" (a fork or your own mirror).

  Update: uo update (or “Update now” on Home) downloads that release's program zip, checks its SHA-256 against the
  release's SHA256SUMS file, and runs the release's own installer over this copy: program files are replaced, your
  profile, catalogue, logs and keys are kept. A git checkout updates with git pull instead.
"""
import hashlib, json, os, re, shutil, ssl, subprocess, sys, tempfile, time, urllib.error, urllib.request, zipfile

from .config import DATA, ROOT
from .setup import VERSION

DEFAULT_REPO = "echelonxventures-Projects/Universal-Organiser"
CACHE = os.path.join(DATA, "logs", "update-check.json")
DAY = 86400


def _settings(cfg):
    u = (cfg.get("updates") if cfg else None) or {}
    return bool(u.get("check", True)), (u.get("repo") or DEFAULT_REPO).strip("/")


def parse(v):
    """'v1.10.2' → (1, 10, 2); anything unreadable sorts lowest."""
    m = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?", str(v or "").strip())
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


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


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": f"UniversalOrganiser/{VERSION}", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout, context=_ctx())


def _load():
    try:
        return json.load(open(CACHE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def check(cfg, force=False):
    """{current, latest, newer, url, notes, checked, error?}; None when checking is turned off."""
    on, repo = _settings(cfg)
    if not on and not force:
        return None
    c = _load()
    if not force and c.get("repo") == repo and time.time() - c.get("checked", 0) < DAY:
        return _view(c)
    c = {"repo": repo, "checked": time.time()}
    try:
        with _get(f"https://api.github.com/repos/{repo}/releases/latest") as r:
            rel = json.loads(r.read())
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        c.update(latest=rel.get("tag_name", "").lstrip("v"), url=rel.get("html_url"), notes=(rel.get("body") or "")[:4000],
                 published=rel.get("published_at"), assets=assets)
    except urllib.error.HTTPError as e:
        c["error"] = ("no published release yet (or the repository is private)" if e.code == 404 else f"GitHub said HTTP {e.code}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        c["error"] = f"could not reach GitHub ({getattr(e, 'reason', e)})"
    _save(c)
    return _view(c)


def cached(cfg):
    """(what the last check found or None, whether a new check is due) — never waits for the network."""
    on, repo = _settings(cfg)
    if not on:
        return None, False
    c = _load()
    if c.get("repo") != repo:
        return None, True
    return _view(c), time.time() - c.get("checked", 0) >= DAY


def _view(c):
    latest = c.get("latest")
    return {"current": VERSION, "latest": latest, "newer": bool(latest) and parse(latest) > parse(VERSION),
            "url": c.get("url"), "notes": c.get("notes"), "checked": c.get("checked"), "error": c.get("error"),
            "git": os.path.isdir(os.path.join(ROOT, ".git"))}


def _installer_cmd(src, dest):
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(src, "install", "install.ps1"),
                "-Dir", dest, "-Yes", "-NoStart"]
    return ["sh", os.path.join(src, "install", "install.sh"), "--dir", dest, "--yes", "--no-start", "--no-link"]


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
        zpath = os.path.join(tmp, zname)
        log(f"downloading {zname}…")
        with _get(assets[zname], timeout=300) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
        with _get(assets["SHA256SUMS"]) as r:
            sums = dict((ln.split()[1].lstrip("*"), ln.split()[0].lower()) for ln in r.read().decode().splitlines() if len(ln.split()) == 2)
        with open(zpath, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        if sums.get(zname) != digest:
            raise SystemExit("The download does not match the release's checksum. Nothing was changed.")
        log("checksum ok")
        out = os.path.join(tmp, "x")
        with zipfile.ZipFile(zpath) as z:
            for n in z.namelist():  # never write outside the temporary folder
                if n.startswith(("/", "\\")) or ".." in n.replace("\\", "/").split("/"):
                    raise SystemExit("The download contains unsafe paths. Nothing was changed.")
            z.extractall(out)
        src = next((os.path.join(out, d) for d in os.listdir(out) if os.path.isdir(os.path.join(out, d, "install"))), out)
        log("installing (program files only; your profile, catalogue and logs stay)…")
        r = subprocess.run(_installer_cmd(src, ROOT), capture_output=True, text=True, timeout=1800)
        log("\n".join(l for l in (r.stdout + r.stderr).splitlines()[-15:]))
        if r.returncode:
            raise SystemExit("The installer stopped with an error (see above). Your data was not touched.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    c["installed"] = ver
    _save(c)
    log(f"Updated to {ver}. Restart the page (uo serve) to use it.")
    return ver
