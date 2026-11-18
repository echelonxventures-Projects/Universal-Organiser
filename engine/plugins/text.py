"""Text from Office/OpenDocument (zip XML, pure Python), plain text, web pages and RTF (standard library), and legacy formats via
macOS textutil. PDF on Windows/Linux: pdftotext when installed (poppler), otherwise name and dates only."""
import re, zipfile, subprocess, html

TAG = re.compile(r"<[^>]+>")
PARA = re.compile(r"</(w:p|a:p|text:p|text:h|row)>|<w:tab/>|<w:br/>|</si>")


def _xml_text(z, names):
    out = []
    for n in names:
        try:
            x = z.read(n).decode("utf-8", "replace")
        except KeyError:
            continue
        out.append(html.unescape(TAG.sub("", PARA.sub("\n", x))))
    return "\n".join(out)


def office(path, ext):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if ext == "docx":
            return _xml_text(z, ["word/document.xml"] + [n for n in names if re.match(r"word/(header|footer)\d*\.xml", n)])
        if ext == "xlsx":
            sheets = re.findall(r'name="([^"]+)"', z.read("xl/workbook.xml").decode("utf-8", "replace")) if "xl/workbook.xml" in names else []
            return "Sheets: " + ", ".join(sheets) + "\n" + _xml_text(z, ["xl/sharedStrings.xml"])
        if ext == "pptx":
            slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml", n)), key=lambda s: int(re.findall(r"\d+", s)[0]))
            return _xml_text(z, slides)
        return _xml_text(z, ["content.xml"])


class _HTMLText(__import__("html.parser", fromlist=["HTMLParser"]).HTMLParser):
    """Visible text of a web page (standard library), for systems without textutil."""
    SKIP = {"script", "style", "noscript", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True); self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def html_text(path, cap):
    with open(path, "r", errors="replace") as f:
        p = _HTMLText(); p.feed(f.read(cap * 4)); p.close()
    return re.sub(r"\n\s*\n+", "\n", "".join(p.out))


def rtf_text(path, cap):
    with open(path, "r", errors="replace") as f:
        t = f.read(cap * 4)
    t = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes.fromhex(m[1]).decode("latin-1"), t)
    t = re.sub(r"\\par[d]?\b|\\line\b", "\n", t)
    t = re.sub(r"\{\\\*[^{}]*\}|\\[a-z]+-?\d* ?|[{}]", "", t)
    return t


class Text:
    NAME, PLATFORMS, CONTENT = "text", {"any"}, True

    @staticmethod
    def run(batch, cfg):
        cap = cfg["catalogue"].get("max_text_chars", 400000)
        mode = cfg["catalogue"].get("text", "full")
        if mode == "metadata-only":
            return
        if mode == "first-2kb":
            cap = 2048
        te = cfg.text_ext
        for r in batch:
            if r.get("unit") != "file" or r.get("skip_content") or r.get("text"):
                continue
            e, p = r["ext"], r["path"]
            try:
                if e in te["zip_xml"]:
                    t = office(p, e)
                elif e in te["plain"] and r["size"] < 50e6:
                    with open(p, "r", errors="replace") as f:
                        t = f.read(cap)
                elif e in te["textutil"] and cfg.platform == "macos" and r["size"] < 80e6:
                    t = subprocess.run(["/usr/bin/textutil", "-convert", "txt", "-stdout", p], capture_output=True, text=True,
                                       timeout=40).stdout
                elif e in ("html", "htm") and r["size"] < 30e6:
                    t = html_text(p, cap)
                elif e == "rtf" and r["size"] < 30e6:
                    t = rtf_text(p, cap)
                else:
                    continue
                r["text"] = t[:cap]
            except Exception as ex:
                r.setdefault("errs", []).append(f"text: {type(ex).__name__}")


class PdfText:
    """PDF text on Windows/Linux through poppler's pdftotext, if present. macOS uses PDFKit in the Swift helper."""
    NAME, PLATFORMS, CONTENT = "text", {"windows", "linux"}, True

    @staticmethod
    def run(batch, cfg):
        import shutil
        tool = shutil.which("pdftotext")
        if not tool:
            return
        cap = cfg["catalogue"].get("max_text_chars", 400000)
        for r in batch:
            if r.get("unit") != "file" or r.get("skip_content") or r.get("ext") != "pdf" or r.get("text"):
                continue
            try:
                out = subprocess.run([tool, "-q", "-enc", "UTF-8", "-l", "200", r["path"], "-"], capture_output=True, timeout=60)
                r["text"] = out.stdout.decode("utf-8", "replace")[:cap]
            except Exception as ex:
                r.setdefault("errs", []).append(f"pdf: {type(ex).__name__}")
