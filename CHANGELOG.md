# Changelog

## 1.5.0

- **Signed updates.** Every release is signed by the publisher (`SHA256SUMS.sig`); the program checks the signature
  against the key built into it and refuses anything else, so a forged or altered release is never installed, even from
  the right address. Own update folders are signed with `uo package --feed … --sign KEY`.
- **Works without disk encryption (Windows Home).** On a Windows or Linux disk without encryption the program no longer
  refuses to start: it runs in **names-only** mode, keeping file names, folders and labels but never the documents' text,
  titles, snippets or transcripts. Search finds names; turn encryption on and run `uo scan --full` for full search.
  Anyone can choose this everywhere with `catalogue.text = "names"`.
- **Problem report.** *Settings → Plug-ins & AI → Help → Make a problem report* (or `uo report`): version, system,
  health checks and recent errors, with paths, file names, names, addresses and long numbers replaced. You see it first
  and send it yourself (Download, Copy, or Email support when `support.email` is set).

## 1.4.0

- **Updates, complete.** Three sources: GitHub (public, or private with a GitHub token saved in *Settings → Updates* or
  with `uo update --token`; the token stays in its own file readable only by you and is only ever sent to GitHub's API),
  a folder or `https://` address made with `uo package --feed`, and — for computers paired with a hub — the hub itself:
  they compare versions at each sync and install the hub's program over their pinned connection, so they need no
  internet access and no token. The Computers page shows each one's version.
- **Install updates by themselves** (optional, off by default): once nobody has used the page for 30 minutes and nothing
  is running. The update check also runs hourly in the background, not only when Home is opened.
- **Restart after an update on Windows too** (it used to ask you to start it again). Updates are listed in *Who used it*.
- Releases also carry `latest.json`; *Settings → Updates* shows the source, the last check and its result, with
  **Check now**.

## 1.3.0

- **Who used it.** *Settings → Who used it* (admins only): each account's last sign-in and device, and every sign-in,
  failed attempt (also for unknown user names), sign-out and page opened in the last 90 days, beside the label changes
  and sorter runs each person made. Stored in the encrypted catalogue; never leaves the computer. In English and Hindi.

## 1.2.0

- **Hindi (हिन्दी).** Every page, button, message and alert, including the server's own messages, is available in Hindi.
  Each phone, tablet or computer picks its language with the new **Language** menu at the top of the page; the default
  for a computer is set in *Settings → Plug-ins & AI → Language* (normally the browser's language). Names of files,
  people, folders and topics are never translated. More languages are one JSON file each (see CONTRIBUTING.md);
  `tools/i18n_extract.py` lists every text and checks the translations in CI.
- **Update check.** Once a day the page asks GitHub for the newest release (program name and version only; can be
  turned off in Settings). Admins see *Version … is ready* on Home with **Update now**: the download is checked against
  the release's SHA-256, the release's own installer replaces only the program files, and the page restarts by itself.
  `uo update` does the same from a terminal; `uo update --check` only looks. Python from python.org on macOS works
  without its separate certificate step.
- **Releases.** A tag `vX.Y.Z` publishes a GitHub release with the program zip, `SHA256SUMS` and the changelog notes.
  The Windows installer is signed when a code-signing certificate is added to the repository secrets.
- **Fewer warnings when installing from a download.** The installers clear Windows' “from the internet” mark and macOS's
  quarantine from the files they install. The manual explains unblocking the zip on Windows before unzipping.
- **Charts by keyboard.** The maps (Overview, Analytics) and heat maps (files per month, owners × topics) are one Tab stop
  each; arrow keys move to the neighbouring tile or cell, Home/End to the first/last, Enter opens, and the tooltip shows
  for the focused one. Heat-map cells are named with their numbers for screen readers.
- Form fields inside tables are now named after their column (“Type – Alex”) for screen readers.

## 1.1.1

- **Installers are tested on every change.** CI installs from scratch on clean macOS, Windows (through `install.cmd`) and
  Linux machines, runs the installed program (doctor, scan, search, page), installs again as an update and checks the
  profile and catalogue were kept. On macOS it also checks the reader (OCR, photos, transcripts) was built.
- **Accessibility.** Every page now has a “Skip to content” link, a labelled navigation with the current page marked,
  visible keyboard focus, keyboard access (Enter/Space) to rows, tiles, smart folders and filters, dialogs that take focus,
  keep Tab inside and close with Escape, names for every field and symbol-only button, and status and error messages that
  screen readers announce. Reduced motion is respected. Colour contrast meets WCAG AA in light and dark themes.
  `tools/a11y_check.py` runs in CI.
- Windows installer with `-Yes` no longer opens the Settings page for disk encryption (it still says how to turn it on).
- No more “favicon not found” error in the browser console.

## 1.1.0 — 2026-11-18

- **File renaming in the Sorter.** Tick “Rename files” to give moved documents clear names in the style chosen in
  Settings (`dated`, `id-docs`, `invoice`, `screenshot`); identity documents, invoices/receipts and screenshots get
  their own style automatically. Names are built around the old name so nothing it said is lost, shown in the plan
  before anything moves, never collide or overwrite, and undo restores them. Sensitive files, photos, videos and audio
  keep their names. Templates now include `{title}` (the meaningful rest of the old name).

## 1.0.1 — 2026-11-18

- **Security:** checking projects, stopping and resuming their iCloud sync now require an admin account (a member
  account could start them before). Test added for every action a member must not do.
- Sorter accepts Windows paths written with backslashes.
- Documentation: features, administrator guide, command-line, configuration and HTTP API references (including the
  agent protocol), architecture.

## 1.0.0 — 2026-11-18

First public-ready version (formerly an in-house tool called FileEngine).

- **Install anywhere:** installers for macOS, Linux and Windows that recognise the system, check requirements
  (`uo doctor`) and offer fixes; macOS reader built from source; Start-menu shortcut on Windows; `uo autostart`.
- **Set-up wizard** in the browser: preset, country pack, folders (home, cloud, network, external drives), people,
  this computer's role and who may open the page.
- **Presets:** Just me, Family, Small office, Student, Custom.
- **Country packs:** country-specific documents moved out of the core. First pack: India.
- **Several computers:** hub and agents (`uo agent pair/sync/run`, Computers page). Records of other computers are
  searchable on the hub and never acted on there.
- **Access:** this computer only / home Wi-Fi / also away from home through your own VPN (Tailscale, WireGuard).
- **Program and data kept apart** (`UO_DATA`), so updates never touch your profile, catalogue or logs. Earlier
  FileEngine installs keep working, including their Keychain key and catalogue folders.
- **Privacy guard:** `tools/privacy_check.py` and git hooks block personal data from the repository.
- Tests for profiles, wizard, hub/agent sync and packaging; CI on macOS, Windows and Linux.
