"""macOS on-device analysis through the compiled Swift helper (PDFKit + Apple Vision):
PDF text (with OCR fallback for scans), image OCR, scene labels, face count, EXIF date/camera."""
import os, json, subprocess, select, threading
from concurrent.futures import ThreadPoolExecutor
from ..config import ROOT

HELPER = os.path.join(ROOT, "helpers/macos/fehelper")
PER_FILE_TIMEOUT = 90


class Helper:
    def __init__(self, args, timeout=PER_FILE_TIMEOUT):
        self.args, self.p, self.timeout = args, None, timeout

    def _start(self):
        self.p = subprocess.Popen([HELPER] + self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, bufsize=1)

    def ask(self, path):
        if self.p is None or self.p.poll() is not None:
            self._start()
        try:
            self.p.stdin.write(path + "\n"); self.p.stdin.flush()
            ready, _, _ = select.select([self.p.stdout], [], [], self.timeout)
            if not ready:
                raise TimeoutError
            line = self.p.stdout.readline()
            return json.loads(line) if line else {"error": "helper exited"}
        except (TimeoutError, BrokenPipeError, ValueError) as e:
            self.p.kill(); self.p = None
            return {"error": "timeout" if isinstance(e, TimeoutError) else "helper error"}

    def close(self):
        if self.p and self.p.poll() is None:
            self.p.stdin.close(); self.p.wait(timeout=10)


def _parallel(items, args, n=4, timeout=PER_FILE_TIMEOUT):
    if not items:
        return {}
    local = threading.local()
    helpers = []

    def work(path):
        if not hasattr(local, "h"):
            local.h = Helper(args, timeout); helpers.append(local.h)
        return path, local.h.ask(path)

    with ThreadPoolExecutor(max_workers=n) as ex:
        res = dict(ex.map(work, items))
    for h in helpers:
        h.close()
    return res


class PDF:
    NAME, PLATFORMS, CONTENT = "text", {"macos"}, True

    @staticmethod
    def run(batch, cfg):
        if not os.path.exists(HELPER):
            return
        pc = cfg.plugin("text")
        pages = pc.get("pdf_ocr_pages", 3) if pc.get("pdf_ocr_if_no_text", True) and cfg.plugin("ocr").get("enabled") else 0
        todo = [r for r in batch if r.get("unit") == "file" and r["ext"] == "pdf" and not r.get("skip_content")]
        res = _parallel([r["path"] for r in todo], ["pdf", str(cfg["catalogue"].get("max_text_chars", 400000)), str(pages)])
        for r in todo:
            d = res.get(r["path"], {})
            if d.get("error"):
                r.setdefault("errs", []).append("pdf: " + d["error"]); continue
            r["text"], r["pages"] = d.get("text", ""), d.get("pages")
            r["title"] = d.get("title") or r.get("title")
            if d.get("ocr") and r["text"].strip():
                r.setdefault("tags", []).append("scanned")
            if d.get("locked"):
                r.setdefault("tags", []).append("password-protected")


class Image:
    NAME, PLATFORMS, CONTENT = "image_meta", {"macos"}, True

    @staticmethod
    def run(batch, cfg):
        if not os.path.exists(HELPER):
            return
        oc, ic = cfg.plugin("ocr"), cfg.plugin("image_classify")
        cap = oc.get("max_mb", 40) * 1e6
        todo = [r for r in batch if r.get("unit") == "file" and r.get("kind") == "Photo" and not r.get("skip_content")
                and r["size"] <= cap and r["ext"] not in ("gif", "raw", "cr2", "nef", "dng")]
        res = _parallel([r["path"] for r in todo], ["image", "20000", "0", str(ic.get("min_confidence", 0.35))])
        for r in todo:
            d = res.get(r["path"], {})
            if d.get("error"):
                r.setdefault("errs", []).append("image: " + d["error"]); continue
            tags = r.setdefault("tags", [])
            if ic.get("enabled", True):
                tags += [x["l"].replace("_", " ") for x in d.get("labels", [])[: ic.get("max_labels", 6)]]
            if cfg.plugin("faces").get("enabled", True) and d.get("faces"):
                tags.append("people"); r.setdefault("extra", {})["faces"] = d["faces"]
            if d.get("gps"):
                tags.append("has-location")
            txt = d.get("text", "") if oc.get("enabled", True) else ""
            if len(txt.strip()) > 30:
                tags.append("has-text"); r["text"] = txt
            ex = r.setdefault("extra", {})
            for k in ("taken", "camera", "w", "h"):
                if d.get(k):
                    ex[k] = d[k]
