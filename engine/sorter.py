"""The sorter: turns catalogue labels (and the action plan) into file moves.

Two steps, always:
  1. build_plan()  - read-only. Works out a destination for each file and why, plus what stays and why.
  2. run()         - moves only the items a person approved. Each move is checked again just before it happens,
                     logged to logs/sort-*.jsonl, and the catalogue is updated. undo() reverses a whole run.

Never moves: projects, apps/packages, protected folders, anything under a protected path, files changed since
the scan, iCloud-only files leaving iCloud (that would force a download), or sensitive files into iCloud."""
import os, re, json, time, calendar, contextlib
from collections import Counter, defaultdict
from .config import DATA as ROOT, HOME, expand
from . import platforms

LOGS = os.path.join(ROOT, "logs")
TRASH = None  # set only by tests; otherwise the platform's Trash


def trash(cfg):
    return TRASH or platforms.trash_dir(cfg)


def _sc(cfg):
    return cfg.get("sorter", {})


def group_label(cfg, key):
    return (cfg.get("group_labels") or {}).get(key) or _sc(cfg).get("default_group_labels", {}).get(key) or key


def _under(p, bases):
    pl = p.lower()
    return any(pl == b.lower() or pl.startswith(b.lower().rstrip("/") + "/") for b in bases)


def _clean(part):
    part = re.sub(r'[\x00-\x1f/:]', "-", str(part)).strip().strip(".")
    return part[:120] or "Misc"


def sources(cfg):
    lib = cfg.library
    out = []
    for s in _sc(cfg).get("sources", []):
        s = s.replace("{LIBRARY}", lib)
        s = re.sub(r"\{(\w+)\}", lambda m: group_label(cfg, m[1]) if m[1] in (cfg.get("group_labels") or {}) or m[1] in
                   _sc(cfg).get("default_group_labels", {}) else m[0], s)
        out.append(expand(s))
    return out


def synced_roots(cfg, cat):
    from .insights import synced_roots as sr
    return sr(cfg, cat)


# ---------------------------------------------------------------- destinations
class Layout:
    def __init__(self, cfg, cat):
        self.cfg, self.cat, self.sc = cfg, cat, _sc(cfg)
        self.lib = cfg.library
        self.ents = {e["name"]: e for e in cfg.get("entities", [])}
        preset = cfg.get("layout_preset") or "classic-numbered"
        self.template = cfg["presets"]["layouts"].get(preset, "{group_label}/{entity}/{topic_top}")
        self.mfmt = cfg["presets"].get("month_format", "{mm}-{MonthName}")
        self.learned = self._learn() if self.sc.get("learn_from_library", True) else {}

    def _learn(self):
        """Where do files of each (owner, topic) already live in the library? Year folders are generalised."""
        seen = defaultdict(Counter)
        pre = self.lib + "/"
        # folders arranged by date, or holding unsorted / duplicate files, say nothing about where an owner's documents belong
        skip = [self.lib + "/" + group_label(self.cfg, g) + "/" for g in ("Unsorted", "Media", "Duplicates", "Testing")]
        for path, e, t, y in self.cat.db.execute("SELECT path, entity, topic, year FROM files WHERE unit='file' AND entity IS NOT NULL "
                                                 "AND substr(path,1,?)=?", (len(pre), pre)):
            if any(path.startswith(x) for x in skip):
                continue
            d = os.path.dirname(path)
            parts = d.split("/")
            if y and parts[-1] == y:
                d = "/".join(parts[:-1]) + "/{year}"
            elif re.fullmatch(r"\d{2}-[A-Za-z]+", parts[-1]) and y and len(parts) > 1 and parts[-2] == y:
                d = "/".join(parts[:-2]) + "/{year}/{month}"
            seen[(e, t)][d] += 1
        out = {}
        for k, c in seen.items():
            d, n = c.most_common(1)[0]
            tot = sum(c.values())
            if n >= self.sc.get("learn_min_files", 2) and n / tot >= self.sc.get("learn_min_share", 0.6):
                out[k] = (d, n, tot)
        return out

    def _month(self, date):
        if not date:
            return "Undated"
        m = int(date[5:7])
        return self.mfmt.replace("{mm}", f"{m:02d}").replace("{MonthName}", calendar.month_name[m])

    def fill(self, tpl, r):
        e = self.ents.get(r["entity"] or "", {})
        topic = r["topic"] or self.sc.get("topic_fallback", "Misc")
        top = topic.split("/")[-1] if (e.get("type") == "Office" and topic.startswith("Work/")) else topic.split("/")[0]
        vals = {"group_label": group_label(self.cfg, e.get("type", "Unsorted")), "entity": r["entity"] or "Unknown", "entity_type": e.get("type", ""),
                "topic": topic, "topic_top": top, "year": r["year"] or "Undated", "month": self._month(r["date"]), "kind": r["kind"] or "Other",
                "media_folder": r.get("_media") or "Other", "LIBRARY": self.lib}
        out = re.sub(r"\{group:(\w+)\}", lambda m: group_label(self.cfg, m[1]), tpl)
        out = re.sub(r"\{(\w+)\}", lambda m: vals.get(m[1], m[0]), out)
        if out.startswith("/"):  # an absolute place: inside the library (cleaned per folder) or a fixed place like the Trash
            if out.startswith(self.lib + "/"):
                return "/".join([self.lib] + [_clean(p) for p in out[len(self.lib) + 1:].split("/") if p])
            return platforms.norm(os.path.normpath(out))
        return "/".join([self.lib] + [_clean(p) for p in out.split("/") if p])

    def owner_dest(self, r):
        k = (r["entity"], r["topic"])
        if k in self.learned:
            d, n, tot = self.learned[k]
            return self.fill(d, r), f"where your other {r['entity']} · {r['topic'] or 'no topic'} files are ({n} of {tot})"
        return self.fill(self.template, r), f"layout “{self.cfg.get('layout_preset') or 'classic-numbered'}”"

    def media_dest(self, r):
        return self.fill(self.sc.get("media_template", "{group:Media}/{media_folder}/{year}/{month}"), r), "media by date"


