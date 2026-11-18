"""First-run set-up and the requirements check (`uo doctor`).

Everything a new install needs to know is asked once by the browser wizard (/welcome) or by `uo init`, and written to
your own profile (profiles/machine.json in the data folder). The shipped files are never edited, so an update never
overwrites your choices.
"""
import json, os, re, shutil, socket, subprocess, sys, time

from .config import ROOT, DATA, HOME, TOKENS, _merge, regions
from . import platforms

VERSION = "1.0.1"
PROFILE = os.path.join(DATA, "profiles", "machine.json")
VERSIONS = os.path.join(DATA, "profiles", "versions")
PRESETS = os.path.join(ROOT, "profiles", "presets")
ROLES = ("standalone", "hub", "agent")
ACCESS = ("local", "lan", "remote")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- presets and regions
def presets():
    out = []
    for f in sorted(os.listdir(PRESETS)) if os.path.isdir(PRESETS) else []:
        if f.endswith(".json"):
            p = _read(os.path.join(PRESETS, f))
            out.append({"id": f[:-5], "title": p.get("title", f[:-5]), "about": p.get("about", "")})
    order = ["personal", "family", "small-office", "student", "custom"]
    return sorted(out, key=lambda x: order.index(x["id"]) if x["id"] in order else 99)


def region_list():
    out = [{"id": "none", "title": "International (no country documents)"}]
    for r in regions():
        p = _read(os.path.join(ROOT, "profiles", "regions", r + ".json"))
        out.append({"id": r, "title": p.get("name", r), "about": p.get("_about", "")})
    return out


# ---------------------------------------------------------------- folders on this computer
def tokenise(p):
    """Write a path with {HOME}/{ICLOUD}/… so the profile also works for another user name or computer."""
    p = platforms.norm(p)
    for k in sorted(TOKENS, key=lambda k: -len(TOKENS[k])):
        v = TOKENS[k]
        if k != "HOME" and v and (p == v or p.startswith(v + "/")):
            return "{" + k + "}" + p[len(v):]
    if p == HOME or p.startswith(HOME + "/"):
        return "{HOME}" + p[len(HOME):]
    return p


