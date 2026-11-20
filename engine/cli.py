"""Universal Organiser command line  (uo on macOS/Linux, uo.cmd on Windows)

Set up
  uo doctor [--fix] [--yes]   check what this computer needs; --fix offers to install/build what is missing
  uo init --preset family --region india --folder ~/Documents --folder ~/Desktop [--role hub|agent] [--access lan]
                              write your profile without the browser wizard (uo serve shows the wizard instead)
  uo serve [--lan] [--no-browser]   open the page (first run: create the admin account, then the set-up wizard)
  uo autostart on|off         start the page (hub) or the agent automatically when you log in
  uo update [--check]         get the newest release (checksum-verified; your profile, catalogue and logs are not touched);
                              --check only says whether there is one
  uo update --token [TOKEN]   save a GitHub token for a private repository (asked for when left out); --forget-token
  uo package [--feed FOLDER [--notes FILE]]
                              zip of the program only, to copy to a computer without internet; --feed: an update
                              source in FOLDER (shared folder, USB stick, web space) for other copies to update from
  uo version

Catalogue
  uo scan [--full]   read-only catalogue of every file in your folders (incremental)
  uo status | stats | search WORDS | close
  uo rules [--apply] | insights | report [YYYY-MM] | similar [--compute] | read-all | index
  uo transcribe [--all] | languages [install xx-YY]
  uo user list | user passwd NAME

Several computers (one search for all of them)
  uo hub code | hub list | hub remove NAME      on the hub: make a pairing code, list or remove paired computers
  uo agent pair HUB-ADDRESS CODE [--name N] [--fingerprint FP] [--yes]
  uo agent sync [--full] | agent run [--every MINUTES] | agent status | agent forget | agent updates on|off
"""
import os, sys, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.config import Config, DATA  # noqa: E402
from engine import platforms  # noqa: E402
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to a narrow code page
except AttributeError:
    pass
from engine.catalogue import Catalogue  # noqa: E402


