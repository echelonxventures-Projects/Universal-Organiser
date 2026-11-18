# Universal Organiser

Find, understand and tidy every file you own — on your own computers, with nothing sent to the internet.

Universal Organiser keeps an **encrypted catalogue** of your files: names, dates, sizes, duplicates, and the text inside
documents, scans and photos. It works out **whose** a document is (the name printed on an ID card, a payslip, a policy)
and **what** it is (passport, invoice, bank statement, certificate…), then lets you search everything in plain words
(`dad insurance 2023`), see where your space goes, and sort files into a clean folder structure — always as a preview
you approve first, and always with undo.

- **Self-hosted.** Runs on your Mac, Windows PC or Linux computer. Python standard library only; no cloud, no account.
- **One search for the whole home.** Make one computer the **hub**; the others send their catalogues to it. Phones and
  tablets use the page over home Wi-Fi (HTTPS, each device approved with a 6-digit code). Away from home only through
  your own VPN.
- **Generic.** Ready-made presets (Just me, Family, Small office, Student, Custom), country packs for local documents,
  and every rule editable in Settings. No names are built in.
- **Safe by design.** Read-only until you approve a plan. Every move is logged and can be undone. Sensitive files (keys,
  passwords, identity documents marked sensitive) are never read for text, never sent to cloud folders, never shown to
  family members' accounts.

## Install

| System | How |
|---|---|
| **macOS** 13+ | `sh install/install.sh` |
| **Linux** | `sh install/install.sh` |
| **Windows** 10/11 | double-click `install\install.cmd` |
| **iPhone, iPad, Android** | nothing to install: open the hub's page in the browser (see the manual) |

The installer recognises the system, checks what is missing (Python 3.9+, disk encryption, PDF reader, HTTPS tools),
offers to fix it, then opens the page: create the admin account and the **set-up wizard** asks the rest.

Check a computer any time with `uo doctor` (`uo.cmd doctor` on Windows).

## Use

```
uo serve           open the page (http://127.0.0.1:8765)
uo scan            update the catalogue (only what changed)
uo search WORDS    search from the terminal
uo help            every command
```

## Documentation

| | |
|---|---|
| [User manual](docs/manual.md) | install, set-up, every page, phones, several computers, privacy, undo, troubleshooting |
| [Features](docs/features.md) | everything it does, and on which systems |
| [Administrator guide](docs/admin-guide.md) | backups, moving computers, accounts, hub operations, updates |
| [Command line](docs/cli.md) · [Configuration](docs/configuration.md) | every command and setting |
| [HTTP API](docs/api.md) · [Architecture](docs/architecture.md) | for developers, including the agent protocol |

## What works where

| | macOS | Windows | Linux |
|---|---|---|---|
| Catalogue, search, owners, topics, duplicates, sorter with undo, analytics, insights, accounts | ✓ | ✓ | ✓ |
| Text in PDFs | ✓ built in | with Poppler | with Poppler |
| Text in scans and photos (OCR), photo labels, similar photos, speech transcripts | ✓ (on-device) | – | – |
| Encrypted catalogue | AES-256 disk image, key in Keychain | needs BitLocker / Device encryption | needs LUKS / encrypted home |
| Hub, agent, phones & tablets, VPN access | ✓ | ✓ | ✓ |

## Development

```
python3 -m unittest discover -s tests -v     # tests use throwaway data folders only
python3 tools/privacy_check.py --all         # nothing personal in the repository
python3 tools/a11y_check.py                  # the pages stay usable by keyboard and screen reader
sh install/install.sh --dir /tmp/uo-try --yes --no-start --no-link && python3 tools/install_smoke.py /tmp/uo-try first
git config core.hooksPath .githooks          # run the privacy check before every commit and push
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Licence

[MIT](LICENSE)
