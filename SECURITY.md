# Security

## How your data is protected

- **Nothing leaves your computers.** No telemetry, no cloud service, no account. Optional local AI (Ollama) runs on
  the same computer; cloud AI is blocked by the settings validator.
- **Encrypted catalogue.** macOS: AES-256 encrypted disk image whose random key lives only in your login Keychain.
  Windows: refuses to store the catalogue unless BitLocker / Device encryption is on. Linux: refuses unless the folder is
  on LUKS/dm-crypt, ZFS encryption or an encrypted home. (An explicit `catalogue.allow_unencrypted_disk` override exists
  and is reported by `uo doctor`.)
- **The page.** Listens on 127.0.0.1 only, unless you turn on home Wi-Fi access. Sessions are HttpOnly SameSite=Strict
  cookies; every API call needs a custom header and a matching Host/Origin, so other web sites cannot reach it. Passwords
  are salted PBKDF2-SHA256 hashes inside the encrypted catalogue.
- **Home Wi-Fi.** HTTPS with a private certificate authority made on your computer; it answers private addresses only
  and only for its own host names; every new phone or tablet must be approved on the computer with a 6-digit code.
- **Away from home.** Only through your own VPN: the page binds to the VPN address and accepts only the VPN's ranges.
  It never opens a port on your router.
- **Hub and agents.** Pairing uses a one-time code valid 15 minutes; the agent then holds a random token (the hub keeps
  only its SHA-256) and pins the hub's certificate authority after you compare its fingerprint. Agents never send the
  text of sensitive files. Records from other computers are never moved, tagged or read on the hub. Removing a computer
  deletes its token and all its records.
- **Files.** Read-only until you approve a previewed plan; every run is logged with undo; protected folders and projects
  are never moved; sensitive files are never moved into cloud-synced folders.

## Reporting a problem

Please report security problems privately through GitHub's *Report a vulnerability* (Security tab) rather than in a
public issue. Include what you did, what you expected and what happened.
