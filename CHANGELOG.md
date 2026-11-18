# Changelog

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
