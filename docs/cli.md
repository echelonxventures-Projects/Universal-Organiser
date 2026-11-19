# Command-line reference

`uo` on macOS and Linux, `uo.cmd` on Windows (`fe` / `fe.cmd` still work: the earlier name). `uo help` prints the
summary. Every command uses the profile and catalogue of the data folder shown by `uo version`; set `UO_DATA` to use
another one.

## Set-up and operation

| Command | What it does |
|---|---|
| `uo version` | version, system, Python, program folder, data folder |
| `uo doctor` | every requirement with ✓ / ✗ / – and how to fix it; exit code 0 even when something is missing |
| `uo doctor --fix [--yes]` | offers each available fix (package install, macOS reader build) and asks first; `--yes` answers yes |
| `uo doctor --build-helper` | builds only the macOS reader (`helpers/macos/fehelper`, `fetrash`) with `swiftc` |
| `uo init [options]` | writes your profile without the browser. Options: `--preset personal\|family\|small-office\|student\|custom`, `--region none\|india`, `--folder PATH` (repeat; default: the suggested folders), `--library PATH`, `--name "Your Name"`, `--role standalone\|hub\|agent`, `--access local\|lan\|remote`, `--profile NAME`, `--force` (answer again; the old profile is kept) |
| `uo serve [--lan] [--no-browser]` | runs the page. First run prints a one-time link to create the admin account. `--lan` also starts home Wi-Fi access for this run. `--no-browser` for servers/autostart. Ctrl+C stops. |
| `uo autostart on\|off` | start at login (macOS LaunchAgent `org.universal-organiser`, Linux systemd user service `universal-organiser`, Windows task “Universal Organiser”). Without `on`/`off`: shows the state. |
| `uo update` | brings this copy to the newest release: downloads its program zip, checks the SHA-256 against the release's `SHA256SUMS`, runs that release's installer over this copy (program files only; profile, catalogue, logs and keys stay), rebuilds the macOS reader if needed. A git copy runs `git pull --ff-only` instead. |
| `uo update --check` | only says whether a newer release exists (works even when the daily check is off) |
| `uo package` | `exports/universal-organiser-<version>.zip` in the data folder: program files only (never profile, catalogue, logs, keys) |
| `uo close` | macOS: locks (detaches) the encrypted catalogue. Elsewhere the disk's own encryption protects it. |

## Catalogue

| Command | What it does |
|---|---|
| `uo scan [--full]` | updates the catalogue (only new/changed files; `--full` reads everything again). Afterwards: insights and the monthly report, photo fingerprints 🍎, remaining PDF pages 🍎, transcripts 🍎, the projects index, and a sync to the hub if this computer is paired. Log: `logs/scan-*.log`. |
| `uo status` | progress of a running scan (and whether it looks stuck) |
| `uo stats` | records and size by kind, owner, type, topic; duplicates; sensitive, cloud-only, needs-owner, suggestions, errors |
| `uo search WORDS` | plain-language search, 25 results: date, owner, type, path |
| `uo rules [--apply]` | what re-applying the rules would change (owner, type, topic), with a sample; `--apply` applies it as one undoable change |
| `uo insights` | alerts, recommendations and learnt proposals |
| `uo report [YYYY-MM]` | the monthly pattern report (default: this month) |
| `uo similar [--compute]` | near-identical photo groups 🍎; `--compute` fingerprints new photos first |
| `uo read-all` | reads every page of scanned PDFs 🍎 |
| `uo transcribe [--all]` | transcribes new speech files 🍎; `--all` every local audio/video |
| `uo languages [install xx-YY]` | speech languages: installed / supported / tried automatically; `install` downloads one from Apple 🍎 |
| `uo index` | rewrites the projects index (needs `projects_home`) |
| `uo user list` | accounts with role and scope |
| `uo user passwd NAME` | sets a new password (asks twice) — also the way to recover a forgotten one |

## Several computers

| Command | Where | What it does |
|---|---|---|
| `uo hub code` | hub | a pairing code (`ABCD-EFGH`, single use, 15 minutes) |
| `uo hub list` | hub | paired computers: system, files, last sync |
| `uo hub remove NAME` | hub | removes a computer and all its records |
| `uo agent pair ADDRESS CODE [--name N] [--fingerprint FP] [--yes]` | other computer | pairs with the hub (`https://hub-name.local:8766`). Shows the hub's certificate fingerprint to compare; `--fingerprint` checks it for you; `--yes` skips the question (only when you checked another way). Name defaults to the computer's name. |
| `uo agent sync [--full]` | other computer | sends what changed since the last sync (first time: everything); `--full` sends everything again |
| `uo agent run [--every MINUTES]` | other computer | scan + sync now, then every N minutes (default 60; `0` = once). Log: `logs/agent-YYYYMMDD.log`. |
| `uo agent status` | other computer | paired hub and last sync |
| `uo agent forget` | other computer | forgets the hub (remove it on the hub too) |

## Environment variables

| Variable | Meaning |
|---|---|
| `UO_DATA` | data folder (profile, catalogue, logs, agent state). Default: the program folder. |
| `UO_PRIVACY_PROFILE` | developers: an extra profile the privacy check reads names from |

## Exit codes

`0` success; `1` failure with a message (for example “No profile yet”, “Not paired with a hub yet”, an unencrypted disk
on Windows/Linux); `2` the installer got an unknown option.
