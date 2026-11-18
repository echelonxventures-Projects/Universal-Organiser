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

Run the newest installer (or `uo update` in a git copy), then restart `uo serve` (or log out and in when it autostarts).
The installer replaces only program files. Read `CHANGELOG.md` for what changed.

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
