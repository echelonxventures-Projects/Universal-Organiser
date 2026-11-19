# Architecture

Universal Organiser is one Python package (`engine/`, standard library only), a small Swift helper for macOS, and
static HTML pages. There is no database server, no web framework and no build step.

```
            ┌──────────── browser (this computer, phones, tablets) ────────────┐
            │  HTML pages: Overview · Files · Browse · Triage · Sorter · …     │
            └───────────────────────────────┬───────────────────────────────────┘
                                            │ JSON API (X-FE header, cookie)
   other computers ── HTTPS, bearer token ─▶│
   (agents: uo agent)                        ▼
                                   engine/server.py  ──  auth, lan (TLS, devices), hub
                                            │
     uo (cli.py) ── scan.py ──▶ plugins/ (metadata, hash, text, archive, macOS Vision, classify)
                                            │
                                   catalogue.py  (SQLite + FTS5)
                                            │
                       platforms.py: encrypted store (vault.py on macOS, encrypted disk elsewhere)
```

## Modules

| Module | Role |
|---|---|
| `cli.py` | command line (`uo`) |
| `config.py` | builds the profile: base + region pack + your profile; path tokens; `ROOT` (program) and `DATA` (your data) |
| `platforms.py` | **all** differences between macOS, Windows and Linux: data folder, encryption checks, cloud-only detection, reveal, trash, thumbnails, tokens |
| `vault.py` | macOS: AES-256 sparse disk image, random key in the login Keychain (one key per data folder; earlier FileEngine key still used) |
| `catalogue.py` | the SQLite catalogue, full-text index, decisions, change log with undo; `uo://` remote records |
| `scan.py` | walks the folders, builds units (file, project, package, protected), runs plug-ins in batches, forgets removed files |
| `plugins/` | readers: `basic` (metadata, hash), `text`, `archive`, `macos_vision` (PDF/OCR/labels via the helper), `classify` (dates, document type, owner, topic) |
| `doctypes.py` | document-type groups from `tags` |
| `query.py` | plain-language, forgiving search |
| `server.py` | the page and the API |
| `auth.py` | accounts, PBKDF2 password hashes, sessions |
| `lan.py` | HTTPS for phones/tablets/agents: private CA, certificates, address checks, device approval, VPN address |
| `hub.py` / `agent.py` | catalogues from other computers: pairing, tokens, push, end-of-sync clean-up |
| `setup.py` | presets, country packs, folder detection, profile writing, requirement checks, building the helper |
| `service.py` | start at login |
| `analytics.py`, `overview.py`, `home.py`, `insights.py`, `smartfolders.py` | views, health, alerts, recommendations, learning, reports |
| `sorter.py`, `tidy.py`, `tags.py`, `naming.py` | plans and logged, undoable moves; library tidy and archive; Finder tags; new file names for moved documents |
| `deepread.py`, `transcribe.py`, `similar.py` | all pages of scans, speech transcripts, near-identical photos (macOS) |
| `projects.py`, `projindex.py`, `cleanup.py`, `projmove.py`, `projsteps.py`, `declutter.py` | projects: status, iCloud exclusion, index, version review, logged folder steps |
| `settings.py`, `reclassify.py` | validated profile editing with versions; re-applying rules |
| `i18n.py`, `i18n.js`, `i18n/<code>.json` | page languages: the server picks the language and puts its dictionary in the page; the browser translates every text as it appears |
| `activity.py` | who used it: sign-ins, failures, sign-outs, pages opened (90 days) |
| `updates.py` | daily release check, checksum-verified update through the release's installer |
| `a11y.js` | added to every page by the server: skip link, landmarks, dialog focus, names for controls, keyboard access, live messages |
| `helpers/macos/fehelper.swift` | PDFKit text, Vision OCR and labels, image fingerprints, SpeechTranscriber, iCloud download; read-only |

## Data model (SQLite, inside the encrypted store)

