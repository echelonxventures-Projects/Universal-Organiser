"""Everything that differs between macOS, Windows and Linux lives here. The rest of the engine asks this module.

Catalogue protection (decision: rely on the OS, standard library only):
  macOS   - AES-256 encrypted disk image, key in the login Keychain (vault.py)
  Windows - catalogue in %LOCALAPPDATA%\\Universal Organiser; refuses to start unless the drive has BitLocker / Device Encryption on
  Linux   - catalogue in $XDG_DATA_HOME/universal-organiser; refuses unless it sits on LUKS/dm-crypt or an encrypted home (ecryptfs)
"""
import os, sys, re, json, shutil, platform, subprocess, time

SYSTEM = {"Darwin": "macos", "Windows": "windows"}.get(platform.system(), "linux")
HOME = os.path.expanduser("~")

# st_flags / st_file_attributes markers for "this file lives only in the cloud" (reading it would download it)
_MAC_DATALESS = 0x40000000
_WIN_OFFLINE = 0x1000
_WIN_RECALL_ON_OPEN = 0x40000
_WIN_RECALL_ON_DATA_ACCESS = 0x400000


def norm(p):
    """One path form everywhere: forward slashes (Windows accepts them), so prefix checks work on every OS."""
    return p.replace("\\", "/") if SYSTEM == "windows" and p else p


def tokens():
    """Path tokens usable in profiles, so one profile works on several machines."""
    t = {"HOME": HOME}
    if SYSTEM == "macos":
        t["ICLOUD"] = os.path.join(HOME, "Library/Mobile Documents/com~apple~CloudDocs")
    elif SYSTEM == "windows":
        t["ONEDRIVE"] = os.environ.get("OneDrive") or os.path.join(HOME, "OneDrive")
        t["LOCALAPPDATA"] = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
    else:
        t["XDG_DATA_HOME"] = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
    return t


def cloud_label(path):
    if "Mobile Documents/com~apple~CloudDocs" in path:
        return "iCloud Drive"
    od = tokens().get("ONEDRIVE")
    if od and (path == od or path.startswith(od + os.sep)):
        return "OneDrive"
    return None


def cloud_only(st):
    """True when the file's content is not on this computer (iCloud / OneDrive placeholder)."""
    if SYSTEM == "macos":
        return bool(getattr(st, "st_flags", 0) & _MAC_DATALESS) or (st.st_size > 0 and getattr(st, "st_blocks", 1) == 0)
    if SYSTEM == "windows":
        a = getattr(st, "st_file_attributes", 0)
        return bool(a & (_WIN_OFFLINE | _WIN_RECALL_ON_OPEN | _WIN_RECALL_ON_DATA_ACCESS))
    return False


def disk_bytes(st):
    blocks = getattr(st, "st_blocks", None)
    return blocks * 512 if blocks else st.st_size


# ---------------------------------------------------------------- catalogue storage
def data_dir():
    """Catalogue folder on Windows/Linux (macOS uses the encrypted vault). UO_DATA puts it inside that folder instead.
    An existing catalogue under the engine's earlier name (FileEngine) keeps being used."""
    if os.environ.get("UO_DATA"):
        return os.path.join(os.path.abspath(os.path.expanduser(os.environ["UO_DATA"])), "catalogue")
    if SYSTEM == "windows":
        new, old = (os.path.join(tokens()["LOCALAPPDATA"], n, "catalogue") for n in ("Universal Organiser", "FileEngine"))
    elif SYSTEM == "linux":
        new, old = (os.path.join(tokens()["XDG_DATA_HOME"], n, "catalogue") for n in ("universal-organiser", "fileengine"))
    else:
        return None
    return old if os.path.isdir(old) and not os.path.isdir(new) else new


def disk_protected(path):
    """(protected?, how) for the disk that holds `path`."""
    try:
        if SYSTEM == "windows":
            return _windows_bitlocker(path)
        if SYSTEM == "linux":
            return _linux_crypt(path)
    except Exception as e:  # never guess "protected" on an error
        return False, f"could not check ({type(e).__name__})"
    return True, "macOS encrypted disk image"


def _windows_bitlocker(path):
    drive = os.path.splitdrive(os.path.abspath(path))[0] or "C:"
    ps = ("$v=(New-Object -ComObject Shell.Application).NameSpace('%s\\').Self.ExtendedProperty('System.Volume.BitLockerProtection');"
          "Write-Output $v" % drive)
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True, timeout=30).stdout.strip()
    # 1 = on, 3 = encrypting (protected as it goes); 2 = off, 4/5 = decrypting / suspended, empty = no BitLocker
    states = {"1": (True, "BitLocker on"), "3": (True, "BitLocker encrypting"), "2": (False, "BitLocker off"),
              "4": (False, "BitLocker decrypting"), "5": (False, "BitLocker suspended")}
    return states.get(out, (False, f"BitLocker not available ({out or 'no value'})"))