def build_plan(cfg, cat, include_medium=False, extra_sources=None, include_plan=True, tidy=False, archive_old=False, rename=False):
    """Read-only. Returns {moves:[...], stays:{reason: n}, sources, warnings}. rename: also give moved documents a clear
    name (naming.py); the new name is part of the plan, so it is seen before anything happens."""
    from . import naming as NM
    sc, L = _sc(cfg), Layout(cfg, cat)
    srcs = sources(cfg) + [s for s in (extra_sources or []) if s]
    auto, ask = set(sc.get("owner_confidence", {}).get("auto", ["high", "you"])), set(sc.get("owner_confidence", {}).get("ask", ["medium"]))
    synced = synced_roots(cfg, cat)
    local_only = expand(sc.get("local_only_folder", "{HOME}/Private (local only)"))
    moves, stays = [], Counter()
    planned = {r[0]: r[1] for r in cat.db.execute("SELECT file_id, action FROM plan")}
    seen = set()
    cols = "id,path,name,kind,unit,size,mtime,date,year,entity,entity_conf,topic,doc_type,title,cloud_only,sensitive,protected"
    taken = defaultdict(set)  # destination folder -> names (lower case) the plan already uses there
    text_of = lambda fid: (cat.db.execute("SELECT body FROM fts WHERE rowid=?", (fid,)).fetchone() or [""])[0]

    def add(r, dest_dir, action, why, needs_ok=False):
        new = NM.new_name(cfg, r, text_of) if rename and action == "file" else None
        dst = os.path.join(dest_dir, new or r["name"])
        if os.path.dirname(r["path"]) == dest_dir:
            stays["already in the right folder"] += 1; return
        if _under(dest_dir, cfg.protect):
            stays["destination is protected"] += 1; return
        if r["sensitive"] and _under(dest_dir, synced):
            dest_dir = os.path.join(local_only, os.path.relpath(dest_dir, cfg.library) if dest_dir.startswith(cfg.library + "/") else "")
            dst = os.path.join(dest_dir, new or r["name"]); why += "; sensitive, so kept out of iCloud"
        if r["cloud_only"] and not _under(dest_dir, synced):
            stays["iCloud-only: would need downloading first"] += 1; return
        if new:  # two files must not get the same name, and an existing file is never overwritten
            if new.lower() in taken[dest_dir] or (os.path.lexists(dst) and dst != r["path"]):
                new = NM.distinct(new, r["name"], taken[dest_dir] | {new.lower()})
                dst = os.path.join(dest_dir, new)
            if new.lower() == r["name"].lower():
                new = None
        taken[dest_dir].add(os.path.basename(dst).lower())
        moves.append({"id": r["id"], "src": r["path"], "dst": dst, "dest_dir": dest_dir, "action": action, "why": why, "size": r["size"] or 0,
                      "needs_ok": needs_ok, "owner": r["entity"], "topic": r["topic"], "kind": r["kind"], "conf": r["entity_conf"],
                      "rename": new})

    # 1) the action plan (trash / archive)
    if include_plan and planned:
        ids = list(planned)
        for i in range(0, len(ids), 900):
            ch = ids[i:i + 900]
            for r in cat.db.execute(f"SELECT {cols} FROM files WHERE id IN ({','.join('?' * len(ch))})", ch):
                r = dict(r); seen.add(r["id"])
                if r["unit"] != "file" or r["protected"] or _under(r["path"], cfg.protect):
                    stays["never moved (project / protected)"] += 1; continue
                if planned[r["id"]] == "trash":
                    if r["cloud_only"]:
                        stays["iCloud-only: delete it in iCloud Drive instead (no download)"] += 1; continue
                    moves.append({"id": r["id"], "src": r["path"], "dst": trash(cfg) + "/" + r["name"], "dest_dir": trash(cfg), "action": "trash",
                                  "why": "in your action plan: Trash", "size": r["size"] or 0, "needs_ok": False, "owner": r["entity"],
                                  "topic": r["topic"], "kind": r["kind"], "conf": r["entity_conf"]})
                else:
                    add(r, L.fill(sc.get("archive_template", "{LIBRARY}/{group:Archive}/{year}"), r), "archive", "in your action plan: Archive")
    # 2) files in the sources
    for s in srcs:
        pre = s.rstrip("/") + "/"
        for r in cat.db.execute(f"SELECT {cols} FROM files WHERE substr(path,1,?)=?", (len(pre), pre)):
            r = dict(r)
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            if r["unit"] != "file" or r["protected"] or _under(r["path"], cfg.protect):
                stays["project / app / protected: never moved"] += 1; continue
            conf = r["entity_conf"] or ""
            if r["entity"] and r["entity"] in L.ents and (conf in auto or conf in ask or conf.startswith("you")):
                d, why = L.owner_dest(r)
                add(r, d, "file", why, needs_ok=conf in ask and not conf.startswith("you"))
                continue
            media = (sc.get("media_doc_types", {}).get(r["doc_type"] or "") or
                     (sc.get("media_kinds", {}).get(r["kind"] or "") if r["doc_type"] not in ("Meeting recording",) else None))
            if media and not r["entity"]:
                r["_media"] = media
                d, why = L.media_dest(r)
                add(r, d, "file", why); continue
            if r["entity"]:
                stays["owner suggested but not certain: confirm it on the search page"] += 1
            elif r["topic"]:
                stays["has a topic but no owner: needs an owner"] += 1
            else:
                stays["no owner, no topic: stays to be sorted"] += 1
    if tidy or archive_old:
        from . import tidy as T
        tm, ts = T.plan(cfg, cat, standard=tidy, misfiled=tidy, archive=archive_old)
        planned_ids = {m["id"] for m in moves}  # only files that already have a move; files the sorter left alone may still be tidied
        moves += [m for m in tm if m["id"] not in planned_ids]
        for k, v in ts.items():
            stays[k] += v
    by_dest = defaultdict(lambda: {"n": 0, "size": 0, "needs_ok": 0})
    for m in moves:
        g = by_dest[(m["action"], m["dest_dir"])]
        g["n"] += 1; g["size"] += m["size"]; g["needs_ok"] += m["needs_ok"]
    groups = [{"action": a, "dest": d, **v} for (a, d), v in sorted(by_dest.items(), key=lambda x: -x[1]["n"])]
    return {"moves": moves, "groups": groups, "stays": dict(stays.most_common()), "sources": srcs, "built_at": time.time(),
            "learned": len(L.learned), "layout": cfg.get("layout_preset")}


