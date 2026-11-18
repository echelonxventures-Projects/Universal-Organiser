# Changelog

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
