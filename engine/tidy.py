"""Library tidy plans for the sorter (read-only until a person runs them):

1. Folder standard - Group / Person / Topic [/ Year].  The year level is used only where a topic folder holds more than
   `year_level_min` files; smaller topics are kept flat. Meaningful sub-folders (Tax, Bank, …) are kept; "Others",
   "General", … are merged into "Misc".
2. Misfiled      - a file whose owner (high confidence or your own label) is a different person than its folder:
                   planned to that person's folder, but marked 'needs OK'.
3. Old clutter   - code, installers and archives in To Sort older than `archive_after_years` go to Archive/<year>/<kind>.
Media, projects, duplicates review and To Sort itself are not restructured here."""
import os, re, datetime
from collections import Counter
from .sorter import group_label, Layout, _clean, _under

YEAR = re.compile(r"^(19|20)\d\d$")
MONTH = re.compile(r"^\d\d-[A-Za-z]+$")


def _sc(cfg):
    return cfg.get("sorter", {})


def _parse(cfg, path):
    """(base folder, owner name, topic, sub-folders without year/month) for a file in a person or office group."""
    lib = cfg.library + "/"
    if not path.startswith(lib):
        return None
    parts = path[len(lib):].split("/")
    gl = cfg.get("group_labels") or {}
    by_label = {v: k for k, v in gl.items()}
    g = parts[0]
    kind = by_label.get(g)
    if kind in ("Self", "Family", "Friend", "Organisation", "Client") and len(parts) >= 4:
        base, owner, rest = lib + g + "/" + parts[1], parts[1], parts[2:-1]
    elif " - " in g and by_label.get(g.split(" - ")[0]) in ("Office", "Client") and len(parts) >= 3:
        base, owner, rest = lib + g, g.split(" - ", 1)[1], parts[1:-1]
    else:
        return None
    if not rest:
        return None
    misc = {m.lower() for m in _sc(cfg).get("misc_names", ["Misc", "Others", "Other", "General", "Miscellaneous"])}
    topic = "Misc" if rest[0].lower() in misc else rest[0]
    subs = [p for p in rest[1:] if not YEAR.match(p) and not MONTH.match(p)]
    return base, owner, topic, subs


def plan(cfg, cat, standard=True, misfiled=True, archive=True):
    sc = _sc(cfg)
    lib = cfg.library + "/"
    ymin = sc.get("year_level_min", 30)
    ents = {e["name"]: e for e in cfg.get("entities", [])}
    rows = [dict(r) for r in cat.db.execute(
        "SELECT id,path,name,kind,unit,size,date,year,entity,entity_conf,topic,doc_type,cloud_only,sensitive,protected FROM files "
        "WHERE unit='file' AND coalesce(protected,0)=0 AND substr(path,1,?)=?", (len(lib), lib))]
    moves, stays = [], Counter()
    parsed = {r["id"]: _parse(cfg, r["path"]) for r in rows}
    counts = Counter((p[0], p[2]) for p in parsed.values() if p)
    L = Layout(cfg, cat) if misfiled else None

    def add(r, dest_dir, action, why, needs_ok=False):
        if os.path.dirname(r["path"]) == dest_dir:
            return
        if _under(r["path"], cfg.protect) or _under(dest_dir, cfg.protect):
            stays["protected"] += 1; return
        moves.append({"id": r["id"], "src": r["path"], "dst": dest_dir + "/" + r["name"], "dest_dir": dest_dir, "action": action, "why": why,
                      "size": r["size"] or 0, "needs_ok": needs_ok, "owner": r["entity"], "topic": r["topic"], "kind": r["kind"], "conf": r["entity_conf"]})

    for r in rows:
        if r["sensitive"]:
            stays["sensitive: left where it is"] += 1
            continue
        p = parsed[r["id"]]
        if not p:
            continue
        base, owner, topic, subs = p
        conf = r["entity_conf"] or ""
        if misfiled and r["entity"] and r["entity"] in ents and r["entity"] != owner and (conf == "high" or conf.startswith("you")):
            d, why = L.owner_dest(r)
            q = _parse(cfg, d + "/x")  # the destination follows the same standard (year level only for big topics)
            if q:
                n = counts[(q[0], q[2])] + 1
                d = "/".join([q[0], _clean(q[2])] + [_clean(x) for x in q[3]]) + (("/" + (r["year"] or "Undated")) if n > ymin else "")
            add(r, d, "file", f"belongs to {r['entity']} ({'your label' if conf.startswith('you') else r.get('entity_why') or 'holder on the document'}), "
                              f"but sits in {owner}'s folder", needs_ok=True)
            continue
        if standard:
            dest = "/".join([base, _clean(topic)] + [_clean(s) for s in subs])
            if counts[(base, topic)] > ymin:
                dest += "/" + (r["year"] or "Undated")
            why = (f"{topic}: {counts[(base, topic)]} files, so by year" if counts[(base, topic)] > ymin
                   else f"{topic}: {counts[(base, topic)]} files, kept in one folder")
            add(r, dest, "file", "folder standard - " + why)
    if archive:
        ts = lib + group_label(cfg, "Unsorted") + "/"
        cut = (datetime.date.today() - datetime.timedelta(days=365 * sc.get("archive_after_years", 2))).isoformat()
        kinds = sc.get("archive_kinds", {"Code": "Code", "Installer": "Installers", "Archive": "Archives"})
        arch = lib + group_label(cfg, "Archive")
        for r in rows:
            if r["path"].startswith(ts) and r["kind"] in kinds and not r["sensitive"] and r["date"] and r["date"] < cut:
                add(r, f"{arch}/{r['year'] or 'Undated'}/{kinds[r['kind']]}", "archive", f"old {kinds[r['kind']].lower()} (from {r['date'][:4]}) out of To Sort")
    return moves, stays