| Table | Holds |
|---|---|
| `files` | one record per unit: path, name, kind, unit, size, dates, cloud-only/sensitive/protected flags, hash, owner (`entity`, type, confidence, reason, suggestions), document type, topic, lifecycle, title, pages, snippet, tags, errors, `scanned_at`, `seen_at` |
| `fts` | full-text index (name, path, title, body text, tags, owner, type) |
| `archive_items` | contents of archives |
| `decisions` | labels set by a person, by path and content hash (they win over rules) |
| `changes` | every label change and rules run, with the data to undo it |
| `plan` | files marked for Trash or Archive |
| `sort_runs` | every sorter run with its log file and undo state |
| `dismissed` | dismissed alerts, recommendations, triage skips (with expiry) |
| `users`, `devices` | accounts; approved phones/tablets |
| `access_log` | sign-ins, failed attempts, sign-outs, pages opened (90 days) |
| `machines`, `pair_codes` | hub: paired computers (token hash) and pairing codes |
| `smart_folders`, `finder_tags`, `transcripts`, `photo_features` | saved views, tags written, transcripts, photo fingerprints |
| `project_status`, `project_sync`, `cleanup_held` | projects: working status, iCloud exclusion, held versions |
| `meta`, `history` | caches, monthly snapshots and reports, last visit per user; scan history |

Records from other computers are stored with paths `uo://<computer>/<path>`; `catalogue.LOCAL_SQL` keeps them out of
every local action and out of the local scan's clean-up.

## Scan pipeline

1. **Walk** each root (skipping excluded, hidden, noise; packages and projects become single units; cloud-only files
   are noted, never read).
2. **Compare** size and modification time with the catalogue; unchanged files are only marked as seen.
3. **Read** new/changed files in batches of 150 through the enabled plug-ins (a failing plug-in never stops a scan).
4. **Classify**: dates → document type → owner (holder fields first) → topic; a person's decision overrides.
5. **Save** records and text; **forget** local records not seen in this scan.
6. **After**: insights/report snapshot, photo fingerprints, remaining PDF pages, transcripts, projects index, hub sync.

## Safety rules enforced in code

- The page and API only ever *read* files, except the Sorter/Move runs, Finder tags, project iCloud exclusion and
  clean-up holding — each admin-only, previewed, logged and undoable.
- Sorter runs take paths only from the server's own plan; each move is re-checked (size, date, protection, project,
  destination inside the library, sensitive never into cloud folders, cloud-only never moved off its cloud).
- Members never see sensitive files or owners outside their scope (enforced in SQL for every query).
- Fixes that need administrator rights are never run from the page.
- Remote (`uo://`) records are never acted on.

## Tests

`tests/test_engine.py`: profiles and country packs, presets, the privacy check, the wizard on a new install, a member
account's limits, hub + agent pairing, sync, deletion and removal, packaging. Each test uses throwaway data folders and
an unencrypted test catalogue. CI runs them on macOS, Windows and Linux with Python 3.9 and 3.12, plus:

- **Installers** (`tools/install_smoke.py`): on clean macOS, Windows and Linux machines, the real installer
  (`install.sh`, or `install.cmd` on Windows) into a folder with a space in its name; then the installed `uo` runs help, doctor,
  a scan, a search and the page; then the installer runs again (an update) and the profile and catalogue must still be there.
- **Accessibility** (`tools/a11y_check.py`): language, title, zoomable viewport, one heading, main landmark, named fields and
  buttons, no mouse-only elements in the markup, colour contrast of each page's light and dark colours.
- **Privacy** (`tools/privacy_check.py`).
- **Languages** (`tools/i18n_extract.py --check`): every translation file is valid and uses only placeholders that the
  English has; the tests also check how a page's language is chosen.
- **Updates**: a fake release served from local files is checksum-checked and installed over a copy by its own
  installer (profile kept); a tampered download changes nothing.
