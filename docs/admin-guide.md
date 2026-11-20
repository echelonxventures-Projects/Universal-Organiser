# Administrator guide

For the person who looks after Universal Organiser at home or in a small office. The [user manual](manual.md) covers
everyday use; this guide covers running it well.

## Where things are

`uo version` prints the **program folder** (replaced by updates) and the **data folder** (yours). By default they are
the same folder:

| System | Default folder |
|---|---|
| macOS | `~/Library/Application Support/Universal Organiser` (installs from before 1.0: `…/FileEngine`) |
| Windows | `%LOCALAPPDATA%\Universal Organiser` |
| Linux | `~/.local/share/universal-organiser` |

What is in the data folder is described in [configuration.md](configuration.md#data-folder-layout).

## Backups

Back up the **whole data folder**. The parts that matter:

| Part | Why |
|---|---|
| `profiles/` | your settings and their history |
| macOS `vault.sparsebundle` · Windows/Linux catalogue folder | labels, decisions, accounts, history (rebuildable by a scan except your **decisions and labels**) |
| `logs/*.jsonl` | **undo logs** of every move — without them a run cannot be undone |
| `agent/` (agents) | the pairing; without it, pair again |

**macOS:** the catalogue image is encrypted with a key in your **login Keychain** (item “UniversalOrganiser-vault”,
or “FileEngine-vault” for installs from before 1.0). A backup of the image is useless without that key. Time Machine
backs up both. To keep the key elsewhere (a password manager), view it in *Keychain Access → the item → Show password*.

Run `uo close` before copying the image by hand, so it is not in use.

## Restore or move to a new computer

1. Install Universal Organiser on the new computer (do not run the wizard yet).
2. Copy the old data folder over the new one (macOS: also bring the Keychain item — Migration Assistant does).
3. Check paths in `profiles/machine.json` (folders with `{HOME}` tokens move by themselves; drive letters may not).
4. `uo doctor`, then `uo scan`. Labels and decisions are matched by path and, if files moved, by content hash.

## Accounts

- *Settings → Accounts*: add members with a **scope** (the owners they may see). Members never see sensitive files and
  cannot change anything. Keep at least two admins if more than one person looks after it.
- Forgotten password: `uo user passwd NAME` on the computer itself.
- Sessions end after `ui.idle_hours` of inactivity (default 4).

## Who used it

*Settings → Who used it*: last sign-in and device per account, sign-ins, failed attempts (also for user names that do
not exist), sign-outs and pages opened, kept 90 days (`access_log` table in the catalogue), next to label changes
and sorter runs with the account that made them. Failed sign-ins are also slowed down after several attempts.

## Phones and tablets

*Settings → Accounts → Phones & tablets* lists every device with its owner and last use. **Remove** signs it out at once;
a removed device must be approved again. Approve new devices only when you see the code on that device.

## Hub operations

- Keep the hub on and reachable: `uo autostart on`, and access **Home Wi-Fi** (or **remote** for your VPN).
- *Computers* shows each paired computer's file count and last sync. A computer that has not synced for long is
  probably off, asleep, or no longer running `uo agent run` / autostart.
- **Remove** a computer you no longer use: it deletes its token and all its records on the hub.
- Pairing codes are single-use and expire after 15 minutes. If someone sees a code, it is harmless once used or expired.
- The hub's certificate authority is made once (10 years). Its server certificate is renewed automatically when the
  hub's address changes; agents and phones keep trusting it.
- If you ever delete the hub's `tls` folder, a **new** authority is made: every phone must install the new certificate
  and every agent must pair again (`uo agent forget`, then pair).

## Away-from-home access

Use only your own VPN. Check `uo doctor` shows a VPN address, then *Computers → Also away from home*. For WireGuard
set `access.remote.bind` to the hub's WireGuard address and `access.remote.networks` to your WireGuard range.

## Updates

Once a day the page asks its update source for the newest version (only the program name and version are sent). When
there is one, admins see **Version … is ready** on Home with *What's new*, **Update now** and **Later**. Update now
downloads the program zip, checks its SHA-256 against `SHA256SUMS`, and runs that version's own installer over this copy:
program files are replaced; your profile, catalogue, logs and keys stay. Then the page restarts by itself on the new
version (macOS, Linux and Windows). Every update is listed in *Settings → Who used it*.

**Install by themselves.** *Settings → Plug-ins & AI → Updates → Install updates by themselves* (profile
`updates.auto = true`): a new version is installed once nobody has used the page for 30 minutes and no scan, sort or
re-run is going, and the page restarts. The check also runs every hour in the background, so this works even when nobody
opens Home. A failed automatic update is not retried until someone presses Update now.

**Where updates come from** (one of these):

| Source | Set up | Who it suits |
|---|---|---|
| GitHub, public repository | nothing (the default) | everyone with internet |
| GitHub, private repository | a GitHub token that can read the repository: *Settings → Updates → Save token*, or `uo update --token`. Make it at github.com → Settings → Developer settings → Fine-grained tokens, only that repository, **Contents: read-only**. It is kept in the data folder file `update-token` (readable only by you, never in the profile or exports), only sent to api.github.com and never along a redirect to GitHub's file storage. `UO_UPDATE_TOKEN` in the environment works too. | the main computer |
| A folder or web address | on any up-to-date copy: `uo package --feed "/path/to/shared folder"` (writes `latest.json`, the program zip and `SHA256SUMS`); on the others: *Settings → Updates → Where updates come from* = that folder, or an `https://` address that serves those three files (profile `updates.feed`). A public GitHub release also works as one: `https://github.com/OWNER/REPO/releases/latest/download`. | computers without GitHub access, or no internet (USB stick) |
| The hub | nothing: computers paired with this one (`uo agent pair …`) compare versions at every sync and, when the hub is newer, download the hub's own program over their pinned connection, check it and install it; `uo agent run` then carries on with the new version. `uo agent updates off` on that computer stops it. The Computers page shows each one's version. | family computers, once the repository is private |

So with a private repository only the main computer needs a token; everything paired with it follows it.

**Signed updates.** Every release's `SHA256SUMS` carries the publisher's signature (`SHA256SUMS.sig`, RSA-3072,
SHA-256). The public key is built into the program (`engine/signing.py`), so an update is installed only when it was
signed with the matching private key: a forged or altered release, even one served from the right address or a broken
into account, is refused and nothing changes. A folder you make yourself is signed with
`uo package --feed FOLDER --sign KEY.pem`; an unsigned one is accepted only with `updates.allow_unsigned = true` in that
computer's profile. Computers paired with a hub trust that hub's own program over their pinned connection.

*The publisher's key.* The private key is `update-signing-key.pem` in the publisher's own safe place (never in the
repository) and in the repository secret `UPDATE_SIGNING_KEY`, which the release workflow needs: without it no release is
published. Keep an offline backup: losing it means installed copies can only be updated by installing again by hand. To
change keys, add the new public key to `PUBLIC_KEYS` in one release, sign the next release with the new key, then remove
the old one.

The same from a terminal: `uo update --check` (also shows the source), `uo update`, `uo update --token`,
`uo update --forget-token`. A git checkout updates with `git pull` instead. Turn the daily check off in *Settings →
Plug-ins & AI → Updates* (profile `updates.check = false`). Read `CHANGELOG.md` for what changed.

## Releases and signing

Push a tag `vX.Y.Z` that matches `VERSION` in `engine/setup.py`. The `release` workflow runs the tests, the privacy and
accessibility checks, builds `universal-organiser-X.Y.Z.zip` and `SHA256SUMS`, and publishes a GitHub release with the
CHANGELOG notes, plus `latest.json` so the release also works as a folder-style source. `uo update` and *Update now* use
exactly these files. A private repository is read with the token described above.

**Signing.** What triggers warnings, and what removes them:

| System | Warning | What to do |
|---|---|---|
| Windows | “Windows protected your PC” (SmartScreen) or “Open File – Security Warning” when running `install.cmd` from a downloaded zip | Before unzipping: right-click the zip → *Properties* → tick **Unblock** → OK. Then nothing in it warns. The installer also clears the mark from everything it installs, so `uo.cmd` and the Start-menu entry never warn later. To sign: add an Authenticode code-signing certificate to the repository secrets `WINDOWS_CERT_PFX_BASE64` (the .pfx, base64) and `WINDOWS_CERT_PASSWORD`; the release workflow then signs and time-stamps `install.ps1` (a `.cmd` file cannot be signed). |
| macOS | none for the normal install: `sh install/install.sh` runs a script with the system's own shell, Python is Apple's or python.org's (both signed), and the macOS reader is compiled on your Mac, so Gatekeeper has nothing to check | The installer also removes the download quarantine from the program files. A signed and notarised app bundle would only be needed for a double-click app, which Universal Organiser does not have. |
| Linux | none | – |

## Logs and problems

| Log | Contents |
|---|---|
| `logs/scan-*.log` | each scan: plug-ins, counts, errors |
| `logs/scan-status.json` | the running scan's progress (`uo status`) |
| `logs/sort-*.jsonl`, `project-*.jsonl`, `cleanup.jsonl` | every move (undo) |
| `logs/agent-*.log` | agent runs |
| `logs/autostart.log` | macOS autostart output |

`uo doctor` is the first step for any problem. The [manual's troubleshooting table](manual.md#12-troubleshooting)
lists common cases.

## Uninstall

`uo autostart off`, `uo close`, delete the program/data folder; macOS: delete the Keychain item; Windows: delete the
Start-menu entry and remove the folder from your PATH. Your own files are never affected.
