# Features

Everything Universal Organiser does, by area. ✓ = every system; 🍎 = macOS only (uses Apple's on-device frameworks).
Where a feature changes files, it is always **preview → your approval → logged run → undo**.

## Catalogue (reading your files)

| Feature | Notes |
|---|---|
| Read-only scan of chosen folders ✓ | incremental: only new or changed files are read again; removed files leave the catalogue |
| Units ✓ | every file is a record; a code project (git, package.json, … 35 markers) is **one** project record; app bundles and libraries are one package; protected folders are one protected record |
| Skips noise ✓ | hidden folders, app libraries (`*.localized`), `node_modules`, virtual environments, logs, lock and temp files, “mostly code” folders outside the library |
| File kinds ✓ | photo, video, audio, PDF, document, spreadsheet, presentation, web page, archive, installer, code, font, e-mail |
| Text inside files ✓ | Office/OpenDocument, text, CSV, JSON, web pages, RTF; PDF (🍎 built in; Windows/Linux with Poppler) |
| Text in scans and photos 🍎 | Apple Vision OCR; first pages during the scan, every page on request |
| Photo labels and EXIF 🍎/✓ | Vision labels 🍎; EXIF date/camera ✓ |
| Inside archives ✓ | lists zip/rar/7z/tar contents without extracting |
| Speech transcripts 🍎 | on-device Apple SpeechTranscriber (macOS 26+); auto for meetings/screen recordings/voice files; 45 languages, best language chosen from a sample; searchable |
| Duplicates ✓ | content hash; identical copies with a suggested keeper |
| Near-identical photos 🍎 | difference hash + Vision feature print; bursts, edits, resized copies; suggest only |
| Cloud-only files ✓ | iCloud and OneDrive placeholders are recorded but never downloaded by a scan; “Download & read” on request 🍎 |
| Sensitive files ✓ | keys, password exports, recovery codes, `.env`… (pattern in the profile): recorded, never read for text |
| Dates ✓ | from content, EXIF, file name or file system, with the source noted |

## Understanding (labels)

| Feature | Notes |
|---|---|
| Owner detection ✓ | holder fields (“Name”, “Policy holder”, “Employee name”, name above the date of birth on ID cards…); file and folder names; aliases and kinship words; never guesses — unsure means a suggestion |
| Document types ✓ | 22 built-in (passport, driving licence, bank statement, payslip, invoice, receipt, insurance, certificates, tickets, medical, contracts, property…) + country packs (India: PAN, Aadhaar, Voter ID, Form 16/ITR, 80G/12A/FCRA) |
| Topics ✓ | 14 built-in (IDs & Legal, Finance/Tax/Bank/Invoices, Insurance, Property, Vehicle, Travel, Medical, Work…, Education) + preset extras; keyword rules per topic |
| Your decisions win ✓ | labels you set are kept across rescans and moves (by path, then by content hash) |
| Rules re-run ✓ | re-apply edited rules to the stored text; preview of every change; one undoable change |
| Learning ✓ | proposes rules from your decisions: “this folder is always X's”, “this word means topic Y” |

## Finding

| Feature | Notes |
|---|---|
| Plain-language search ✓ | `dad insurance 2023`, `my passport`, `invoices FY 2024-25`: owners, types, topics, years and financial years become filters |
| Forgiving ✓ | typos, spelling variants, sounds-alike (romanised Hindi and Indian English), synonyms you can edit |
| Shows how it understood you ✓ | removable chips; “exact words” switch |
| Filters and facets ✓ | kind, owner, type, topic, year, owner type, folder, duplicates, review queues |
| Smart folders ✓ | 9 built in (identity documents, tax & salary, insurance, medical, property & rent, education, travel this year, added in 30 days, important papers without an owner) + save any search |
| Person pages ✓ | IDs present/missing, alerts, documents by section, topics, years |
| Terminal search ✓ | `uo search WORDS` |
| One search across computers ✓ | hub + agents |

## Seeing

| Feature | Notes |
|---|---|
| Overview ✓ | zoomable map by folder, person, topic, year or type; health colours; new since your last visit; trends vs last month; auto-refresh |
| Analytics ✓ | space treemap, duplicates, overlapping folders, timeline, owner × topic heat map, similar photos 🍎 |
| Insights ✓ | alerts: documents expiring (read from the text), missing expected documents per person, missing yearly documents (tax year per country), overdue regular documents (learnt rhythm) |
| Recommendations ✓ | sensitive files in cloud folders, identical copies, large old files, installers, old downloads, old screenshots, unreadable files, suggested owners, lifecycle (temporary/testing files past their time) |
| Monthly report ✓ | files added, by type/owner/topic, compared with last month and the 12-month average; saved automatically |

## Organising (changes files — always previewed and undoable)

| Feature | Notes |
|---|---|
| Triage ✓ | one file at a time, keyboard (`1`–`9`, `Enter`, `N`, `T`, `D`, `S`, `Z`, `O`), important papers first, learns rules |
| Sorter ✓ | moves files to where files of the same owner and topic already are, else the layout preset; media by year/month; local-only folder for sensitive files; needs-OK for medium confidence |
| Tidy ✓ | library standard Group/Person/Topic (+Year when a topic has more than 30 files); merges Misc/Others/General; misfiled files |
| Archive ✓ | old code, installers and archives from To Sort into Archive/<year> |
| Browse ✓ | real folder tree; drag-and-drop or cut/paste with preview |
| Action plan ✓ | mark files for Trash or Archive from any view; carried out by the Sorter |
| Undo ✓ | every run, every label change, every settings save |
| Finder tags 🍎 | owner and topic as Finder tags (Spotlight finds them); removable; never on sensitive files |
| Safety ✓ | re-checks every file before moving; never moves projects, protected folders, other computers' files; never moves sensitive files into cloud folders; removes only folders it emptied |

## Projects

| Feature | Notes |
|---|---|
| Project detection ✓ | a projects folder (`projects_home`): each folder inside is one project, even if made of parts |
| Projects index ✓ | `INDEX.md` and an HTML index, rewritten after every scan, with a “rebuildable” size column |
| Working status ✓ | Active / Paused / Completed / Experiment (+ Finder tag 🍎) |
| Stop iCloud sync 🍎 | per project, without moving or renaming it (Apple's official exclude attribute), with download, verification, in-use check and rollback |
| Clean-up review ✓ | other versions of a kept project grouped safe / probably / different (file overlap and git commits); hold in a folder; put back |

## People and access

| Feature | Notes |
|---|---|
| Accounts ✓ | admin and member; member sees only chosen owners, never sensitive files, cannot change anything |
| Phones and tablets ✓ | HTTPS on home Wi-Fi, private certificate, fingerprint check, each device approved with a 6-digit code, removable at once |
| Away from home ✓ | through your own VPN (Tailscale/WireGuard); never a router port |
| Hub and agents ✓ | pairing code, pinned certificate, token; agents send catalogues only; remove a computer = delete its records |
| Network folders ✓ | a NAS or old PC's share scanned directly by the hub |

## Install, set-up and operation

| Feature | Notes |
|---|---|
| Installers ✓ | macOS/Linux shell, Windows PowerShell (+ Start-menu entry); recognise the system; update in place keeping your data |
| Requirements check ✓ | `uo doctor`: Python, FTS5, profile, encryption, macOS reader, speech, PDF text, OpenSSL, VPN, space, folders, local AI, port; `--fix` |
| Set-up wizard ✓ | presets, country, folders (home/cloud/network/external detected), people, role, access; first scan with progress |
| Presets ✓ | Just me, Family, Small office, Student, Custom |
| Country packs ✓ | add documents, tax year, search words, topic words, speech languages; one file per country |
| Settings ✓ | owners, topics, types, folders & layout, plug-ins & AI, accounts, history; validated; versioned |
| Start at login ✓ | `uo autostart on` (launchd / systemd user / Task Scheduler) |
| Offline package ✓ | `uo package` (program only) |
| Local AI (optional) ✓ | Ollama on the same computer; cloud AI is refused |
| Encrypted catalogue ✓ | 🍎 AES-256 disk image + Keychain; Windows BitLocker/Device encryption required; Linux LUKS/encrypted home required |
| Privacy guard (developers) ✓ | blocks personal data, keys and data files from commits |