def _mount_of(path):
    path = os.path.realpath(path)
    best = None
    with open("/proc/self/mountinfo") as f:
        for line in f:
            pre, post = line.split(" - ", 1)
            parts, rest = pre.split(), post.split()
            mnt = parts[4].replace("\\040", " ")
            if (path == mnt or path.startswith(mnt.rstrip("/") + "/")) and (best is None or len(mnt) > len(best[0])):
                best = (mnt, rest[0], rest[1], parts[2])  # mount point, fs type, source, major:minor
    return best


def _dm_is_crypt(majmin, seen=None):
    seen = seen or set()
    if majmin in seen:
        return False
    seen.add(majmin)
    base = f"/sys/dev/block/{majmin}"
    uuid = os.path.join(base, "dm", "uuid")
    if os.path.exists(uuid) and open(uuid).read().startswith("CRYPT-"):
        return True
    slaves = os.path.join(base, "slaves")
    if os.path.isdir(slaves):
        for s in os.listdir(slaves):
            dev = os.path.join(slaves, s, "dev")
            if os.path.exists(dev) and _dm_is_crypt(open(dev).read().strip(), seen):
                return True
    return False


def _linux_crypt(path):
    os.makedirs(path, exist_ok=True)
    m = _mount_of(path)
    if not m:
        return False, "mount not found"
    mnt, fstype, source, majmin = m
    if fstype == "ecryptfs":
        return True, "encrypted home (ecryptfs)"
    if fstype in ("zfs",) and shutil.which("zfs"):
        enc = subprocess.run(["zfs", "get", "-H", "-o", "value", "encryption", source], capture_output=True, text=True, timeout=20).stdout.strip()
        return (enc not in ("", "off", "-")), f"ZFS encryption {enc or 'unknown'}"
    if _dm_is_crypt(majmin):
        return True, f"LUKS / dm-crypt ({source})"
    return False, f"{fstype} on {source} is not encrypted"


def open_store(cfg, create=True):
    """Folder that holds the catalogue, after checking it is protected."""
    if SYSTEM == "macos":
        from . import vault
        return vault.open_vault(cfg, create=create)
    d = data_dir()
    os.makedirs(d, exist_ok=True)
    if cfg["catalogue"].get("encrypted", True):
        ok, how = disk_protected(d)
        if not ok and not cfg["catalogue"].get("allow_unencrypted_disk", False):
            hint = ("Turn on BitLocker or Device Encryption (Settings > Privacy & security > Device encryption)" if SYSTEM == "windows"
                    else "Use a LUKS-encrypted disk or an encrypted home folder")
            raise SystemExit(f"The catalogue would hold your documents' text, but this disk is not encrypted ({how}).\n{hint}, "
                             f"then run this again. (To accept the risk anyway: set catalogue.allow_unencrypted_disk = true in the machine profile.)")
    return d


def close_store():
    if SYSTEM == "macos":
        from . import vault
        vault.close_vault()


# ---------------------------------------------------------------- desktop actions
def reveal(path):
    """Show a file in the file manager of this computer."""
    if SYSTEM == "macos":
        subprocess.run(["/usr/bin/open", "-R", path])
    elif SYSTEM == "windows":
        subprocess.run(["explorer", "/select,", os.path.normpath(path)])
    else:
        uri = "file://" + path
        if shutil.which("dbus-send"):
            r = subprocess.run(["dbus-send", "--session", "--dest=org.freedesktop.FileManager1", "--type=method_call",
                                "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems", f"array:string:{uri}", "string:"],
                               capture_output=True)
            if r.returncode == 0:
                return
        if shutil.which("xdg-open"):
            subprocess.run(["xdg-open", os.path.dirname(path)])


def trash_dir(cfg):
    """Where 'Move to Trash' puts files. Windows has no movable Recycle Bin folder, so a holding folder in the library is used."""
    if SYSTEM == "macos":
        return os.path.join(HOME, ".Trash")
    if SYSTEM == "linux":
        return os.path.join(tokens()["XDG_DATA_HOME"], "Trash", "files")
    return norm(os.path.join(cfg.library, "_Trash (Universal Organiser - empty when sure)"))


def after_trash(src, dst):
    """Linux desktops need a .trashinfo note to show and restore a trashed file."""
    if SYSTEM != "linux":
        return
    info = os.path.join(os.path.dirname(os.path.dirname(dst)), "info")
    os.makedirs(info, exist_ok=True)
    from urllib.parse import quote
    with open(os.path.join(info, os.path.basename(dst) + ".trashinfo"), "w") as f:
        f.write(f"[Trash Info]\nPath={quote(src)}\nDeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n")


def after_untrash(dst):
    if SYSTEM == "linux":
        p = os.path.join(os.path.dirname(os.path.dirname(dst)), "info", os.path.basename(dst) + ".trashinfo")
        if os.path.exists(p):
            os.remove(p)


def thumbnail(src, out, px=360):
    """Small JPEG preview. macOS: sips. Elsewhere there is no built-in converter, so the caller may send small originals."""
    if SYSTEM == "macos":
        subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", "-s", "formatOptions", "70", "-Z", str(px), src, "--out", out],
                       capture_output=True, timeout=30)
        return os.path.exists(out)
    return False


def keep_awake_cmd():
    return ["caffeinate", "-i"] if SYSTEM == "macos" else []
