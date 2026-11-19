# HTTP API reference

Every page in Universal Organiser is a thin browser front-end over this JSON API, served by `uo serve`
(`engine/server.py`). This document lists every endpoint. The API is meant for the bundled pages, for agents
(other computers), and for your own scripts on the same computer. It is **not** a public internet API.

- [Servers and addresses](#servers-and-addresses)
- [Request rules (all endpoints)](#request-rules-all-endpoints)
- [Authentication and roles](#authentication-and-roles)
- [Errors](#errors)
- [Background jobs](#background-jobs)
- [Endpoints](#endpoints): [sign-in](#sign-in-and-session) · [pages](#pages) · [search and files](#search-and-files) ·
  [overview and home](#overview-home-and-people) · [analytics](#analytics) · [labels and plan](#labels-and-the-action-plan) ·
  [triage](#triage) · [sorter](#sorter) · [smart folders](#smart-folders) · [reading and transcripts](#reading-and-transcripts) ·
  [Finder tags](#finder-tags-macos) · [projects](#projects) · [clean-up](#clean-up-review) · [insights](#insights) ·
  [settings and rules](#settings-and-rules) · [accounts](#accounts) · [phones and access](#phones-tablets-and-access) ·
  [set-up and doctor](#set-up-wizard-and-requirements) · [hub](#hub-admin) · [agent protocol](#agent-protocol)
- [Example: a script on the same computer](#example-a-script-on-the-same-computer)

## Servers and addresses

| Server | Address | When |
|---|---|---|
| Local | `http://127.0.0.1:8765` (`ui.port`) | always while `uo serve` runs |
| Network (HTTPS) | `https://<home-network-ip>:8766` and `https://<hostname>.local:8766` (`ui.lan.port`) | access mode `lan` or `remote` |
| VPN (HTTPS) | `https://<vpn-ip>:8766` | access mode `remote` and a VPN address found |

The network servers use a private certificate authority made on the computer (`<catalogue>/tls/ca.crt`), TLS 1.2+.
They answer only private addresses (plus the configured VPN ranges in `remote` mode), and only for their own host names.

## Request rules (all endpoints)

| Rule | Detail |
|---|---|
| Host / Origin | Local server: `Host` must be `127.0.0.1` or `localhost`, and `Origin` (if sent) too. Network server: `Host` must be one of its own names; `Origin` must match. Otherwise **403**. |
| `X-FE: 1` header | Required on every `/api/…` call (except `GET /api/thumb`). Without it: **403**. This stops other web sites in your browser from calling the API. |
| Body | JSON (`Content-Type: application/json`), at most 4 MB. Agent calls: up to 32 MB, may be gzip (`Content-Encoding: gzip`). |
| Locking | Requests are handled one at a time against the catalogue (a lock); long work runs as a [background job](#background-jobs). |
| Responses | JSON, `Cache-Control: no-store`. HTML pages carry a strict Content-Security-Policy, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`. |

## Authentication and roles

- **Session cookie** `fe_s` (HttpOnly, SameSite=Strict, `Secure` on HTTPS). Idle sessions end after `ui.idle_hours`
  (default 4).
- **Device cookie** `fe_d` (network server only): identifies an approved phone/tablet. A session from the network is
  valid only while its device is approved for that same user.
- **Roles.** `admin` sees and changes everything. `member` sees only files whose owner is in their *scope*, never
  sensitive files, and may not change anything (except their own password).
- **Agents** do not use cookies: they send `Authorization: Bearer <token>` (see [agent protocol](#agent-protocol)).

In the tables: **Who** = `public` (no sign-in), `any` (any signed-in account), `admin`, `local` (also refused from a
phone/tablet: must be done on the computer itself), `agent` (bearer token).

## Errors

```json
{"error": "Plain-language reason"}
```

| Status | Meaning |
|---|---|
| 400 | bad input, or a refusal with a reason (e.g. “Already there.”) |
| 401 | not signed in (API) — pages redirect to `/login` instead; agent token missing or revoked |
| 403 | not allowed: wrong host/origin, missing `X-FE`, member account, or must be done on the computer itself |
| 404 | unknown path or object |
| 413 | agent body too large |
| 500 | `internal error: <ExceptionType>` (details are never sent to the page) |

## Background jobs

Long operations return `{"ok": true}` at once and run in the background; poll their status endpoint. A job object has
`phase` (`running`, `done`, `ready`, `failed`, `applied`), progress `done`/`total` where known, `step` (text), and
`error` when failed. Only one job of each kind runs at a time (a second start returns 400).

| Job | Start | Status |
|---|---|---|
| Scan | `POST /api/scan/start` | `GET /api/scan/status` |
| Rules re-run | `POST /api/rules/start` → `POST /api/rules/apply` | `GET /api/rules/status` |
| Sorter run | `POST /api/sort/run` | `GET /api/sort/status` |
| Transcript | `POST /api/transcribe` | `GET /api/transcribe/status` |
| Read all pages / download & read | `POST /api/deepread` | `GET /api/deepread/status` |
| Finder tags | `POST /api/tags/apply`, `/api/tags/remove` | `GET /api/tags` (`job`) |
| Projects check / stop sync | `POST /api/projects/refresh`, `/api/projects/stop` | `GET /api/projects` (`job`) |
| Clean-up analyse / hold | `POST /api/cleanup/analyse`, `/api/cleanup/hold` | `GET /api/cleanup` (`job`) |

---

## Endpoints

### Sign-in and session

| Method | Path | Who | Body / query | Returns |
|---|---|---|---|---|
| GET | `/api/login-state` | public | `?t=<setup token>` | `has_users`, `remote` (on network server), `setup_ok` (token valid and no account yet), `profile` |
| POST | `/api/setup` | public, local, once | `t`, `username`, `display`, `password`, `password2` | creates the first **admin** and signs in (sets `fe_s`). Only while no account exists, only with the one-time token printed by `uo serve`. |
| POST | `/api/login` | public | `username`, `password` | `{"ok": true}` + cookie. From a phone/tablet: first time **403** `{"pending": true, "code": "123456"}` until the device is approved; **403** if the device was removed. |
| POST | `/api/logout` | any | – | clears the session |
| POST | `/api/password` | any | `old`, `new` (≥ 8 characters) | changes your own password |
| GET | `/api/me` | any | – | `user`, `display`, `role`, `scope`, `options` (owners, topics, types for menus), `profile` |

### Pages

HTML pages (no `X-FE` needed). Not signed in → redirect to `/login`. Admin-only pages redirect members to `/` or `/home`.

| Path | Who | Page |
|---|---|---|
| `/login` | public | sign in / create the first admin |
| `/device-setup`, `/ca.crt` | public, network on | phone set-up instructions; the certificate authority to install |
| `/home` | any | Overview (admins of a new install are sent to `/welcome` first) |
| `/` | any | Files (search) |
| `/browse`, `/person?name=…`, `/analytics`, `/actions` | any | folder browser, person page, analytics, action list |
| `/triage`, `/sorter`, `/insights`, `/projects`, `/cleanup`, `/settings`, `/welcome`, `/computers` | admin | |

### Search and files

| Method | Path | Who | Query / body | Returns |
|---|---|---|---|---|
| GET | `/api/search` | any | `q` words · filters `kind`, `entity` (owner), `doc_type`, `topic`, `year`, `entity_type`, `under` (folder prefix), `planned=1` · `dups=1` (only duplicate copies) · `review=owner\|suggested\|sensitive\|mine` · `rec=<recommendation id>` · `smart=<smart folder id>` · `literal=1` (exact words, no plain-language parsing) · `ignore=a,b` (drop understood chips) · `limit` (≤ 200, default 50) · `offset` | `total`, `results[]` (id, path, name, kind, unit, size, date, year, owner `entity`, `entity_conf`, `doc_type`, `topic`, `suggestions`, flags `cloud_only`/`sensitive`/`protected`, `hash`…), `understood` (`chips`, `also`) |
| GET | `/api/facets` | any | – | counts per kind, owner, type, topic, year, owner type |
| GET | `/api/file?id=` | any (in scope) | – | full record with labels, confidence and reason, `text` (excerpt), `transcript`, `archive` (contents), `copies` (identical files), `decision` (your own labels) |
| GET | `/api/thumb?id=` | any (in scope) | – | JPEG preview of a photo/PDF (no `X-FE`; never sensitive or cloud-only files) |
| POST | `/api/reveal` | any, local | `id` | shows the file in Finder / Explorer / file manager |
| POST | `/api/reveal-folder` | any, local | `path` (inside a scanned folder) | shows the folder |

Plain-language search understands owner names and aliases (and “my”/“mine”), document-type words, topics, years and
financial years, forgives typos and sounds-alike spellings, and widens words with the synonyms in the profile.

### Overview, home and people

| Method | Path | Who | Query / body | Returns |
|---|---|---|---|---|
| GET | `/api/ov/node` | any | `lens=folder\|person\|topic\|year\|type`, `key=<JSON list path>` (≤ 40) | one level of the map: children with size, counts, health colour, new-since-last-visit, trend |
| GET | `/api/ov/strip` | any | – | the health strip (owned %, sensitive in cloud, damaged, new since last visit, change vs last month) |
| GET | `/api/ov/stamp` | any | – | a small value that changes when the catalogue changes (pages poll it every 20 s) |
| POST | `/api/ov/visit` | any | – | records this visit; returns `since` (the previous visit) |
| GET | `/api/home` | any | – | top actions (admin), people, recent changes (admin), smart folders, totals, tag job, platform |
| GET | `/api/person?name=` | any (in scope) | – | that person's IDs present/missing, alerts, sections, topics, years, recent files, suggestions count; 404 if not visible to you |

### Analytics

| Method | Path | Who | Query | Returns |
|---|---|---|---|---|
| GET | `/api/analytics/overview` | any | – | totals, by type, owned share, cloud-only, duplicates |
| GET | `/api/analytics/tree` | any | `path` (folder), `raw=1` (real hierarchy, used by Browse) | treemap children with sizes and colours |
| GET | `/api/analytics/dups` | any | – | duplicate groups with a suggested keeper |
| GET | `/api/analytics/overlap` | any | – | folders that largely contain the same files |
| GET | `/api/analytics/similar` | any | – | near-identical photo groups (macOS), cached 10 minutes |

### Labels and the action plan

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| POST | `/api/label` | admin | `set: {entity?, topic?, doc_type?}` and either `ids: [..]` or `query: {q, filters…, dups, review, rec}`; `preview: true` to only count | preview: `n`, `summary`; apply: `change` id (undoable). Labels only — never moves a file. Your decision wins over the rules on every rescan. |
| GET | `/api/plan` | admin | – | files planned for `trash` or `archive` |
| POST | `/api/plan/add` | admin | `action: trash\|archive`, `ids` or `query`, `preview` | adds to the plan (projects, apps and protected folders are skipped). Nothing happens to files until a Sorter run. |
| POST | `/api/plan/remove` | admin | `ids` or `all: true` | removes from the plan |
| POST | `/api/undo` | admin | `id` (change id) | undoes a label change or rules run |
| GET | `/api/changes` | admin | – | history of label changes with undo state |

### Triage

| Method | Path | Who | Query | Returns |
|---|---|---|---|---|
| GET | `/api/triage` | admin | `where=tosort` (the library's “To Sort” folder; any other value = everywhere), `under=<folder>`, `limit` (≤ 30) | `items` (most valuable first: important documents, suggested owner, papers, archives/media, other) with holder names read from the text, `remaining`, `buckets`, `where` |

Triage answers use `/api/label`; “skip 30 days” uses `/api/insights/dismiss` with key `triage:<id>`.

### Sorter

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/sort/options` | admin | – | default sources, other choices, plan size, library, layout, local-only folder, `naming` style and its `naming_template` |
| POST | `/api/sort/plan` | admin | `sources: [folders]` (inside scanned folders, not protected), `include_plan`, `tidy`, `archive_old`, `rename` (give moved documents a new name in the chosen style) | the plan: `moves[]` (id, src, dst, why, size, `needs_ok`, owner, topic, kind, confidence, `rename` = new file name or null), totals. Kept on the server for 30 minutes. |
| POST | `/api/sort/run` | admin | `ids: [..]` (ticked moves) | starts the run. **Paths come only from the server's own plan**, never from the request. Each move is re-checked (size, date, protection, cloud, sensitive). |
| GET | `/api/sort/status` | admin | – | job progress and result |
| GET | `/api/sort/runs` | admin | – | past runs with counts and undo state |
| POST | `/api/sort/undo` | admin | `run` | moves every file of that run back |
| POST | `/api/move` | admin | `ids` and/or `folder`/`folders`, `dest` (inside the library), `preview` | drag-and-drop move from Browse: preview, then one logged, undoable run. Refuses projects, protected folders and other computers' files. |

### Smart folders

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/smart` | any | – | built-in and saved smart folders with live counts |
| POST | `/api/smart/save` | admin | `name`, `def: {q?, filters?, doc_types?, topics?, year?, recent_days?, no_owner?}` | `id` |
| POST | `/api/smart/delete` | admin | `id` | – |

### Reading and transcripts

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| POST | `/api/deepread` | admin | `id` | reads every page of a scanned PDF, or (macOS) downloads an iCloud-only file first and reads it. Never sensitive files. |
| GET | `/api/deepread/status` | admin | – | job |
| POST | `/api/transcribe` | admin | `id`, `language` (e.g. `en-GB`, optional: forces a new transcript in that language; downloads it from Apple if needed) | job start (macOS 26+) |
| GET | `/api/transcribe/status` | admin | – | job |
| GET | `/api/languages` | admin | – | supported / installed / reserved speech languages |

### Finder tags (macOS)

| Method | Path | Who | Returns |
|---|---|---|---|
| GET | `/api/tags` | admin | how many files would be tagged, already tagged, sample tags, job |
| POST | `/api/tags/apply` | admin | writes owner/topic as Finder tags (keeps your own tags; never sensitive or iCloud-only files) |
| POST | `/api/tags/remove` | admin | removes only the tags it added |

### Projects

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/projects` | admin | – | catalogued projects with status, cloud files, git state, last change, job |
| POST | `/api/projects/status` | admin | `path`, `status: Active\|Paused\|Completed\|Experiment\|""` | sets the working status (also a Finder tag on macOS) |
| POST | `/api/projects/refresh` | admin, local | – | deep check of every project (job) |
| POST | `/api/projects/stop` | admin, local | `paths: [..]` | macOS: stop iCloud syncing each project (downloads, verifies, checks it is not in use, then sets Apple's exclude attribute; rolls back if iCloud does not confirm) |
| POST | `/api/projects/resume` | admin, local | `path` | syncs it again |

### Clean-up review

Compares other versions of projects with the kept version in the projects folder (`projects_home`).

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/cleanup` | admin | – | last analysis (families of versions: safe / probably / different), held versions, job |
| POST | `/api/cleanup/analyse` | admin, local | – | job |
| POST | `/api/cleanup/hold` | admin, local | `paths: [..]` (≤ 500) | renames versions into the holding folder (nothing deleted) |
| POST | `/api/cleanup/restore` | admin, local | `path` | puts a held version back exactly where it was |

### Insights

| Method | Path | Who | Query / body | Returns |
|---|---|---|---|---|
| GET | `/api/insights/summary` | admin | – | counts of alerts, important alerts, proposals, recommendations |
| GET | `/api/insights/alerts` | admin | – | expiring documents, missing expected/yearly documents, overdue regular documents |
| GET | `/api/insights/recs` | admin | – | recommendations (sensitive in cloud, identical copies, large old files, installers, old downloads, old screenshots, damaged files, suggested owners, lifecycle) with counts and sizes; use `rec=<id>` in search |
| GET | `/api/insights/proposals` | admin | – | rules learnt from your decisions (folder → owner; name word → owner/topic) |
| POST | `/api/insights/proposal` | admin | `key`, `preview` | applies a proposal (labels, or a new versioned profile rule followed by a rules preview) |
| POST | `/api/insights/dismiss` | admin | `key`, `days` (empty = forever) | hides an alert or recommendation |
| POST | `/api/insights/undismiss` | admin | `key` | shows it again |
| GET | `/api/insights/reports` | admin | – | current month and saved monthly reports |
| GET | `/api/insights/report` | admin | `month=YYYY-MM`, `fresh=1` | the monthly pattern report |

### Settings and rules

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/settings` | admin | – | editable values (owners, topics, types → topics, layout, folders, plug-ins, local AI) and what is locked |
| POST | `/api/settings/preview` | admin | the edited values | `errors[]` or `changes[]` (a readable diff) |
| POST | `/api/settings/save` | admin | the edited values | saves your profile; `kept` = name of the previous version. Validation refuses: missing folders, removing protection, cloud AI, bad patterns. |
| GET | `/api/settings/versions` | admin | – | saved profile versions |
| POST | `/api/settings/restore` | admin | `name` | restores a version (the current one is kept too) |
| POST | `/api/rules/start` | admin | – | re-applies the rules to the stored text (job; read-only) |
| GET | `/api/rules/status` | admin | – | progress; when `ready`, the counts and a sample of what would change |
| POST | `/api/rules/apply` | admin | – | applies the previewed result as one undoable change |

### Accounts

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/users` | admin | – | accounts (no password data) |
| POST | `/api/users/add` | admin | `username`, `display`, `role: admin\|member`, `scope: [owner names]`, `password` | – |
| POST | `/api/users/update` | admin | `username`, any of `display`, `role`, `scope`, `password` | the last admin cannot be demoted |
| POST | `/api/users/remove` | admin | `username` (not yourself; not the last admin) | – |

### Phones, tablets and access

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/lan` | admin | – | network server state: `enabled`, `url`, `fingerprint`, `ip`, `error` |
| POST | `/api/lan` | admin, local | `enabled` | switches home Wi-Fi access on/off (kept in the profile) |
| GET | `/api/devices` | admin | – | phones/tablets with code, status, last seen |
| POST | `/api/devices/set` | admin (approve: local) | `id`, `status: approved\|revoked\|removed` | – |
| POST | `/api/access` | admin, local | `mode: local\|lan\|remote` | saves the mode and restarts the network servers; `error` if e.g. no VPN address |

### Set-up wizard and requirements

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/welcome` | admin | – | presets, country packs, detected folders (home/cloud/network/removable, with suggestions), current answers, owner types, requirement checks, version, `setup_done` |
| POST | `/api/welcome/save` | admin, local | `preset`, `region`, `roots[]`, `library`, `you`, `people: [{name, type}]`, `role: standalone\|hub\|agent`, `access` | writes your profile (previous one kept; aliases and other settings preserved) and restarts network servers as needed |
| POST | `/api/scan/start` | admin, local | – | starts a scan (job) |
| GET | `/api/scan/status` | admin | – | `job` and the scanner's progress (`phase` listing/analysing/done, `done`, `total`, `found`) |
| GET | `/api/doctor` | admin | – | requirement checks: `id`, `title`, `status: ok\|missing\|warn\|info`, `need: required\|recommended\|optional`, `detail`, `fix`, `cmd`, `fixable` |
| POST | `/api/doctor/fix` | admin, local | `id` | builds the macOS reader. Fixes that need a password (package installs) are never run from the page: the error tells you the command. |

### Who used it (admin)

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/activity` | admin | – | `accounts[]` (`username`, `display`, `role`, `last_login`, `signins_30d`, `failed_30d`, `pages_30d`, `last_device`, `last_ip`), `events[]` (latest 300: `t`, `username`, `event: signin\|signin-failed\|signout\|page`, `detail`, `ip`, `device`), `changes[]`, `runs[]`, `keep_days` (90), `unknown_failed_30d` |

Pages opened are recorded at most once per person, page and device every 10 minutes. Entries older than 90 days are
removed. The device is “this computer”, an approved phone's or tablet's label, or the browser's kind.

### Updates (admin)

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/update` | admin | – | `check` (on/off), `info` (`current`, `latest`, `newer`, `url`, `notes`, `checked`, `error`, `git`) from the last check — never waits for the network; a due check (once a day) starts in the background — and `job` (`phase: running\|current\|restarting\|restart\|failed`, `log[]`, `error`) |
| POST | `/api/update/check` | admin | – | checks GitHub now: `info` |
| POST | `/api/update/install` | admin, local | – | starts the update job (checksum-verified download, the release's own installer). On macOS/Linux the server then restarts itself with the new program; on Windows `phase` becomes `restart` (start it again from the Start menu). |

Every page also receives `window.UO_I18N` (`lang`, `dict`, `languages`): the language comes from the `uo_lang` cookie,
else `ui.language`, else the browser's `Accept-Language`, else English.

### Hub (admin)

| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/hub` | admin | – | `enabled`, `machines[]` (id, name, os, version, created, last_seen, last_sync, files, ip), `access`, `url`, `vpn_url`, `fingerprint`, `running`, `hostname`, `port`, `error` |
| POST | `/api/hub/enable` | admin, local | `enabled` | turns the hub on/off (on also switches access to `lan` if it was `local`) |
| POST | `/api/hub/code` | admin | – | `code` (`ABCD-EFGH`, single use, 15 minutes), `expires` |
| POST | `/api/hub/remove` | admin | `id` | deletes that computer's token and every record it sent; `removed` count |

---

### Agent protocol

How another computer sends its catalogue to the hub. Implemented by `uo agent` (`engine/agent.py`) and
`engine/hub.py`. All calls are `POST` with `X-FE: 1`, JSON (gzip allowed), to the hub's HTTPS address. The hub must
have `hub.enabled` (else **403**).

1. **Trust.** The agent downloads `/ca.crt` without trusting it, shows its SHA-256 fingerprint, and continues only if
   it matches the one on the hub's Computers page (or `--fingerprint`). From then on it trusts **only** that CA (pinned)
   with normal host-name checking.
2. **Pair** — `POST /api/agent/pair` `{"code": "ABCD-EFGH", "name": "Study PC", "os": "Windows", "version": "1.0.0"}`
   → `{"machine": "<id>", "name": "Study PC", "token": "<secret>"}`. The code works once; names are 1–40 letters,
   digits, space, dot, dash, underscore, unique per hub. The hub stores only the token's SHA-256.
3. **Sync** — each with `Authorization: Bearer <token>` (missing/revoked → **401**):
   - `POST /api/agent/begin` `{}` → `{"sync": <hub time>}`
   - `POST /api/agent/push` `{"sync": t, "records": [ … ≤ 2000 … ]}` → `{"stored": n}`. A record is a catalogue row:
     `path` (as on the agent), `name`, `ext`, `kind`, `unit`, `size`, `mtime`, `birth`, `cloud_only`, `sensitive`,
     `hash`, `date`, `date_source`, `year`, owner fields (`entity`, `entity_type`, `entity_conf`, `entity_why`,
     `suggestions`), `doc_type`, `doc_conf`, `topic`, `lifecycle`, `title`, `pages`, `snippet`, `tags`, `extra`,
     `inner_count`, `errors`, `scanned_at`, and `text` (≤ 200,000 characters; always empty for sensitive files).
     Unknown fields are ignored. The first sync sends everything; later ones only rows scanned since the last sync.
   - `POST /api/agent/end` `{"sync": t, "paths": [every current path]}` → `{"files": n, "removed": n}`. Records of
     that computer not in the list are deleted on the hub.
4. **On the hub** the records are stored as `uo://<computer name>/<path>`, marked protected. They are searchable,
   viewable and labelable, but never moved, tagged, read, transcribed or removed by a local scan.

`GET /api/agent/…` returns `{"hub": "<hostname>", "version": "…"}` (a liveness check).

## Example: a script on the same computer

```python
import json, urllib.request, http.cookiejar
base = "http://127.0.0.1:8765"
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(path, body=None):
    req = urllib.request.Request(base + path, headers={"X-FE": "1", "Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode())
    return json.loads(op.open(req).read())

call("/api/login", {"username": "admin", "password": "…"})
for f in call("/api/search?q=insurance%202024&limit=20")["results"]:
    print(f["date"], f["entity"], f["doc_type"], f["path"])
```

Scripts on other computers should not call the API; use an agent, or open the page on a phone/tablet instead.
