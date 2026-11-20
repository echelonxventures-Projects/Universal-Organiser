"""Transcripts of speech in audio and video, made on this Mac (Apple SpeechTranscriber). Nothing leaves the Mac and a
language model that is not installed is never downloaded by the engine. Speech files are done automatically
(meetings, office/client recordings, voice formats); everything else on request. Sensitive and iCloud-only files are skipped."""
import os, json, time
from .config import expand
from .catalogue import LABEL_COLS
from .plugins.macos_vision import _parallel, HELPER

SCHEMA = """CREATE TABLE IF NOT EXISTS transcripts(file_id INTEGER PRIMARY KEY, mtime REAL, locale TEXT, duration REAL, segments TEXT,
 words INTEGER, error TEXT, t REAL)"""


def pc(cfg):
    return cfg.plugin("transcribe")


def is_auto(cfg, r, ents):
    c = pc(cfg)
    if any(r["path"].startswith(expand(x).rstrip("/") + "/") for x in c.get("skip_under", [])):
        return False
    return (r["doc_type"] in c.get("auto_doc_types", []) or (ents.get(r["entity"] or "") in c.get("auto_entity_types", []))
            or (r["ext"] or "") in c.get("auto_exts", []))


def languages():
    """Speech languages Apple supports / has installed on this Mac."""
    import subprocess
    try:
        out = subprocess.run([HELPER, "lang", "list"], capture_output=True, text=True, timeout=60).stdout
        return json.loads(out.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return {"supported": [], "installed": [], "reserved": [], "max_reserved": 0}


def install_language(cfg, loc, cat=None):
    """Download one language model through Apple's on-device installer. Apple keeps at most a few reserved per app and deletes a
    model once its slot is released, so when the slots are full the least recently used one (never a kept one) makes room."""
    import subprocess
    L = languages()
    if loc in L["installed"]:
        return {"locale": loc, "installed": True, "downloaded": False}
    if loc not in L["supported"]:
        return {"locale": loc, "error": "not supported by Apple speech"}
    keep = set(pc(cfg).get("keep_reserved", []))
    used = (cat.get_meta("lang_used", {}) if cat else {}) or {}
    if len(L["reserved"]) >= L["max_reserved"]:
        free = sorted((x for x in L["reserved"] if x not in keep), key=lambda x: used.get(x, 0))
        if not free:
            return {"locale": loc, "error": "all language slots are kept; free one in the profile (keep_reserved)"}
        subprocess.run([HELPER, "lang", "release", free[0]], capture_output=True, text=True, timeout=60)
    r = subprocess.run([HELPER, "lang", "install", loc], capture_output=True, text=True, timeout=900).stdout
    out = json.loads(r.strip().splitlines()[-1]) if r.strip() else {"error": "no answer"}
    if len(L["reserved"]) >= L["max_reserved"] and not out.get("error"):
        out["replaced"] = free[0]
    return out


def mark_used(cat, loc):
    used = cat.get_meta("lang_used", {}) or {}
    for l in loc.split(","):
        used[l] = time.time()
    cat.set_meta("lang_used", used)


def candidates(cfg, cat, ids=None, everything=False, force=False):
    cat.db.execute(SCHEMA)
    ents = {e["name"]: e["type"] for e in cfg.get("entities", [])}
    q = ("SELECT f.id,f.path,f.ext,f.mtime,f.doc_type,f.entity,f.size FROM files f LEFT JOIN transcripts t ON t.file_id=f.id "
         "WHERE f.kind IN ('Audio','Video') AND f.unit='file' AND f.path NOT LIKE 'uo://%' AND coalesce(f.cloud_only,0)=0 AND coalesce(f.sensitive,0)=0 "
         + ("" if force else "AND (t.file_id IS NULL OR abs(t.mtime-f.mtime)>1)"))
    rows = cat.db.execute(q).fetchall()
    if ids is not None:
        want = set(ids)
        return [r for r in rows if r["id"] in want]
    return [r for r in rows if everything or is_auto(cfg, r, ents)]


def _relabel(cfg, cat, fid, text):
    """Owner / document type / topic again for one file, now with its spoken words."""
    from .plugins import classify
    r = cat.db.execute("SELECT id,path,name,kind,unit,ext,hash FROM files WHERE id=?", (fid,)).fetchone()
    rec = {"id": fid, "path": r["path"], "name": r["name"], "kind": r["kind"], "unit": r["unit"], "ext": r["ext"], "hash": r["hash"], "text": text}
    for name, step in (("doc_type", classify.DocType), ("entities", classify.Entities), ("topics", classify.Topics)):
        if cfg.plugin(name).get("enabled"):
            step.run([rec], cfg)
    d = cat.decision_for(r["path"], r["hash"])
    if d:
        rec.update(d)
    cat._write_cols(fid, {c: rec.get(c) for c in LABEL_COLS})


def save(cfg, cat, row, d):
    segs = d.get("segments") or []
    text = d.get("text") or ""
    if cat.names_only:  # a disk without encryption: spoken words are document text too, never kept
        segs, text = [], ""
    cat.db.execute("INSERT OR REPLACE INTO transcripts VALUES(?,?,?,?,?,?,?,?)",
                   (row["id"], row["mtime"], d.get("locale"), d.get("duration"), json.dumps(segs, ensure_ascii=False),
                    len(text.split()), d.get("error") or ("partly unreadable: transcript covers the readable part" if d.get("partial") else None), time.time()))
    if text:
        body = (cat.db.execute("SELECT body FROM fts WHERE rowid=?", (row["id"],)).fetchone() or [""])[0] or ""
        marker = "\n[transcript]\n"
        body = body.split(marker)[0] + marker + text
        cat.db.execute("UPDATE fts SET body=? WHERE rowid=?", (body, row["id"]))
        tags = json.loads(cat.db.execute("SELECT coalesce(tags,'[]') FROM files WHERE id=?", (row["id"],)).fetchone()[0] or "[]")
        if "transcribed" not in tags:
            tags.append("transcribed")
        cat.db.execute("UPDATE files SET snippet=coalesce(nullif(snippet,''),?), tags=? WHERE id=?", (text[:300], json.dumps(tags), row["id"]))
        if pc(cfg).get("label_from_transcript", False):  # off by default: spoken words are noisy evidence for owner/topic
            _relabel(cfg, cat, row["id"], text)


def run(cfg, cat, rows, log=print, lock=None, progress=lambda d, t: None, language=None):
    import contextlib
    c = pc(cfg)
    if not os.path.exists(HELPER):
        log("helper missing"); return 0
    loc = language or ",".join(c.get("languages") or ["en-US"])
    tmp = os.path.join(cat.folder, "tmp-audio")
    total, done, t0 = len(rows), 0, time.time()
    log(f"to transcribe: {total} ({sum(r['size'] or 0 for r in rows) / 1e9:.1f} GB), language {loc}")
    w = max(1, int(c.get("workers", 2)))
    for i in range(0, total, w * 2):
        chunk = rows[i:i + w * 2]
        res = _parallel([r["path"] for r in chunk], ["transcribe", loc, str(c.get("max_minutes", 180)), tmp], n=w,
                        timeout=max(600, c.get("max_minutes", 180) * 30))
        with (lock or contextlib.nullcontext()):
            for r in chunk:
                save(cfg, cat, r, res.get(r["path"], {"error": "no result", "locale": loc}))
            cat.db.commit()
        done += len(chunk)
        progress(done, total)
        el = time.time() - t0
        log(f"  {done}/{total}  ({el / done * (total - done) / 60:.0f} min left)")
    return done


def get(cat, fid):
    cat.db.execute(SCHEMA)
    r = cat.db.execute("SELECT locale,duration,segments,words,error,t FROM transcripts WHERE file_id=?", (fid,)).fetchone()
    if not r:
        return None
    d = dict(r); d["segments"] = json.loads(d["segments"] or "[]")
    return d


def stats(cat):
    cat.db.execute(SCHEMA)
    return dict(zip(("files", "with_text", "hours", "words", "errors"), cat.db.execute(
        "SELECT count(*), sum(words>0), coalesce(sum(duration),0)/3600.0, coalesce(sum(words),0), sum(error IS NOT NULL) FROM transcripts").fetchone()))
