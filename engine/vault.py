"""Encrypted storage for the catalogue (macOS): an AES-256 encrypted sparse disk image whose
random password lives only in the login Keychain. Other platforms fall back to a plain folder
(to be replaced by that OS's built-in encryption plug-in)."""
import os, subprocess, secrets
from .config import DATA as ROOT

import hashlib
# one Keychain key per data folder, so a second install (or a test copy) on the same Mac never picks up another's key
SERVICE = "UniversalOrganiser-vault"
ACCOUNT = "universal-organiser-" + hashlib.sha256(ROOT.encode()).hexdigest()[:12]
LEGACY = ("FileEngine-vault", "fileengine")  # key made by earlier versions (FileEngine): still found and used
IMAGE = os.path.join(ROOT, "vault.sparsebundle")
MOUNT = os.path.join(ROOT, "vault")


def _security(cmd):
    # commands go via stdin (security -i) so the password never appears in the process list
    return subprocess.run(["/usr/bin/security", "-i"], input=cmd + "\n", capture_output=True, text=True, timeout=30)


def _password(service=None, account=None):
    if service is None:  # this version's key, else the one an earlier version made
        return _password(SERVICE, ACCOUNT) or (_password(*LEGACY) if os.path.exists(IMAGE) else None)
    r = subprocess.run(["/usr/bin/security", "find-generic-password", "-a", account, "-s", service, "-w"],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip() if r.returncode == 0 else None


def mounted():
    return os.path.ismount(MOUNT)


def open_vault(cfg, create=True):
    if cfg.platform != "macos" or not cfg["catalogue"].get("encrypted", True):
        os.makedirs(MOUNT, exist_ok=True)
        return MOUNT
    if mounted():
        return MOUNT
    pw = _password()
    if not os.path.exists(IMAGE):
        if not create:
            raise SystemExit("No catalogue yet. Run: uo scan")
        if pw is None:
            pw = secrets.token_urlsafe(32)
            r = _security(f'add-generic-password -a {ACCOUNT} -s {SERVICE} -l "Universal Organiser catalogue" -w "{pw}" -U')
            if _password() != pw:
                raise SystemExit("Could not store the vault key in Keychain: " + r.stderr)
        subprocess.run(["hdiutil", "create", "-quiet", "-size", cfg["catalogue"].get("vault_size", "20g"), "-type", "SPARSEBUNDLE",
                        "-fs", "APFS", "-encryption", "AES-256", "-stdinpass", "-volname", "Universal Organiser Catalogue", IMAGE],
                       input=pw, text=True, check=True, timeout=180)
    if pw is None:
        raise SystemExit(f"Vault key missing from Keychain ({SERVICE}).")
    os.makedirs(MOUNT, exist_ok=True)
    subprocess.run(["hdiutil", "attach", "-quiet", "-nobrowse", "-owners", "on", "-stdinpass", "-mountpoint", MOUNT, IMAGE],
                   input=pw, text=True, check=True, timeout=180)
    open(os.path.join(MOUNT, ".metadata_never_index"), "a").close()
    return MOUNT


def close_vault():
    if mounted():
        subprocess.run(["hdiutil", "detach", "-quiet", MOUNT], timeout=120)
