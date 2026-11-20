# Universal Organiser — user manual

Version 1.1 · works on macOS, Windows and Linux · phones and tablets use it through the browser

1. [What it does](#1-what-it-does)
2. [Install](#2-install)
3. [First start: the set-up wizard](#3-first-start-the-set-up-wizard)
4. [The pages](#4-the-pages)
5. [Phones and tablets](#5-phones-and-tablets)
6. [Several computers: hub and agents](#6-several-computers-hub-and-agents)
7. [Away from home](#7-away-from-home)
8. [Privacy and safety](#8-privacy-and-safety)
9. [Undo](#9-undo)
10. [Update, start automatically, uninstall](#10-update-start-automatically-uninstall)
11. [Commands](#11-commands)
12. [Troubleshooting](#12-troubleshooting)
13. [Customising: presets, country packs, rules](#13-customising-presets-country-packs-rules)

More: [features](features.md) · [administrator guide](admin-guide.md) · [commands](cli.md) · [configuration](configuration.md) · [API](api.md)

---

## 1. What it does

Universal Organiser builds a **catalogue** of the folders you choose: every file's name, size, dates, duplicates, and
the text inside documents (and, on a Mac, inside scans and photos, plus speech in recordings). From that it works out:

- **Owner** — whose document it is. It reads holder fields such as the name on an ID card, “Policy holder”, “Employee
  name”. A name merely mentioned somewhere is only a *suggestion*. It never guesses: unsure files wait for you.
- **Document type** — passport, invoice, payslip, bank statement, certificate… (more with a country pack).
- **Topic** — Finance/Tax, Insurance, Medical, Travel, Work, Education…

You then search in plain words, see where your space goes, find duplicates and near-identical photos, get reminders
(an ID that expires soon, a yearly tax paper that is missing), and sort files into a tidy structure — as a preview you
approve, with undo.

**Your files are never changed** unless you approve a plan, and nothing is ever sent to the internet.

## 2. Install

You need about 2 GB of free space. The installer checks everything else and tells you what is missing.

### macOS (13 or newer)

1. Unzip or clone Universal Organiser anywhere, open **Terminal** in that folder.
2. Run `sh install/install.sh`
3. If asked, allow Apple's *Command Line Tools* to install (needed once to build the macOS reader for scans, photos and
   speech). Then run the installer again.

It installs into `~/Library/Application Support/Universal Organiser` and adds the `uo` command (in `~/.local/bin`).

### Windows (10 or 11)

1. Before unzipping, right-click the zip → *Properties* → tick **Unblock** (otherwise Windows asks “Do you want to
   run this file?” for each script). Unzip, open the folder, double-click **`install\install.cmd`**.
2. If Python is missing, it offers to install it with winget (or get it from python.org — tick *Add to PATH*).
3. **Disk encryption must be on** (the catalogue holds your documents' text): *Settings → Privacy & security →
   Device encryption* (or *BitLocker*). The installer offers to open that page.

It installs into `%LOCALAPPDATA%\Universal Organiser`, adds a **Start menu** entry and the `uo` command.

**PDF text on Windows:** install Poppler (search the web for “poppler windows releases”), unzip it, and add its
`Library\bin` folder to your PATH. `uo doctor` shows whether `pdftotext` is found.

### Linux

1. Unzip or clone, open a terminal in the folder, run `sh install/install.sh`
2. It offers to install Python, PDF text (Poppler) and OpenSSL with your package manager (apt, dnf, pacman, zypper);
   each command is shown and runs only if you say yes.
3. The catalogue must be on an encrypted disk (LUKS) or encrypted home folder.

It installs into `~/.local/share/universal-organiser`.

### A computer without internet

On a computer that has it, run `uo package`. Copy the zip (USB stick), unzip it there and run the installer as above.
The package contains the program only — never your profile, catalogue or logs.

### Phones and tablets

Nothing to install. See [section 5](#5-phones-and-tablets).

### Check a computer

`uo doctor` lists every requirement as ✓ ok, ✗ required and missing, or – recommended. `uo doctor --fix` offers to fix
what it can (it asks before each step).

## 3. First start: the set-up wizard

`uo serve` (or the Start menu entry) opens the page in your browser.

1. **Admin account.** The very first time, the terminal shows a one-time link; the page asks for a name and password
   (at least 8 characters). This account can see and change everything.
2. **Check** — what this computer has. Required items must be fixed before you continue; on a Mac you can build the
   reader right there.
3. **Use** — a preset: *Just me*, *Family*, *Small office*, *Student* or *Custom*. It sets the kinds of owners and the
   folder layout. Everything can be changed later.
4. **Country** — adds that country's identity and tax documents, its tax year and speech languages. *International*
   covers what every country has (passport, driving licence, bank, invoices, insurance, medical, travel…).
5. **Folders** — tick the folders to look at. Cloud folders (iCloud Drive, OneDrive, Dropbox, Google Drive), network
   shares and external drives that are connected appear here too. Add any other folder by typing its path. Also choose
   where sorted files go (only used when you run the Sorter).
6. **People** (optional) — your name and the people or organisations whose papers are here.
7. **Computers** — *Just this computer*, *The hub* (collects other computers' catalogues) or *Send to a hub*; and who
   may open the page: *Only this computer*, *Home Wi-Fi*, or *Also away from home* (your own VPN).
8. **Review and save**, then the **first scan** starts. You can use the page while it runs.

Run the wizard again any time from *Settings → Set-up wizard*; your other settings are kept.

## 4. The pages

- **Overview (Home)** — a map of all your files: by folder, person, topic, year or type. Colours show health (red:
  sensitive files in a cloud-synced folder or damaged files; amber: many papers without an owner). Changes since your
  last visit are marked; the page refreshes by itself.
- **Files** — search. Type the way you think: `dad insurance 2023`, `invoices last year`, `passport`. It understands
  owners, document types, topics and years, forgives typos and spelling variants, and shows how it understood you
  (chips you can remove). *Save this search* makes a smart folder. Click a file for details, its text, and actions.
- **Browse** — your real folders as a tree. Drag files or folders onto another folder (or *Cut* / *Paste*): you get a
  preview first, and the move can be undone.
- **Triage** (admin) — files waiting for an owner, most important first. Keys: `1`–`9` owner · `Enter` accept the
  suggestion · `N` no owner · `T` topic · `D` type · `S` skip for 30 days · `Z` undo · `O` show the file. Every few
  answers it proposes a rule learnt from you.
- **Sorter** (admin) — builds a plan to file things where they belong, learning from where your files of the same owner
  and topic already are. Untick anything, then run. Each run is logged and can be undone.
  **Rename files** (shown once you pick a naming style in *Settings → Folders & layout*) also gives the moved
  documents clear names, e.g. `2023-07-30_Alex_B 412 sale deed Scan.pdf`; the plan shows every old → new name,
  and undo restores the old names. Holiday photos, videos and sensitive files keep their names.
- **Projects** (admin) — folders with code (git, package.json…) are kept whole as projects and never sorted. Here you
  can set their status and, on a Mac, stop iCloud from syncing a project folder.
- **Analytics** — space (treemap), duplicates with a suggested keeper, overlapping folders, timelines, similar photos.
  Select or drag to label, or to plan *move to Trash* / *archive* (carried out by the Sorter after preview).
- **Insights** (admin) — alerts (expiring documents, missing yearly papers), recommendations (large old files, old
  downloads, screenshots) and rule proposals learnt from your decisions; nothing is applied without your OK.
- **Person pages** — one page per person: their IDs (present or missing), alerts and documents by section.
- **Computers** (admin) — who may open the page, the hub switch and paired computers ([section 6](#6-several-computers-hub-and-agents)).
- **Settings** (admin) — owners and their name words, topics, document types, folders, readers (OCR, transcripts, local
  AI), accounts, phones and tablets, history with undo. Every save keeps the previous profile; restore it any time.

**Accounts.** *Settings → Accounts* adds family members. A *member* sees only the owners you choose and never sensitive
files, and cannot change anything.

**Who used it.** *Settings → Who used it* (admins only) shows each account's last sign-in and device, every sign-in,
failed attempt, sign-out and page opened in the last 90 days, and beside it every change and sorter run with who made
it. Many failed attempts for one name, or from an address you don't know, is a reason to change that password
(*Settings → Accounts*). It is kept inside the encrypted catalogue and never leaves this computer.

**Language.** The pages come in English and Hindi (हिन्दी). Each phone, tablet or computer picks its own with the
**Language** menu at the top right of the page; *Settings → Plug-ins & AI → Language* sets the default for devices that
have not chosen (normally the browser's own language). Names of your files, people, folders and topics are never
translated. The terminal (`uo …`) stays in English.

**Keyboard and screen readers.** Every page works without a mouse. The first Tab shows *Skip to content*; Tab moves
through links, buttons, fields, rows and tiles, and Enter or Space opens the one in focus. In a dialog, Tab stays inside
it and Escape cancels. In the maps and heat maps (Overview, Analytics) a chart is one Tab stop: arrow keys move to the
neighbouring tile or cell, Home and End to the first and last, Enter opens it, and the tooltip shows for the one in focus. Screen readers (VoiceOver, NVDA, Narrator, TalkBack) hear the page's navigation, the current page,
every field's name and status messages such as “saved”. Pages follow your system's dark mode and reduced-motion
settings, and zoom with the browser (Ctrl/⌘ +). Triage also has its own keys (`1`–`9`, `Enter`, `N`, `T`, `D`, `S`, `Z`, `O`).

## 5. Phones and tablets

1. On the computer: *Computers → Who can open the page → Home Wi-Fi*. The page shows an address such as
   `https://192.168.1.20:8766/device-setup` and a certificate **fingerprint**.
2. On the phone or tablet (same Wi-Fi), open that address. The browser warns once because the certificate was made by
   your computer; that is expected the first time.
3. Check that the fingerprint on the phone matches the one on the computer, then **install the certificate**:
   - *iPhone / iPad:* Settings → *Profile Downloaded* → Install; then Settings → General → About → Certificate Trust
     Settings → turn on “Universal Organiser home certificate authority”.
   - *Android:* Settings → Security → Encryption & credentials → Install a certificate → CA certificate.
4. Sign in. The first time, the phone shows a **6-digit code**; approve it on the computer (*Settings → Accounts →
   Phones & tablets*). Then sign in again.

Phones can search, browse and label; moving files, the Wi-Fi switch and device approval are only possible on the
computer itself. A removed device is signed out at once.

## 6. Several computers: hub and agents

One computer is the **hub**: it holds the shared catalogue and the page everyone uses. Every other computer runs
Universal Organiser as an **agent**: it scans its own files and sends its catalogue to the hub. **Files never move
between computers** — only what the scan learnt (names, sizes, dates, labels, the text it read). Sensitive files are
sent without any text.

**Set up the hub**

1. On the hub: *Computers* → tick **This computer is the hub** (this also turns on Home Wi-Fi).
2. Leave the hub running (`uo autostart on` starts it at every login).

**Add a computer**

1. Install Universal Organiser on it; in the wizard choose **Send to a hub**.
2. On the hub: *Computers → Add a computer*. It shows a pairing code (valid 15 minutes, works once), the command to
   type, and the hub's certificate fingerprint.
3. On the new computer, in a terminal: `uo agent pair https://hub-name.local:8766 ABCD-EFGH`
   (Windows: `uo.cmd agent pair …`). Compare the fingerprint it prints with the hub's, answer `y`.
4. Send its catalogue: `uo agent sync`. From then on every `uo scan` also sends what changed. To keep it up to date by
   itself: `uo agent run --every 60` (scan and send every hour) or `uo autostart on`.

On the hub, files of other computers appear under `uo://<computer name>/…`. They can be searched, opened in details and
labelled, but never moved, tagged or read again there — do that on the computer that has them.

**Remove a computer:** *Computers → Remove* deletes its records and its access. On that computer, `uo agent forget`.

**A computer that cannot run it (a NAS, an old PC):** share its folder on the network, connect the share on the hub
(*Finder → Go → Connect to Server*, *File Explorer → Map network drive*, or your Linux file manager), and add it in
*Settings → Folders & layout*. The hub then scans it directly.

## 7. Away from home

Universal Organiser never opens a port on your router. To use it away from home, use **your own VPN**:

1. Install **Tailscale** (or WireGuard) on the hub and on your phone or laptop, and sign in to both.
2. On the hub: *Computers → Also away from home*. The page then also listens on the VPN address, and accepts only
   the VPN's address ranges (Tailscale's by default; change `access.remote.networks` in the profile for WireGuard).
3. Open the VPN address shown on the Computers page; set the device up as in [section 5](#5-phones-and-tablets).

If no VPN address is found, `uo doctor` and the Computers page say so.

## 8. Privacy and safety

- Nothing is sent to the internet. No account, no telemetry. Optional local AI (Ollama) runs on the same computer.
- The catalogue is encrypted: macOS uses an AES-256 disk image with its key in your Keychain; Windows and Linux
  require an encrypted disk.
- Read-only until you approve. Projects and protected folders are never moved. Sensitive files (keys, password
  exports, recovery codes…) are never read for text, never moved into cloud-synced folders, never shown to members.
- Your profile, catalogue and logs live in the data folder (`uo version` shows where) — never inside the program files,
  so an update cannot change them.

## 9. Undo

- **Labels** (owner, topic, type, rules re-runs): *Settings → History → Undo*.
- **Moves** (Sorter, Browse, Analytics plans): *Sorter → Runs → Undo* moves every file of that run back.
- **Settings:** *Settings → History* (profile versions) restores an earlier profile.
- Files you sent to the Trash stay there until you empty it yourself.

## 10. Update, start automatically, uninstall

- **Update:** when a new version is out, admins see **Version … is ready** on Home: press **Update now** (it checks the
  download, replaces only program files and restarts the page), or run `uo update`. *Settings → Plug-ins & AI → Updates*
  turns the daily check off, can install updates by themselves, and sets where they come from. Computers paired with a
  hub update from the hub at their next sync.
- **Start automatically:** `uo autostart on` (macOS LaunchAgent, Linux systemd user service, Windows Task Scheduler);
  `uo autostart off` to stop. A hub or standalone computer starts the page; an agent starts `uo agent run`.
- **Uninstall:** `uo autostart off`, `uo close`, then delete the install folder (`uo version` shows it). On macOS also
  delete the “UniversalOrganiser-vault” item in Keychain Access. Your own files are not affected.

## 11. Commands

`uo help` lists them all. The main ones:

| Command | What it does |
|---|---|
| `uo doctor [--fix]` | check requirements; offer fixes |
| `uo serve [--no-browser]` | open the page |
| `uo scan [--full]` | update the catalogue |
| `uo search WORDS` | search in the terminal |
| `uo init --preset family --region india --folder ~/Documents` | set up without the browser |
| `uo hub code` / `hub list` / `hub remove NAME` | on the hub |
| `uo agent pair ADDRESS CODE` / `agent sync` / `agent run` / `agent status` / `agent forget` | on other computers |
| `uo autostart on/off` | start at login |
| `uo user list` / `uo user passwd NAME` | accounts (also: reset a forgotten password) |
| `uo package` | program zip for an offline computer |
| `uo version` | version, program folder and data folder |

## 12. Troubleshooting

| Problem | What to do |
|---|---|
| “Port 8765 is in use” | the page is already running: open http://127.0.0.1:8765 |
| Forgot the password | `uo user passwd NAME` in a terminal on the computer |
| Windows/Linux: “this disk is not encrypted” | turn on Device encryption / BitLocker, or use an encrypted disk |
| Text in PDFs missing (Windows/Linux) | install Poppler's `pdftotext`; then `uo scan --full` |
| Mac: scans/photos have no text | `uo doctor --fix` builds the macOS reader |
| Phone shows a certificate warning | install and trust the certificate ([section 5](#5-phones-and-tablets)) |
| Agent: “Could not reach the hub” | is the hub running with Home Wi-Fi on? Same network? Try the IP address instead of `name.local` |
| Agent: fingerprint does not match | do **not** pair; check you typed the hub's address |
| Agent: “not paired (or was removed)” | pair again with a new code |
| A cloud folder hangs the scan | files that live only in the cloud are skipped; download them first if you want them read |
| Logs | in the data folder, `logs/` |

## 13. Customising: presets, country packs, rules

- **Everything in Settings** is stored in your own profile (`profiles/machine.json` in the data folder) and overrides
  the shipped rules (`profiles/base.json`).
- **Presets** (`profiles/presets/*.json`) are starting points the wizard copies from.
- **Country packs** (`profiles/regions/*.json`) add local documents, tax year and languages. To add your country, copy
  `india.json` and follow [CONTRIBUTING.md](../CONTRIBUTING.md#adding-a-country-pack).
- **Document-type tags** decide where a type shows up: `id` (identity documents), `holder` (the named holder owns it),
  `dob` (name printed above the date of birth), `important` (Triage first), `paper` (important paper), and the sections
  of a person's page (`money`, `tax`, `insurance`, `medical`, `education`, `work`, `property`, `vehicle`, `travel`).
