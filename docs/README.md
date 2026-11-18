# Universal Organiser documentation

| Document | For | What is in it |
|---|---|---|
| [User manual](manual.md) | everyone | install, set-up wizard, every page, phones and tablets, several computers, away from home, privacy, undo, troubleshooting |
| [Features](features.md) | everyone | everything it does, by area, and which systems support it |
| [Administrator guide](admin-guide.md) | whoever looks after it | backups, restore and moving computers, accounts, devices, hub operations, updates, logs, uninstall |
| [Command-line reference](cli.md) | admins, power users | every `uo` command and option |
| [Configuration reference](configuration.md) | admins, power users | how profiles are built, every setting, owners, topics, document types, country packs, data folder |
| [HTTP API reference](api.md) | developers | every endpoint, rules, roles, errors, background jobs, the agent protocol |
| [Architecture](architecture.md) | developers | modules, data model, scan pipeline, safety rules, tests |
| [Security](../SECURITY.md) | everyone | how data is protected; reporting problems |
| [Contributing](../CONTRIBUTING.md) | developers | rules for changes; adding a country pack |
| [Changelog](../CHANGELOG.md) | everyone | what changed in each version |

## Words used in these documents

| Word | Meaning |
|---|---|
| **Catalogue** | the encrypted database of what is known about your files (never the files themselves) |
| **Profile** | your settings (`profiles/machine.json` in the data folder) on top of the shipped rules |
| **Preset** | a ready-made starting profile (Just me, Family, Small office, Student, Custom) |
| **Country pack** | a file adding a country's documents, tax year and languages |
| **Owner** | the person or organisation a file belongs to (`entity` in the API) |
| **Library** | the folder where the Sorter files things |
| **To Sort** | the library folder for things not yet sorted |
| **Hub** | the computer that holds the shared catalogue for the home |
| **Agent** | another computer that sends its catalogue to the hub |
| **Member** | a read-only account limited to some owners |
| **Sensitive file** | keys, password exports, recovery codes…: never read, never moved to cloud folders, never shown to members |
| **Protected** | folders that are catalogued but never changed; projects are always protected from sorting |
