# Configuration reference

## How the profile is built

```
profiles/base.json            shipped generic rules (replaced on update)
  + profiles/regions/<r>.json country pack named by "region" (shipped)
  + <data>/profiles/machine.json   YOUR profile: written by the wizard, Settings and `uo init`; overrides anything
```

Objects are merged key by key; a list in your profile **replaces** the shipped list. Old copies of your profile are
kept in `<data>/profiles/versions/` on every save (Settings → History restores them). Presets
(`profiles/presets/*.json`) are only starting points copied by the wizard.

**Path tokens** keep a profile portable: `{HOME}` everywhere, `{ICLOUD}` (macOS iCloud Drive), `{ONEDRIVE}` and
`{LOCALAPPDATA}` (Windows), `{XDG_DATA_HOME}` (Linux), and in sorter templates `{LIBRARY}`.

Most people never edit JSON: the wizard and Settings cover the usual keys and validate them.

## Your profile: the usual keys

| Key | Type / example | Meaning |
|---|---|---|
| `profile` | `"Study Mac"` | a name for this computer's profile |
| `preset` | `family` | the preset the wizard started from (information only) |
| `region` | `none`, `india` | country pack |
| `role` | `standalone`, `hub`, `agent` | this computer's part in a home with several computers |
| `setup_done` | `true` | the wizard has been completed (else admins are sent to it) |
| `roots` | `["{HOME}/Documents", "D:/Papers"]` | folders to scan |
| `exclude` | paths | never scanned |
| `protect` | paths | scanned, but never moved or changed (and never removed from protection by Settings) |
| `library` | `"{HOME}/Documents/Organized"` | where the Sorter files things |
| `projects_home` | `"{HOME}/Projects"` | optional: each folder directly inside is one project; the projects index is written there. Off unless set. |
| `extra_project_markers` | `[".myide"]` | more files/folders that mark a code project |
| `entity_types` | `["Self", "Family", …]` | kinds of owners (built in: Self, Family, Friend, Office, Organisation, Client, Property, Vehicle) |
| `entities` | list | the people and organisations — see below |
| `topics` | list | topics with keywords — see below |
| `doc_type_topics` | `{"Payslip": "Work/HR & Payslips"}` | when a document type is detected with confidence, its topic |
| `layout_preset` | `by-owner`, `by-year`, `media`, `classic-numbered` | folder layout for the Sorter (see `presets.layouts`) |
| `group_labels` | `{"Family": "20_Family", "Unsorted": "99_To Sort", …}` | top-level folder names per owner type and for Media, Archive, Unsorted, Duplicates, Testing, Projects |
| `naming_preset` | `original` (default), `dated`, `id-docs`, `invoice`, `screenshot` | file-name style used when you tick **Rename files** in the Sorter (`original` = never rename). See [file renaming](#file-renaming). |
| `access` | `{"mode": "local"}` | `local`, `lan` (home Wi-Fi), `remote` (+ your VPN) — see below |
| `hub` | `{"enabled": true}` | accept catalogues from paired computers |
| `agent` | `{"every_minutes": 60}` | how often `uo autostart` runs scan + sync on an agent |

### Owners (`entities`)

```json
{"name": "Sam Example", "type": "Family", "relation": "brother",
 "aliases": ["\\bsam\\b", "sammy"], "text_all": ["sam", "example"], "not_if": ["bakery"], "expect": ["Passport"]}
```

| Field | Meaning |
|---|---|
| `name`, `type` | display name; one of `entity_types` (`Self` = you) |
| `aliases` | words in file or folder names that mean this owner. Plain text matches anywhere; `\b…\b` matches a whole word (digits and `_` count as separators, so `\bsam\b` matches `Sam1` and `sam_passport`) |
| `text_all` | words that must **all** appear in a document's text to count as a mention (default: the words of the name) |
| `not_if` | words that cancel a match (e.g. a company that carries the person's name) |
| `relation` | shown on the person page |
| `expect` | documents this owner should have (overrides `insights.expected_docs` for the type) |

Owner rules in short: the holder named on a document (ID cards, policies, payslips, certificates) → **high**
confidence; a name in the file name → medium/high; a mere mention → **suggestion only**; conflicting signals → no
owner, both suggested.

### Topics (`topics`)

```json
{"name": "Finance/Tax", "lifecycle": "Permanent", "keywords": ["income tax", "\\btax\\b", "tax return"]}
```

`/` makes sub-topics. `lifecycle` is one of `lifecycles` (`Permanent`; `Temporary` = 90 days; `Testing` = 30 days),
used by the lifecycle recommendations. A region may add words through `topic_keywords_extra`.

### Access (`access`)

```json
"access": {"mode": "remote", "remote": {"bind": "auto", "networks": ["100.64.0.0/10", "fd7a:115c:a1e0::/48"], "names": ["hub.tailnet-name.ts.net"]}}
```

| Field | Meaning |
|---|---|
| `mode` | `local`: 127.0.0.1 only · `lan`: + HTTPS on the home network · `remote`: + HTTPS on your VPN address |
| `remote.bind` | `auto` asks Tailscale for this computer's VPN address; or give the address (e.g. a WireGuard `10.8.0.1`) |
| `remote.networks` | address ranges allowed in remote mode besides private ones (default: Tailscale's) |
| `remote.names` | extra host names to accept and to put in the certificate (e.g. a MagicDNS name) |

`ui.lan.enabled` (older switch) is kept in step with `access.mode`.

## Shipped rules (`base.json`) — change them in your profile

| Key | What it controls |
|---|---|
| `engine` | `mode: read-only`, `network: offline`, `ai.apple_builtin`, `ai.ollama {enabled, url, model}`, `ai.cloud: never` (cannot be changed) |
| `catalogue` | `encrypted` (macOS disk image), `vault_size` (`20g` maximum, grows as needed), `text: full`, `max_text_chars` (400,000 per file), `spotlight_also`, `history`, `allow_unencrypted_disk` (Windows/Linux override, reported by doctor) |
| `plugins` | each reader `{enabled, …}`: `metadata`, `hash` (`full_hash_max_mb`), `text` (`pdf_ocr_if_no_text`, `pdf_ocr_pages`), `archive` (`max_entries`), `image_meta`, `ocr` (`max_mb`, `languages`), `image_classify` (`min_confidence`, `max_labels`), `faces` (suggest-only), `transcribe` (see below), `doc_type`, `entities`, `topics`, `near_duplicate_photos` (`max_distance`, `max_hamming`, `burst_seconds`, `max_distance_screens`, `min_pixels`) |
| `plugins.transcribe` | `languages` tried on a 60-second sample, `max_minutes`, `auto_doc_types`, `auto_entity_types`, `auto_exts`, `skip_under`, `workers`, `label_from_transcript` (false), `keep_reserved` |
| `kinds` | file extension → kind |
| `text_extract` | which reader handles which extension |
| `skip_dirs`, `package_exts`, `project_markers`, `skip` | what is never catalogued, kept as one unit, or treated as a code project; `skip.code_folder {min_files, share}` |
| `technical_kinds` | kinds that never need an owner (Code, Font, Installer) |
| `sensitive` | `name_regex` of sensitive files; `read_content`, `allow_icloud`, `allow_ai` (all false) |
| `doc_types` | document-type rules — see below |
| `presets` | `layouts` (path templates), `naming` (file-name templates), `month_format` |
| `ui` | `port` (8765), `idle_hours` (4), `lan.port` (8766) |
| `insights` | `expected_docs` per owner type, `annual_docs`, `year_start_month` (tax year), `annual_due_month`, `annual_lookback_years`, `expiry_doc_types`, `expiry_patterns`, `date_order` (`dmy`/`mdy`), `expiry_warn_days`, `series` (regular-document detection), `recommendations` (thresholds), `folder_consensus` and `mining` (learning), `auto_report` |
| `sorter` | `sources`, `owner_confidence {auto, ask}`, `learn_from_library`, `learn_min_share`, `learn_min_files`, `topic_fallback`, `media_kinds`, `media_doc_types`, `media_template`, `archive_template`, `default_group_labels`, `local_only_folder`, `remove_empty_folders`, `max_errors`, `year_level_min`, `misc_names`, `archive_after_years`, `archive_kinds` |
| `search` | `doc_type_words` (word → document-type filter), `synonyms` (word → extra words) |
| `person_sections` | sections of a person's page: `title`, document-type `tags`, `topics` |

### Document types (`doc_types`)

```json
{"name": "Passport", "tags": ["id", "holder", "dob", "important", "paper"],
 "any_text": ["passport no", "passport number"], "all_text": [], "any_name": ["passport"],
 "kinds": ["PDF", "Photo"], "max_text_chars": 2500}
```

| Field | Meaning |
|---|---|
| `any_name` | patterns in the file name (any one) |
| `all_text` / `any_text` | patterns that must all / at least one appear in the text (regular expressions, case-insensitive) |
| `kinds` | only for these file kinds |
| `max_text_chars` | only documents with at most this much text (an ID card is short; a book mentioning “passport” is not) |
| `tags` | `id` identity document · `holder` named holder owns it · `dob` name above the date of birth · `important` Triage first · `paper` counted as an important paper · `money` `tax` `insurance` `medical` `education` `work` `property` `vehicle` `travel` person-page sections |

## File renaming

Only when **Rename files** is ticked in the Sorter, and only for files that run moves. Every new name is shown in the
plan first; undoing the run restores the old name with the old place.

| Setting | Default | Meaning |
|---|---|---|
| `naming_preset` | `original` | the style for documents; `original` never renames |
| `presets.naming` | `dated` `{date}_{entity_tag}_{title}` · `id-docs` `{entity_tag}_{doc_type}_{title}` · `invoice` `{date}_{vendor}_Invoice_{amount}_{title}` · `screenshot` `{date}_{time}_Screenshot` · `original` `{original}` | the templates (edit or add your own in your profile) |
| `presets.naming_by_type` | `tag:id` → `id-docs`, `Invoice`/`Receipt` → `invoice`, `Screenshot` → `screenshot` | document types with their own style (`tag:<tag>` = every type with that tag) |
| `presets.naming_kinds` | PDF, Document, Spreadsheet, Presentation, Email | kinds renamed with the chosen style; any file with a detected document type is renamed too |

Tokens: `{date}` (document date, YYYY-MM-DD) · `{time}` (HH.MM of the file) · `{entity_tag}` (owner: a person's first
name, an organisation's name, or the owner's `tag`) · `{doc_type}` · `{vendor}` (owner, when it is an office,
organisation or client) · `{amount}` (the last “Total / Grand total / Amount due” amount in the text) · `{original}`
(the old name) · `{title}` — what the old name says beyond what the new name adds back.

Rules: **a new name never loses what the old one said.** `{title}` is the old name with only the parts the style writes
again taken out (a leading date when the style has `{date}`, the owner when it has `{entity_tag}`, the type's words when
it has `{doc_type}` or writes them itself); the rest keeps its own spelling and separators. Empty tokens are left out
with their separator. Never renamed: sensitive files, and photos, videos and audio that are not documents. Names
already in the style are left alone. Two files that would get the same name: the later one gets its old name added;
an existing file is never overwritten. Characters that are not allowed in file names become `-`; names stay ≤ 60
characters for the `{title}` part.

| Old name | Style | New name |
|---|---|---|
| `B 412 sale deed Scan.pdf` (owner Alex, 2023-07-30) | dated | `2023-07-30_Alex_B 412 sale deed Scan.pdf` |
| `2024-07-19_PASSPORT-Dad1.pdf` (passport of Sam) | id-docs | `Sam_Passport_2024-07-19_Dad1.pdf` |
| `invoice 77.pdf` (Acme Traders, total 1,499.00) | invoice | `2024-03-05_Acme Traders_Invoice_1499.00_77.pdf` |
| `IMG_2041.jpg` (holiday photo) | — | unchanged |

## Country packs (`profiles/regions/<name>.json`)

| Key | Meaning |
|---|---|
| `name`, `_about` | shown in the wizard |
| `doc_types_insert` | `[{"before": "Passport", "type": {…}}]` — new document types, placed before a named one |
| `doc_types_replace` | `{"Passport": {…}}` — a country version of a built-in type |
| `set` | any other settings, merged into the shipped rules (tax year, expected documents, search words, speech languages) |
| `topic_keywords_extra` | `{"Finance/Bank": ["local bank names"]}` — added to topics that do not have the word yet |

## Data folder layout

```
<data>/
  profiles/machine.json          your profile
  profiles/versions/             previous versions
  vault.sparsebundle  vault/     macOS: encrypted catalogue image and its mount point
  catalogue/                     Windows/Linux with UO_DATA: the catalogue (else %LOCALAPPDATA% / $XDG_DATA_HOME)
  logs/                          scan logs, sorter and move logs (*.jsonl, needed for undo), status files
  agent/                         agent: hub address, token (private), the hub's pinned certificate
  exports/                       packages from `uo package`
```