# ---------------------------------------------------------------- run / undo
def manual_moves(cfg, cat, ids=None, folder=None, dest=None):
    """Moves asked for by drag and drop in the folder browser. Destination must be inside the library and not protected;
    projects, apps and protected folders are never moved. Returns (moves, refusal reason or None)."""
    from . import platforms
    dest = platforms.norm(dest or "").rstrip("/")  # Windows paths may arrive with backslashes
    folder = platforms.norm(folder) if folder else folder
    if not dest or not _under(dest, [cfg.library]) or _under(dest, cfg.protect):
        return [], "Drop onto a folder inside your library (not a protected folder)."
    rows = []
    if folder:
        folder = folder.rstrip("/")
        if dest == folder or dest.startswith(folder + "/"):
            return [], "A folder cannot go inside itself."
        if _under(folder, cfg.protect) or cat.db.execute("SELECT 1 FROM files WHERE unit!='file' AND substr(path,1,?)=? LIMIT 1",
                                                          (len(folder) + 1, folder + "/")).fetchone():
            return [], "This folder holds a project, an app or a protected folder; move those in Finder yourself."
        for r in cat.db.execute("SELECT id,path,name,size,entity,topic,kind,entity_conf,unit,protected,sensitive FROM files "
                                "WHERE unit='file' AND substr(path,1,?)=?", (len(folder) + 1, folder + "/")):
            rel = os.path.dirname(r["path"][len(folder) + 1:])
            rows.append((r, "/".join([dest, os.path.basename(folder)] + ([rel] if rel else []))))
    for i in ids or []:
        r = cat.db.execute("SELECT id,path,name,size,entity,topic,kind,entity_conf,unit,protected,sensitive FROM files WHERE id=?", (int(i),)).fetchone()
        if r:
            if r["path"].startswith("uo://"):
                return [], f"{r['name']} is on another computer; sort it on that computer."
            if r["unit"] != "file" or r["protected"]:
                return [], f"{r['name']} is a project, app or protected folder; it is never moved."
            rows.append((r, dest))
    moves = []
    for r, d in rows:
        if os.path.dirname(r["path"]) == d:
            continue
        moves.append({"id": r["id"], "src": r["path"], "dst": d + "/" + r["name"], "dest_dir": d, "action": "file", "why": "moved by you",
                      "size": r["size"] or 0, "needs_ok": False, "owner": r["entity"], "topic": r["topic"], "kind": r["kind"], "conf": r["entity_conf"]})
    return moves, None