def _mounts():
    """mount point -> file system type (macOS/Linux)."""
    out = {}
    if platforms.SYSTEM == "linux" and os.path.exists("/proc/self/mounts"):
        for line in open("/proc/self/mounts"):
            parts = line.split()
            if len(parts) > 2:
                out[parts[1].replace("\\040", " ")] = parts[2]
    elif platforms.SYSTEM == "macos":
        try:
            txt = subprocess.run(["/sbin/mount"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            txt = ""
        for line in txt.splitlines():
            m = re.match(r"^(.*) on (.*) \((\w+)", line)
            if m:
                out[m[2]] = m[3]
    return out


NETWORK_FS = {"smbfs", "nfs", "nfs4", "cifs", "afpfs", "webdav", "sshfs", "fuse.sshfs", "davfs"}


def _win_drives():
    import ctypes, string
    out = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i) and letter != "C":
            t = ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\")
            kind = {2: "removable", 3: "disk", 4: "network"}.get(t)
            if kind:
                out.append((f"{letter}:/", kind))
    return out


def detect_folders():
    """Places worth scanning on this computer, with a suggestion for each."""
    H, S = HOME, platforms.SYSTEM
    cand = []

    def add(path, kind, suggest, label=None):
        path = platforms.norm(path)
        if os.path.isdir(path) and path not in [c["real"] for c in cand]:
            cand.append({"path": tokenise(path), "real": path, "kind": kind, "suggested": suggest,
                         "label": label or os.path.basename(path.rstrip("/")) or path})

    for n in ("Desktop", "Documents", "Downloads"):
        add(os.path.join(H, n), "home", True)
    for n in ("Pictures", "Movies", "Videos", "Music"):
        add(os.path.join(H, n), "home", n == "Pictures")
    if S == "linux":
        ud = os.path.join(H, ".config", "user-dirs.dirs")
        if os.path.exists(ud):
            for line in open(ud, encoding="utf-8", errors="replace"):
                m = re.match(r'XDG_(\w+)_DIR="(.+)"', line.strip())
                if m and m[1] not in ("TEMPLATES", "PUBLICSHARE"):
                    add(m[2].replace("$HOME", H), "home", m[1] in ("DESKTOP", "DOCUMENTS", "DOWNLOAD", "PICTURES"))
    if S == "macos":
        add(TOKENS.get("ICLOUD", ""), "cloud", True, "iCloud Drive")
        cs = os.path.join(H, "Library", "CloudStorage")
        if os.path.isdir(cs):
            for n in sorted(os.listdir(cs)):
                add(os.path.join(cs, n), "cloud", True, n.split("-")[0])
    if S == "windows":
        add(TOKENS.get("ONEDRIVE", ""), "cloud", True, "OneDrive")
    for n in ("Dropbox", "Google Drive", "OneDrive", "Nextcloud", "pCloud Drive", "Box"):
        add(os.path.join(H, n), "cloud", True, n)
    mounts = _mounts()
    if S == "macos" and os.path.isdir("/Volumes"):
        for n in sorted(os.listdir("/Volumes")):
            p = "/Volumes/" + n
            if os.path.ismount(p) and os.path.realpath(p) != "/" and not n.startswith((".", "com.apple")):
                fs = mounts.get(p, "")
                add(p, "network" if fs in NETWORK_FS else "removable", False)
    if S == "linux":
        for base in (f"/media/{os.environ.get('USER', '')}", "/mnt", "/run/media/" + os.environ.get("USER", "")):
            if os.path.isdir(base):
                for n in sorted(os.listdir(base)):
                    p = os.path.join(base, n)
                    if os.path.ismount(p):
                        add(p, "network" if mounts.get(p, "") in NETWORK_FS else "removable", False)
    if S == "windows":
        try:
            for p, kind in _win_drives():
                add(p, kind, False, p[:2])
        except Exception:
            pass
    return cand


def default_library():
    return "{HOME}/Documents/Organized"


# ---------------------------------------------------------------- your profile
def has_profile():
    return os.path.exists(PROFILE)


def _load():
    return _read(PROFILE) if os.path.exists(PROFILE) else {}


def _write(m, by):
    os.makedirs(os.path.dirname(PROFILE), exist_ok=True)
    if os.path.exists(PROFILE):
        os.makedirs(VERSIONS, exist_ok=True)
        shutil.copy2(PROFILE, os.path.join(VERSIONS, time.strftime("machine-%Y%m%d-%H%M%S.json")))
    m["_saved"] = {"by": by, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    tmp = PROFILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROFILE)


def patch_profile(patch, by):
    """Merge a few settings into your profile (the old one is kept in versions/)."""
    _write(_merge(_load(), patch), by)


def _clean_people(people):
    out = []
    for p in people or []:
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        e = {"name": name[:80], "type": p.get("type") or "Family"}
        al = [a.strip() for a in (p.get("aliases") or []) if str(a).strip()]
        if al:
            e["aliases"] = al
        out.append(e)
    return out


def build_profile(ans):
    """Answers of the wizard (or `uo init`) -> a machine profile."""
    preset = ans.get("preset") or "personal"
    pf = os.path.join(PRESETS, preset + ".json")
    if not os.path.exists(pf):
        raise ValueError(f"Unknown preset '{preset}'. Choose one of: " + ", ".join(p["id"] for p in presets()))
    pr = _read(pf).get("profile", {})
    region = ans.get("region") or "none"
    if region != "none" and region not in regions():
        raise ValueError(f"Unknown region '{region}'.")
    role = ans.get("role") or "standalone"
    access = ans.get("access") or ("lan" if role in ("hub", "agent") else "local")
    if role not in ROLES or access not in ACCESS:
        raise ValueError("role must be standalone/hub/agent and access local/lan/remote")
    roots = [r if r.startswith("{") else tokenise(os.path.abspath(os.path.expanduser(r))) for r in (ans.get("roots") or [])]
    if not roots:
        raise ValueError("Choose at least one folder to scan.")
    m = {"_about": "Your own profile: it overrides the shipped rules. Edit it in Settings; old copies are kept in versions/.",
         "profile": ans.get("profile_name") or f"{socket.gethostname().split('.')[0]}", "preset": preset, "region": region,
         "role": role, "roots": roots, "library": tokenise(os.path.abspath(os.path.expanduser(ans["library"]))) if ans.get("library") and not ans["library"].startswith("{") else (ans.get("library") or default_library()), "exclude": ans.get("exclude") or [],
         "protect": ans.get("protect") or [], "access": {"mode": access}, "hub": {"enabled": role == "hub"},
         "ui": {"lan": {"enabled": access in ("lan", "remote")}}}
    for k in ("entity_types", "layout_preset", "group_labels"):
        if k in pr:
            m[k] = pr[k]
    if pr.get("extra_topics"):
        base = _read(os.path.join(ROOT, "profiles", "base.json"))
        m["topics"] = base.get("topics", []) + pr["extra_topics"]
    people = _clean_people(ans.get("people"))
    you = str(ans.get("you") or "").strip()
    if you and not any(p["name"] == you for p in people):
        people.insert(0, {"name": you, "type": "Self"})
    if people:
        m["entities"] = people
    if ans.get("speech_languages"):
        m["plugins"] = {"transcribe": {"languages": list(ans["speech_languages"])}}
    m["setup_done"] = True
    return m


def init_profile(ans, by="setup"):
    m = build_profile(ans)
    old = _load()
    if old:  # keep anything the wizard does not ask about (aliases, content words, rules learnt, …)
        before = {e["name"]: e for e in old.get("entities", [])}
        if "entities" in m:
            m["entities"] = [{**before.get(e["name"], {}), **e} for e in m["entities"]]
        m = _merge(old, m)
    _write(m, by)
    return m


# ---------------------------------------------------------------- requirements check
def _which(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _pkg_install(pkg_apt, pkg_dnf=None, pkg_pacman=None, brew=None):
    """Command that installs a package with this computer's package manager (shown to you, run only with your OK)."""
    if platforms.SYSTEM == "linux":
        if _which("apt-get"):
            return ["sudo", "apt-get", "install", "-y", pkg_apt]
        if _which("dnf"):
            return ["sudo", "dnf", "install", "-y", pkg_dnf or pkg_apt]
        if _which("pacman"):
            return ["sudo", "pacman", "-S", "--noconfirm", pkg_pacman or pkg_apt]
        if _which("zypper"):
            return ["sudo", "zypper", "install", "-y", pkg_dnf or pkg_apt]
    if platforms.SYSTEM == "macos" and brew and _which("brew"):
        return ["brew", "install", brew]
    return None


HELPER_SRC = os.path.join(ROOT, "helpers", "macos", "fehelper.swift")
HELPER_BIN = os.path.join(ROOT, "helpers", "macos", "fehelper")


def build_helper(log=print):
    """Compile the macOS helper (PDF text, OCR, photo labels, similar photos, transcripts) from its source."""
    swiftc = _which("swiftc")
    if not swiftc:
        raise RuntimeError("swiftc not found: install Apple's Command Line Tools (xcode-select --install)")
    out = []
    for name in ("fehelper", "fetrash"):
        src = os.path.join(ROOT, "helpers", "macos", name + ".swift")
        if os.path.exists(src):
            dst = os.path.join(ROOT, "helpers", "macos", name)
            r = subprocess.run([swiftc, "-O", src, "-o", dst + ".new"], capture_output=True, text=True, timeout=900)
            if r.returncode:
                raise RuntimeError(f"building {name} failed:\n{r.stderr[-2000:]}")
            os.replace(dst + ".new", dst)
            out.append(name)
            log(f"built helpers/macos/{name}")
    return out


def _helper_current():
    return os.path.exists(HELPER_BIN) and os.path.getmtime(HELPER_BIN) >= os.path.getmtime(HELPER_SRC) - 1


def checks(cfg=None):
    """Every requirement, with what is missing and how to fix it. need: required / recommended / optional."""
    S, out = platforms.SYSTEM, []

    def add(cid, title, ok, need, detail="", fix="", cmd=None, fn=None, status=None):
        out.append({"id": cid, "title": title, "status": status or ("ok" if ok else "missing"), "need": need,
                    "detail": detail, "fix": "" if ok else fix, "cmd": None if ok else cmd, "fn": None if ok else fn})

    v = sys.version_info
    add("python", f"Python {v.major}.{v.minor}", v >= (3, 9), "required", sys.executable,
        "Install Python 3.9 or newer (python.org, the Microsoft Store, or your package manager).")
    try:
        import sqlite3
        c = sqlite3.connect(":memory:"); c.execute("CREATE VIRTUAL TABLE t USING fts5(x)"); c.close()
        fts = True
    except Exception:
        fts = False
    add("fts5", "SQLite full-text search (FTS5)", fts, "required", "", "Use a standard Python build from python.org (it includes FTS5).")
    add("profile", "Your profile", has_profile(), "required", PROFILE if has_profile() else "",
        "Run  uo serve  and finish the set-up wizard in the browser (or  uo init).")
    if S == "macos":
        add("hdiutil", "Encrypted disk images (hdiutil, security)", bool(_which("hdiutil") and os.path.exists("/usr/bin/security")),
            "required", "the catalogue is kept in an AES-256 disk image; its key in your Keychain", "These come with macOS.")
        try:
            fv = subprocess.run(["fdesetup", "status"], capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            fv = ""
        add("filevault", "FileVault disk encryption", "On" in fv, "recommended", fv,
            "System Settings → Privacy & Security → FileVault → Turn On.")
        if os.path.exists(HELPER_SRC):
            have = _helper_current()
            add("helper", "macOS reader (OCR, photos, transcripts)", have, "recommended",
                "built" if have else ("out of date" if os.path.exists(HELPER_BIN) else "not built yet"),
                "Build it from source (needs Apple's Command Line Tools).", fn="build_helper")
            if not have and not _which("swiftc"):
                add("swiftc", "Apple Command Line Tools (swiftc)", False, "recommended", "", "Opens Apple's installer.", cmd=["xcode-select", "--install"])
        mv = platform_version()
        add("speech", "On-device speech transcripts", mv >= 26, "optional", f"macOS {mv}", "Needs macOS 26 or newer.")
    else:
        d = platforms.data_dir()
        try:
            ok, how = platforms.disk_protected(d)
        except Exception as e:
            ok, how = False, str(e)
        allow = bool(cfg and cfg["catalogue"].get("allow_unencrypted_disk"))
        add("encryption", "Disk encryption for the catalogue", ok, "required", how + (" (you allowed an unencrypted disk)" if allow and not ok else ""),
            "Windows: Settings → Privacy & security → Device encryption (or BitLocker) → On.  Linux: use a LUKS-encrypted disk "
            "or an encrypted home folder.", status="warn" if allow and not ok else None)
        pdf = _which("pdftotext")
        fix = ("Download Poppler for Windows, unzip it and add its bin folder to PATH (see the manual)." if S == "windows"
               else "Install Poppler's pdftotext.")
        add("pdftotext", "PDF text (pdftotext)", bool(pdf), "recommended", pdf or "", fix, cmd=_pkg_install("poppler-utils", "poppler-utils", "poppler"))
    mode = (cfg.get("access") or {}).get("mode") if cfg else "local"
    ossl = bool(_which("openssl") or os.path.exists("/usr/bin/openssl"))
    add("openssl", "OpenSSL (HTTPS for phones, tablets and other computers)", ossl,
        "required" if mode in ("lan", "remote") or (cfg and (cfg.get("role") in ("hub", "agent"))) else "optional", "",
        "Install OpenSSL." + (" (winget install -e --id ShiningLight.OpenSSL.Light)" if S == "windows" else ""),
        cmd=_pkg_install("openssl", brew="openssl") if S != "windows" else None)
    if mode == "remote":
        from . import lan
        vip = lan.vpn_ip((cfg.get("access") or {}).get("remote"))
        add("vpn", "Your own VPN for away-from-home access", bool(vip), "required", vip or "",
            "Install Tailscale (or WireGuard) on this computer and on your phone, sign in to both, then restart  uo serve.")
    try:
        free = shutil.disk_usage(DATA).free
    except OSError:
        free = 0
    add("space", "Free disk space for the catalogue", free > 2 * 1024 ** 3, "recommended", f"{free / 1024 ** 3:.1f} GB free",
        "Free some space: the catalogue needs about 1 GB per 100,000 files.")
    if cfg:
        missing = [r for r in cfg.roots if not os.path.isdir(r)]
        add("roots", "Folders to scan exist", not missing, "recommended", ", ".join(missing[:5]),
            "Fix the list of folders in Settings → Folders & layout (a disconnected drive is skipped until it is back).")
        ol = cfg["engine"]["ai"]["ollama"]
        if ol.get("enabled"):
            up = _port_open("127.0.0.1", 11434)
            add("ollama", "Local AI (Ollama)", up, "optional", ol.get("model") or "", "Start Ollama, or turn it off in Settings → Plug-ins & AI.")
    port = (cfg.get("ui", {}) if cfg else {}).get("port", 8765)
    add("port", f"Page address 127.0.0.1:{port}", True, "optional", "free" if not _port_open("127.0.0.1", port) else "in use (already running?)",
        status="ok" if not _port_open("127.0.0.1", port) else "info")
    return out


def platform_version():
    if platforms.SYSTEM != "macos":
        return 0
    import platform as P
    try:
        return int(P.mac_ver()[0].split(".")[0])
    except ValueError:
        return 0


def _port_open(host, port):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def fix(check, log=print):
    """Run the fix for one check (the caller has asked you first)."""
    if check.get("fn") == "build_helper":
        return build_helper(log)
    if check.get("cmd"):
        log("running: " + " ".join(check["cmd"]))
        return subprocess.run(check["cmd"]).returncode == 0
    return False


def report(cfg=None):
    rows = checks(cfg)
    sym = {"ok": "✓", "missing": "✗", "warn": "!", "info": "·"}
    lines = [f"Universal Organiser {VERSION} on {platforms.SYSTEM} — requirements"]
    for c in rows:
        s = sym[c["status"]] if c["status"] != "missing" or c["need"] == "required" else "–"
        lines.append(f" {s} {c['title']}" + (f"  ({c['detail']})" if c["detail"] else "") + ("" if c["status"] == "ok" else f"  [{c['need']}]"))
        if c["fix"]:
            lines.append(f"     fix: {c['fix']}" + (f"\n     command: {' '.join(c['cmd'])}" if c.get("cmd") else "")
                         + ("\n     command: uo doctor --fix" if c.get("fn") else ""))
    bad = [c for c in rows if c["status"] == "missing" and c["need"] == "required"]
    lines.append("Ready." if not bad else f"{len(bad)} required item(s) missing.")
    return "\n".join(lines), rows