def log_to(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a", encoding="utf-8")

    def log(msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True); f.write(line + "\n"); f.flush()
    return log


def fmt(n):
    n = n or 0
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def _arg(a, flag, default=None, many=False):
    vals = [a[k + 1] for k, x in enumerate(a[:-1]) if x == flag]
    return vals if many else (vals[-1] if vals else default)


def package(a=()):
    """Zip of the program files only (no profile, catalogue, logs or keys), for a computer without internet; with
    --feed FOLDER, an update source in that folder (latest.json + zip + SHA256SUMS) for  updates.feed."""
    from engine import updates
    from engine.setup import VERSION
    feed = _arg(list(a), "--feed")
    if feed:
        notes = ""
        nf = _arg(list(a), "--notes")
        if nf:
            with open(nf, encoding="utf-8") as f:
                notes = f.read()
        z, digest = updates.write_feed(feed, notes)
        print(f"Update source written to {os.path.dirname(z)}: latest.json, {os.path.basename(z)}, SHA256SUMS ({digest[:12]}…)\n"
              f"  Point other copies at it: Settings → Updates → Where updates come from, or profile  updates.feed")
        return
    out_dir = os.path.join(DATA, "exports"); os.makedirs(out_dir, exist_ok=True)
    out = updates.build_zip(os.path.join(out_dir, f"universal-organiser-{VERSION}.zip"))
    print(f"Program package: {out}\n  Contains no profile, catalogue, logs or keys. On the other computer unzip it and run the installer in install/.")


def update(a=()):
    from engine import updates, setup as SU
    try:
        cfg = Config()
    except Exception:
        cfg = None  # no profile yet: defaults
    if "--token" in a or "--forget-token" in a:
        if "--forget-token" in a:
            print(updates.set_token(cfg, "")); return
        import getpass
        tok = _arg(list(a), "--token") or os.environ.get("UO_NEW_TOKEN") or getpass.getpass("GitHub token (input hidden): ")
        try:
            print(updates.set_token(cfg, tok))
        except ValueError as e:
            raise SystemExit(str(e))
        return
    if "--check" in a:
        u = updates.check(cfg, force=True)
        if u.get("error"):
            print(f"Universal Organiser {u['current']}: could not check ({u['error']}).")
        elif u["newer"]:
            print(f"Version {u['latest']} is available (you have {u['current']}): {u['url']}\n  Update with:  uo update")
        else:
            print(f"Universal Organiser {u['current']} is the newest version.")
        print(f"  source: {u['source']}" + ("; GitHub token saved" if updates.token() else ""))
        return
    if updates.install(cfg) and platforms.SYSTEM == "macos" and os.path.exists(SU.HELPER_SRC) and not SU._helper_current():
        try:
            SU.build_helper()
        except Exception as e:
            print("macOS reader not rebuilt:", e)


def doctor(cfg, a):
    from engine import setup as SU
    if "--build-helper" in a:
        SU.build_helper(); return
    text, rows = SU.report(cfg)
    print(text)
    if "--fix" not in a:
        return
    for c in rows:
        if c["status"] == "missing" and (c.get("cmd") or c.get("fn")):
            what = " ".join(c["cmd"]) if c.get("cmd") else "build the macOS reader from source"
            if "--yes" in a or input(f"\nFix “{c['title']}”: {what}? [y/N] ").strip().lower() in ("y", "yes"):
                try:
                    SU.fix(c)
                except Exception as e:
                    print("  not fixed:", e)
    print("\n" + SU.report(cfg)[0])


def init(a):
    from engine import setup as SU
    ans = {"preset": _arg(a, "--preset", "personal"), "region": _arg(a, "--region", "none"), "role": _arg(a, "--role", "standalone"),
           "access": _arg(a, "--access"), "roots": _arg(a, "--folder", many=True) or [c["path"] for c in SU.detect_folders() if c["suggested"]],
           "library": _arg(a, "--library"), "you": _arg(a, "--name"), "profile_name": _arg(a, "--profile")}
    if SU.has_profile() and "--force" not in a:
        raise SystemExit(f"You already have a profile ({SU.PROFILE}). Change it in Settings, or add --force to answer again (the old one is kept).")
    try:
        m = SU.init_profile(ans, "uo init")
    except ValueError as e:
        raise SystemExit(str(e))
    print(f"Profile written: {SU.PROFILE}\n  preset {m['preset']}, region {m['region']}, role {m['role']}, access {m['access']['mode']}")
    print("  folders: " + ", ".join(m["roots"]))
    print("Next:  uo scan   then   uo serve")


def autostart(a):
    from engine import service
    on = len(a) > 1 and a[1] == "on"
    if len(a) < 2 or a[1] not in ("on", "off"):
        print(service.status()); return
    print(service.enable() if on else service.disable())


def agent_cmd(cfg, a):
    from engine import agent as AG
    sub = a[1] if len(a) > 1 else "status"
    if sub == "pair":
        if len(a) < 4:
            raise SystemExit("usage: uo agent pair HUB-ADDRESS CODE [--name N] [--fingerprint FP] [--yes]")
        AG.pair(a[2], a[3], _arg(a, "--name"), _arg(a, "--fingerprint"), "--yes" in a)
        return True
    if sub == "status":
        print(AG.status()); return True
    if sub == "forget":
        print(AG.forget()); return True
    if sub == "updates":
        if len(a) < 3 or a[2] not in ("on", "off"):
            raise SystemExit("usage: uo agent updates on|off")
        print(AG.set_auto_update(a[2] == "on")); return True
    return False


def main():
    a = sys.argv[1:] or ["help"]
    cmd = a[0]
    if cmd in ("help", "-h", "--help"):
        print(__doc__); return
    if cmd in ("version", "--version"):
        from engine.setup import VERSION
        print(f"Universal Organiser {VERSION} ({platforms.SYSTEM}, Python {sys.version.split()[0]})\n  program: {ROOT}\n  data:    {DATA}"); return
    if cmd == "init":
        return init(a)
    if cmd == "package":
        return package(a)
    if cmd == "update":
        return update(a)
    if cmd == "autostart":
        return autostart(a)
    cfg = Config()
    if cmd == "doctor":
        return doctor(cfg, a)
    if cmd == "agent" and agent_cmd(cfg, a):
        return
    if cmd == "scan" and not os.path.exists(cfg.path):
        raise SystemExit("No profile yet. Run  uo serve  and finish the set-up wizard (or  uo init).")
    if cmd == "status":
        p = os.path.join(DATA, "logs/scan-status.json")
        if not os.path.exists(p):
            print("no scan has run yet"); return
        s = json.load(open(p)); el = time.time() - s.get("started", s["t"])
        idle = time.time() - s["t"]
        if s["phase"] == "analysing" and idle > 600:
            print(f"no progress for {idle/60:.0f} min at {s['done']:,}/{s['total']:,}: the scan looks stuck "
                  "(see the newest log in logs/)"); return
        if s["phase"] == "analysing" and s.get("done"):
            rate = s["done"] / max(el, 1); left = (s["total"] - s["done"]) / max(rate, 1e-6)
            print(f"analysing {s['done']:,}/{s['total']:,} ({100*s['done']/max(s['total'],1):.0f}%), errors {s['errors']}, "
                  f"about {left/60:.0f} min left")
        else:
            print(json.dumps(s))
        return
    if cmd == "export-engine":  # older name
        return package()
    if cmd == "close":
        platforms.close_store(); print("catalogue locked" if platforms.SYSTEM == "macos" else "nothing to lock: the disk's own encryption protects it"); return
    folder = platforms.open_store(cfg, create=(cmd in ("scan", "serve")))
    cat = Catalogue(folder)
    if cmd == "scan":
        from engine.scan import scan
        log = log_to(os.path.join(DATA, "logs", time.strftime("scan-%Y%m%d-%H%M%S.log")))
        log(f"profile: {cfg.get('profile')} | mode: {cfg['engine']['mode']} | roots: {len(cfg.roots)}")
        scan(cfg, cat, full="--full" in a, log=log)
        from engine import insights
        insights.auto(cfg, cat, log)
        if cfg.plugin("near_duplicate_photos").get("enabled") and cfg.platform == "macos":
            from engine import similar
            similar.compute(cfg, cat, log)
        if cfg.platform == "macos":
            from engine import deepread as DR
            DR.read_all_pages(cfg, cat, DR.candidates(cfg, cat), log)
        if cfg.plugin("transcribe").get("enabled") and cfg.platform == "macos":
            from engine import transcribe as T
            T.run(cfg, cat, T.candidates(cfg, cat), log)
        try:
            from engine import projindex
            d = projindex.write(cfg, cat)
            if d: log(f"projects index rewritten: {len(d['projects'])} projects")
        except Exception as e:
            log(f"projects index not rewritten: {type(e).__name__}: {e}")
        from engine import agent as AG
        if AG.paired():
            try:
                AG.sync(cfg, cat, log=log)
            except SystemExit as e:
                log(f"not sent to the hub: {e}")
    elif cmd == "index":
        from engine import projindex
        d = projindex.write(cfg, cat)
        print(f"{len(d['projects'])} projects indexed in {d['home']}" if d else "no projects folder")
    elif cmd == "stats":
        q = lambda s, *p: cat.db.execute(s, p).fetchall()
        tot = q("SELECT count(*), sum(size) FROM files")[0]
        print(f"{tot[0]:,} records, {fmt(tot[1])}")
        for title, col in (("By kind", "kind"), ("By owner", "entity"), ("By document type", "doc_type"), ("By topic", "topic")):
            print("\n" + title)
            for r in q(f"SELECT {col}, count(*), sum(size) FROM files WHERE {col} IS NOT NULL GROUP BY {col} ORDER BY 2 DESC LIMIT 25"):
                print(f"  {r[1]:>7,}  {fmt(r[2]):>9}  {r[0]}")
        d = q("SELECT count(*), sum(size) FROM (SELECT hash, size FROM files f WHERE hash IS NOT NULL AND hash IN "
              "(SELECT hash FROM files WHERE hash IS NOT NULL GROUP BY hash HAVING count(*)>1) "
              "AND id NOT IN (SELECT min(id) FROM files WHERE hash IS NOT NULL GROUP BY hash))")[0]
        print(f"\nExtra duplicate copies: {d[0] or 0:,} ({fmt(d[1])})")
        for lbl, w in (("Sensitive (content not read)", "sensitive=1"), ("iCloud only (content not read)", "cloud_only=1"),
                       ("Needs owner (has a topic, no owner)", "entity IS NULL AND topic IS NOT NULL"),
                       ("Owner suggestions to review", "entity IS NULL AND suggestions IS NOT NULL"), ("With errors", "errors IS NOT NULL")):
            print(f"{lbl}: {q(f'SELECT count(*) FROM files WHERE {w}')[0][0]:,}")
    elif cmd == "search":
        from engine.server import search
        for r in search(cat, " ".join(a[1:]), limit=25)["results"]:
            print(f"{r['date'] or '':10}  {(r['entity'] or '-')[:22]:22}  {(r['doc_type'] or r['kind'] or '')[:22]:22}  {r['path']}")
    elif cmd == "user":
        from engine.auth import Auth
        import getpass
        au = Auth(cat)
        if len(a) >= 3 and a[1] == "passwd":
            pw = getpass.getpass(f"New password for {a[2]}: ")
            if pw != getpass.getpass("Again: "):
                print("The two passwords differ."); return
            au.update(a[2], pw=pw); print("Password changed.")
        else:
            for u in au.list():
                print(f"{u['username']:16} {u['role']:7} {u['display']:24} sees: {'everything' if u['role'] == 'admin' else ', '.join(u['scope']) or 'nothing'}")
            if not au.has_users():
                print("No accounts yet: run 'uo serve' and open the link it prints.")
    elif cmd == "rules":
        from engine import reclassify
        res = reclassify.compute(cfg, cat)
        c = res["counts"]
        print(f"{res['files']:,} files would change: owner {c['entity']:,}, document type {c['doc_type']:,}, topic {c['topic']:,}")
        for s_ in res["sample"][:15]:
            print("  " + s_["path"].replace(os.path.expanduser("~"), "~"))
            for k, o, n in s_["changes"]:
                print(f"      {k}: {o or 'none'} -> {n or 'none'}")
        if "--apply" in a and res["files"]:
            print("applied; change id", reclassify.apply(cat, res, "cli"), "(undo from Settings > History)")
    elif cmd == "insights":
        from engine import insights as I
        print("ALERTS")
        for x in I.alerts(cfg, cat):
            if not x["dismissed"]:
                print(f"  [{x['level']}] {x['title']}")
        print("\nRECOMMENDATIONS")
        for x in I.recommendations(cfg, cat):
            if not x["dismissed"]:
                print(f"  {x['n']:>6,}  {fmt(x['size']):>9}  {x['title']}")
        print("\nLEARNED PROPOSALS (approve on the Insights page)")
        for x in I.proposals(cfg, cat):
            print(f"  {x['title']}\n      {x['evidence']}")
    elif cmd == "report":
        from engine import insights as I
        r = I.report(cfg, cat, a[1] if len(a) > 1 else None)
        print(f"{r['month']}{' (so far)' if r['partial'] else ''}: {r['files']:,} files, {fmt(r['bytes'])} "
              f"(previous month {r['prev_files']:,}, 12-month average {r['avg_files']:.0f})")
        for n in r["notes"]:
            print("  • " + n)
        for title, k in (("Type", "by_kind"), ("Owner", "by_owner"), ("Topic", "by_topic")):
            print(f"  {title}: " + ", ".join(f"{x[0]} {x[1]}" for x in r[k][:6]))
    elif cmd == "similar":
        from engine import similar
        if "--compute" in a:
            log = log_to(os.path.join(DATA, "logs", time.strftime("similar-%Y%m%d-%H%M%S.log")))
            similar.compute(cfg, cat, log)
        r = similar.groups(cfg, cat)
        print(f"{r['photos']:,} photos fingerprinted ({r['pending']:,} still to do), {r['candidates']:,} candidate pairs, "
              f"{len(r['groups']):,} groups of similar photos, {fmt(sum(g['save'] for g in r['groups']))} if only the best of each is kept")
        for g in r["groups"][:10]:
            print(f"  {g['n']} photos, closest {g['closest']}, keep {os.path.basename(g['items'][0]['path'])}")
    elif cmd == "transcribe":
        from engine import transcribe as T
        log = log_to(os.path.join(DATA, "logs", time.strftime("transcribe-%Y%m%d-%H%M%S.log")))
        T.run(cfg, cat, T.candidates(cfg, cat, everything="--all" in a), log)
        st = T.stats(cat)
        log(f"transcripts: {st['files']} files, {st['with_text'] or 0} with speech, {st['hours']:.1f} h of audio, {st['words']:,} words, {st['errors'] or 0} notes")
    elif cmd == "languages":
        from engine import transcribe as T
        if len(a) >= 3 and a[1] == "install":
            print(T.install_language(cfg, a[2]))
        L = T.languages()
        inst = set(L["installed"])
        print(f"{len(inst)} of {len(L['supported'])} speech languages installed; reserved {L['reserved']} (max {L['max_reserved']})")
        print("not installed:", " ".join(sorted(set(L["supported"]) - inst)) or "none")
        print("tried automatically:", ", ".join(cfg.plugin("transcribe").get("languages", [])))
    elif cmd == "read-all":
        from engine import deepread as DR
        log = log_to(os.path.join(DATA, "logs", time.strftime("readall-%Y%m%d-%H%M%S.log")))
        rows = DR.candidates(cfg, cat); log(f"scanned PDFs with unread pages: {len(rows)}")
        log(f"done: {DR.read_all_pages(cfg, cat, rows, log)} files")
    elif cmd == "serve":
        from engine.server import serve
        serve(cfg, cat, lan="--lan" in a, browser="--no-browser" not in a)
    elif cmd == "hub":
        from engine.hub import Hub
        h, sub = Hub(cat), (a[1] if len(a) > 1 else "list")
        if sub == "code":
            if not (cfg.get("hub") or {}).get("enabled"):
                print("Note: this computer is not a hub yet. Turn it on in the Computers page, or run  uo init --role hub --force.")
            c = h.new_code("cli")
            print(f"Pairing code: {c['code']}  (valid 15 minutes, works once)")
        elif sub == "remove" and len(a) > 2:
            m = next((x for x in h.list() if x["name"].lower() == a[2].lower()), None)
            print(f"Removed {a[2]} and its {h.remove(m['id']):,} records." if m else "No paired computer with that name.")
        else:
            for m in h.list():
                ls = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["last_sync"])) if m["last_sync"] else "never"
                print(f"  {m['name']:24} {m['os'] or '':8} {m['files'] or 0:>9,} files   last sync {ls}")
            if not h.list():
                print("No computers paired yet. Make a code with  uo hub code")
    elif cmd == "agent":
        from engine import agent as AG
        sub = a[1] if len(a) > 1 else "status"
        if sub == "sync":
            AG.sync(cfg, cat, full="--full" in a)
        elif sub == "run":
            from engine.scan import scan
            every = float(_arg(a, "--every", "60"))
            while True:
                log = log_to(os.path.join(DATA, "logs", time.strftime("agent-%Y%m%d.log")))
                try:
                    scan(cfg, cat, log=log)
                    if AG.sync(cfg, cat, log=log).get("updated"):
                        from engine import updates
                        cat.db.close()
                        updates.restart()  # carry on with the new program
                except SystemExit as e:
                    log(f"sync failed: {e}")
                except Exception as e:
                    log(f"run failed: {type(e).__name__}: {e}")
                if every <= 0:
                    break
                time.sleep(every * 60)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