def _free(dst):
    if not os.path.lexists(dst):
        return dst
    base, ext = os.path.splitext(dst)
    for i in range(2, 1000):
        c = f"{base} ({i}){ext}"
        if not os.path.lexists(c):
            return c
    raise OSError("no free name")


def _update_catalogue(cat, fid, src, dst):
    cat.db.execute("UPDATE files SET path=?, name=? WHERE id=?", (dst, os.path.basename(dst), fid))
    cat.db.execute("UPDATE fts SET path=?, name=? WHERE rowid=?", (dst, os.path.basename(dst), fid))
    cat.db.execute("UPDATE decisions SET path=? WHERE path=?", (dst, src))
    cat.db.execute("UPDATE plan SET path=? WHERE file_id=?", (dst, fid))


def run(cfg, cat, moves, by, progress=lambda d, t: None, lock=None):
    """Move the approved items. Each is re-checked first. Returns a summary; the log makes it undoable."""
    sc = _sc(cfg)
    synced = synced_roots(cfg, cat)
    os.makedirs(LOGS, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(LOGS, f"sort-{stamp}.jsonl")
    done = skipped = errors = 0
    reasons = Counter()
    left_dirs = set()
    allowed = [cfg.library, trash(cfg), expand(sc.get("local_only_folder", "{HOME}/Private (local only)"))]
    with open(log_path, "w") as log:
        for i, m in enumerate(moves):
            progress(i, len(moves))
            if errors >= sc.get("max_errors", 25):
                reasons["stopped: too many errors"] += len(moves) - i; break
            with (lock or contextlib.nullcontext()):
                res = _one(cfg, cat, m, synced, allowed, log)
            if res == "moved":
                done += 1; left_dirs.add(os.path.dirname(m["src"]))
                if done % 100 == 0:
                    with (lock or contextlib.nullcontext()):
                        cat.db.commit()
            elif res.startswith("error"):
                errors += 1; reasons[res] += 1
            else:
                skipped += 1; reasons[res] += 1
    with (lock or contextlib.nullcontext()):
        cat.db.commit()
    with (lock or contextlib.nullcontext()):
        return _finish(cfg, cat, by, log_path, done, skipped, errors, reasons, left_dirs, len(moves), progress)


def _one(cfg, cat, m, synced, allowed, log):
    """Check one approved move again and do it. Returns 'moved', a skip reason, or 'error: …'."""
    row = cat.db.execute("SELECT path,size,mtime,unit,protected,sensitive FROM files WHERE id=?", (m["id"],)).fetchone()
    src = m["src"]
    why = None
    if src.startswith("uo://"):
        why = "on another computer"
    elif not row or row["path"] != src:
        why = "catalogue changed since the plan"
    elif row["unit"] != "file" or row["protected"] or _under(src, cfg.protect):
        why = "project / protected"
    elif not _under(m["dest_dir"], allowed) or _under(m["dest_dir"], cfg.protect):
        why = "destination not allowed"
    elif row["sensitive"] and _under(m["dest_dir"], synced):
        why = "sensitive file would go into iCloud"
    else:
        try:
            st = os.lstat(src)
        except OSError:
            why = "file no longer there"
        else:
            if st.st_size != row["size"] or abs(st.st_mtime - (row["mtime"] or 0)) > 1:
                why = "file changed since the scan"
            elif platforms.cloud_only(st) and not _under(m["dest_dir"], synced):
                why = "iCloud-only: would need downloading"
    if why:
        log.write(json.dumps({"id": m["id"], "src": src, "skipped": why}) + "\n"); log.flush(); return why
    try:
        os.makedirs(m["dest_dir"], exist_ok=True)
        name = m.get("rename") or os.path.basename(src)  # the new name from the plan, if renaming was ticked
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise OSError("bad file name in the plan")
        dst = platforms.norm(_free(os.path.join(m["dest_dir"], name)))
        os.rename(src, dst)
        if m["action"] == "trash":
            platforms.after_trash(src, dst)
    except OSError as e:
        log.write(json.dumps({"id": m["id"], "src": src, "error": str(e)}) + "\n"); log.flush(); return f"error: {type(e).__name__}"
    log.write(json.dumps({"id": m["id"], "src": src, "dst": dst, "action": m["action"], "renamed": bool(m.get("rename")), "t": time.time()},
                         ensure_ascii=False) + "\n"); log.flush()
    _update_catalogue(cat, m["id"], src, dst)
    if m["action"] in ("trash", "archive"):
        cat.db.execute("DELETE FROM plan WHERE file_id=?", (m["id"],))
    return "moved"


def _finish(cfg, cat, by, log_path, done, skipped, errors, reasons, left_dirs, total, progress):
    sc = _sc(cfg)
    removed_dirs = []
    if sc.get("remove_empty_folders", True):
        stop = set(sources(cfg)) | {cfg.library} | set(cfg.roots)
        for d in sorted(left_dirs, key=len, reverse=True):
            while d and d not in stop and _under(d, [cfg.library]) and not _under(d, cfg.protect):
                try:
                    names = [n for n in os.listdir(d) if n not in (".DS_Store",)]
                    if names:
                        break
                    if os.path.exists(os.path.join(d, ".DS_Store")):
                        os.remove(os.path.join(d, ".DS_Store"))
                    os.rmdir(d); removed_dirs.append(d)
                except OSError:
                    break
                d = os.path.dirname(d)
    summary = f"Sorted {done:,} file(s)" + (f", skipped {skipped:,}" if skipped else "") + (f", {errors} error(s)" if errors else "")
    cur = cat.db.execute("INSERT INTO sort_runs(t,by,summary,log,moved,skipped,errors,removed_dirs) VALUES(?,?,?,?,?,?,?,?)",
                         (time.time(), by, summary, log_path, done, skipped, errors, json.dumps(removed_dirs)))
    cat.db.commit()
    progress(total, total)
    return {"run": cur.lastrowid, "moved": done, "skipped": skipped, "errors": errors, "reasons": dict(reasons), "summary": summary,
            "log": log_path, "removed_dirs": len(removed_dirs)}


def undo(cfg, cat, run_id, by):
    r = cat.db.execute("SELECT log, undone, removed_dirs FROM sort_runs WHERE id=?", (run_id,)).fetchone()
    if not r or r["undone"]:
        return {"undone": 0, "problems": ["already undone or unknown run"]}
    back, problems = 0, []
    entries = [json.loads(l) for l in open(r["log"]) if l.strip()]
    for e in reversed(entries):
        if "dst" not in e:
            continue
        if not os.path.lexists(e["dst"]):
            problems.append(f"gone: {e['dst']}"); continue
        if os.path.lexists(e["src"]):
            problems.append(f"something else is now at {e['src']}"); continue
        try:
            os.makedirs(os.path.dirname(e["src"]), exist_ok=True)
            os.rename(e["dst"], e["src"])
            if e.get("action") == "trash":
                platforms.after_untrash(e["dst"])
            _update_catalogue(cat, e["id"], e["dst"], e["src"])
            back += 1
        except OSError as ex:
            problems.append(f"{type(ex).__name__}: {e['dst']}")
    cat.db.execute("UPDATE sort_runs SET undone=? WHERE id=?", (time.time(), run_id))
    cat.db.commit()
    with open(r["log"].replace(".jsonl", f".undo-{time.strftime('%H%M%S')}.txt"), "w") as f:
        f.write(f"undone by {by}: {back} moved back\n" + "\n".join(problems))
    return {"undone": back, "problems": problems[:50]}


def runs(cat, limit=30):
    return [dict(r) for r in cat.db.execute("SELECT id,t,by,summary,moved,skipped,errors,undone FROM sort_runs ORDER BY id DESC LIMIT ?", (limit,))]
