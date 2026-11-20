"""Read more of a file than the first scan did.
- Scanned PDFs: the first scan reads (OCR) only the first few pages; this reads every page (up to max_pages).
- iCloud-only files: only on request, downloads that one file with macOS's own iCloud tool, then reads it.
Afterwards owner / type / topic are worked out again (a person's own labels always win)."""
import os, time, json, subprocess, shutil
from .plugins.macos_vision import _parallel, HELPER
from .catalogue import LABEL_COLS
from . import platforms


def candidates(cfg, cat, ids=None):
    cap = cfg.plugin("text").get("pdf_ocr_pages", 3)
    q = ("SELECT id,path,pages FROM files WHERE kind='PDF' AND unit='file' AND path NOT LIKE 'uo://%' AND coalesce(cloud_only,0)=0 AND coalesce(sensitive,0)=0 "
         "AND tags LIKE '%scanned%' AND pages > ? AND tags NOT LIKE '%all-pages-read%'")
    rows = cat.db.execute(q, (cap,)).fetchall()
    return [r for r in rows if ids is None or r["id"] in set(ids)]


def _relabel(cfg, cat, fid, text):
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


def read_all_pages(cfg, cat, rows, log=print, lock=None):
    import contextlib
    if cfg.platform != "macos" or not os.path.exists(HELPER) or not rows:
        return 0
    maxp = str(cfg.plugin("text").get("pdf_ocr_max_pages", 200))
    cap = str(cfg["catalogue"].get("max_text_chars", 400000))
    done = 0
    for i in range(0, len(rows), 8):
        chunk = rows[i:i + 8]
        res = _parallel([r["path"] for r in chunk], ["pdf", cap, maxp, "0.35", "all"], n=2, timeout=1800)
        with (lock or contextlib.nullcontext()):
            for r in chunk:
                d = res.get(r["path"], {})
                text = d.get("text") or ""
                if d.get("error") or not text.strip():
                    continue
                body = (cat.db.execute("SELECT body FROM fts WHERE rowid=?", (r["id"],)).fetchone() or [""])[0] or ""
                tail = ("\n[transcript]\n" + body.split("\n[transcript]\n", 1)[1]) if "\n[transcript]\n" in body else ""
                if not cat.names_only:
                    cat.db.execute("UPDATE fts SET body=? WHERE rowid=?", (text + tail, r["id"]))
                tags = json.loads(cat.db.execute("SELECT coalesce(tags,'[]') FROM files WHERE id=?", (r["id"],)).fetchone()[0] or "[]")
                if "all-pages-read" not in tags:
                    tags.append("all-pages-read")
                cat.db.execute("UPDATE files SET tags=? WHERE id=?", (json.dumps(tags), r["id"]))
                _relabel(cfg, cat, r["id"], text)
                done += 1
            cat.db.commit()
        log(f"  read all pages: {min(i + 8, len(rows))}/{len(rows)}")
    return done


def download_and_read(cfg, cat, fid, log=print, lock=None, wait_s=600):
    """Bring one iCloud-only file onto this Mac, then read it like a normal scan."""
    import contextlib
    r = cat.db.execute("SELECT path, sensitive FROM files WHERE id=?", (fid,)).fetchone()
    if not r:
        raise ValueError("no such file")
    if r["sensitive"]:
        raise ValueError("Sensitive files are never read.")
    path = r["path"]
    if platforms.SYSTEM != "macos" or not os.path.exists(HELPER):
        raise ValueError("Download from iCloud works on macOS only.")
    if platforms.cloud_only(os.lstat(path)):
        # Apple's startDownloadingUbiquitousItem (what Finder's "Download Now" does); `brctl download` does nothing on macOS 27
        subprocess.run([HELPER, "download"], input=path + "\n", capture_output=True, text=True, timeout=60)
        t0 = time.time()
        while platforms.cloud_only(os.lstat(path)):
            if time.time() - t0 > wait_s:
                raise TimeoutError("iCloud did not finish downloading in time; try again later")
            time.sleep(2)
    from .scan import make_record
    from . import plugins
    rec = make_record(cfg, path, "file", None)
    for p in plugins.active(cfg):
        try:
            p.run([rec], cfg)
        except Exception as ex:
            log(f"{p.__name__}: {type(ex).__name__}")
    rec["scanned_at"] = rec["seen_at"] = time.time()
    with (lock or contextlib.nullcontext()):
        cat.save([rec])
    return {"read": bool(rec.get("text")), "chars": len(rec.get("text") or "")}
