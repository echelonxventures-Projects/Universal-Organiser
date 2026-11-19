"""Collect the English text of the pages, and check the translations.

  python tools/i18n_extract.py            write engine/i18n/en.json (every text the pages show) and report coverage
  python tools/i18n_extract.py --check    CI: fail if a translation file is broken (bad JSON, placeholders that do not
                                          match the English, or a key no page uses any more is fine — only reported)

Texts come from the pages' markup, their attributes (placeholder, title, aria-label, alt) and the strings their scripts
build. "${…}" parts become {0}, {1}…; markup splits a text into separate pieces, exactly as the browser shows them.
Translation files: engine/i18n/<code>.json = {"_name": "हिन्दी", "English text": "translation", …}.
"""
import glob, html, json, os, re, sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I18N = os.path.join(ROOT, "engine", "i18n")
ATTRS = ("placeholder", "title", "aria-label", "alt")
CODEY = re.compile(r"^[\w.-]+$|[{};=<>]|=>|\b(function|const|let|return|var)\b|^[/#.]|\\\\|^\w+\(|^[a-z_]+:|^&\w+;$")


def norm(t):
    return re.sub(r"\s+", " ", t).strip()


IGNORE = {"b own", "btn pri", "dot label", "x u-del", "tag ask", "st {0}", "dot {0}", "noopener noreferrer", ".fold input",
          "uo scan", "uo scan --full", "uo serve", "uo agent pair {0} {1}", "uo.cmd agent pair {0} {1}",
          "Content-Type", "Universal Organiser",
          # HTTP and program words, and names that are folders, topics or apps on disk: never translated
          "Authorization", "Bearer", "Bypass", "Cookie", "Host", "Origin", "Enter", "Escape", "Port", "Release", "Set", "Over",
          "Android", "Chrome", "Firefox", "Safari", "Linux", "Macintosh", "Python", "Box", "Dropbox", "Google Drive", "Nextcloud",
          "Desktop", "Documents", "Downloads", "Pictures", "Movies", "Music", "Mobile Documents", "Library", "Sorted", "Unsorted",
          "Education", "Insurance", "Medical", "Property", "Travel", "General", "Misc", "Miscellaneous", "Others", "Testing",
          "Mostly", "Location", "Finder", "Mac", "Mac / Linux", "Windows", "Windows PC", "Python {0}.{1}", "· Universal Organiser",
          "Apple Command Line Tools (swiftc)", "(winget install -e --id ShiningLight.OpenSSL.Light)", "\\bdad\\b"}
WORD = re.compile(r"[A-Z][a-z]+(?:[ -][a-z]+)?(?: \([A-Z]\))?[.…!?]?|[A-Z][a-z]+…")


def wanted(t):
    t = norm(t)
    if len(t) < 2 or not re.search(r"[A-Za-z]{2}", t) or t in IGNORE:
        return False
    if WORD.fullmatch(t):  # a single word on a button or menu ("Save", "Settings", "Next (N)")
        return True
    if CODEY.search(re.sub(r"\{\d+\}", "", t)) and " " not in t:
        return False
    if re.search(r"[{}]|;(?!\s)|=>|\$\{|&&|\|\||\?'|':|==|\.\w+\(", re.sub(r"\{\d+\}", "", t)):  # code, not prose
        return False
    if re.fullmatch(r"[a-z][a-zA-Z0-9_-]*", t):  # identifiers, css classes, ids
        return False
    if re.fullmatch(r"(--|var\(|#|rgb|\d)[\w\s(),.%-]*", t):
        return False
    return True


class Markup(HTMLParser):
    def __init__(self, out):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = out, 0

    def handle_starttag(self, tag, a):
        if tag in ("script", "style", "code", "pre"):
            self.skip += 1
        for k, v in a:
            if k in ATTRS and v and wanted(v):
                self.out.add(norm(v))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "code", "pre") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and wanted(data):
            self.out.add(norm(data))


STR = re.compile(r'`((?:[^`\\]|\\.|\$\{(?:[^{}]|\{[^{}]*\})*\})*)`|"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'', re.S)


def pieces(lit):
    """A script string → the texts a browser would show from it."""
    n = [0]

    def ph(m):
        inner = m[1]
        if re.search(r"[`<]", inner):  # a nested template or markup: its own texts come from the outer scan
            return "\x02"
        k = f"{{{n[0]}}}"; n[0] += 1
        return k
    s = re.sub(r"\$\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}", ph, lit)
    out = []
    for seg in re.split(r"<[^>]*>|\x02", s):
        seg = seg.replace("\\n", " ").replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
        for a in re.findall(r'(?:placeholder|title|aria-label|alt)="([^"]*)"', seg):
            out.append(a)
        if wanted(seg) and "=" not in seg:
            t = norm(seg)
            ks = re.findall(r"\{\d+\}", t)  # renumber from {0} inside this piece
            for i, k in enumerate(dict.fromkeys(ks)):
                t = t.replace(k, f"{{#{i}}}")
            out.append(t.replace("{#", "{"))
    for a in re.findall(r'(?:placeholder|title|aria-label|alt)="([^"$]*)"', lit):
        out.append(a)
    return [norm(o) for o in out if wanted(o)]


def from_page(path):
    src = open(path, encoding="utf-8").read()
    found = set()
    Markup(found).feed(src)
    m = re.search(r"<title>(.*?)</title>", src, re.S)
    if m:
        found.add(norm(m[1]))
    for script in re.findall(r"<script>(.*?)</script>", src, re.S):
        script = re.sub(r"/\*.*?\*/", "", script, flags=re.S)
        script = re.sub(r"(?m)^\s*//.*$", "", script)
        for m in STR.finditer(script):
            lit = next(g for g in m.groups() if g is not None) if any(g is not None for g in m.groups()) else ""
            if m.group(0)[0] == "`" or "<" in lit or " " in lit:
                found.update(pieces(lit))
            elif wanted(lit) and re.match(r"[A-Z]", lit):
                found.add(norm(lit))
    return found


PY_UI = ["setup.py", "settings.py", "server.py", "home.py", "insights.py", "overview.py", "analytics.py", "tidy.py", "sorter.py",
         "smartfolders.py", "projects.py", "cleanup.py", "hub.py", "lan.py", "auth.py", "reclassify.py", "similar.py", "projsteps.py",
         "tags.py", "declutter.py", "deepread.py", "transcribe.py", "projmove.py", "updates.py"]
SQLISH = re.compile(r"\b(CREATE|INSERT|DELETE FROM|ORDER BY|GROUP BY|AND|OR|LIMIT|VALUES|FROM files)\b|^\(\?i\)|\bf\.\w+|\bLIKE\b|\bCASE\b|= \?|\bIN \(|\bSELECT\b|\bWHERE\b|\bAND \(|%s|\\\\|/api/|<\w|\.py\b|`")


def from_python(path):
    """Texts the server sends to the pages: string literals and f-strings ({x} → {0}), not docstrings, not SQL."""
    import ast
    tree = ast.parse(open(path, encoding="utf-8").read())
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body and \
                isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
            docs.add(id(node.body[0].value))
    parts_of_f = {id(v) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for v in node.values}
    out = set()
    for node in ast.walk(tree):
        if id(node) in parts_of_f:
            continue
        if isinstance(node, ast.JoinedStr):
            parts, n = [], 0
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                else:
                    parts.append(f"{{{n}}}"); n += 1
            t = "".join(parts)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            t = node.value
        else:
            continue
        t = norm(html.unescape(t))
        if (re.match(r"[A-Z(“✓⚠]", t) and re.search(r"[a-z]{2}", t) and (" " in t or WORD.fullmatch(t)) and len(t) < 400
                and not SQLISH.search(t) and t not in IGNORE and not re.search(r"\{[a-z_]", t)):
            out.add(t)
    return out


def extract():
    keys = set()
    for m in PY_UI:
        f = os.path.join(ROOT, "engine", m)
        if os.path.exists(f):
            keys |= from_python(f)
    for f in sorted(glob.glob(os.path.join(ROOT, "engine", "*.html"))):
        keys |= from_page(f)
    a11y = open(os.path.join(ROOT, "engine", "a11y.js"), encoding="utf-8").read()
    keys |= {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Language"}
    keys -= {"Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec"}
    keys |= set(re.findall(r'"((?:Skip to content|Pages|Arrow keys[^"]*|Close|More|Back|Next|Previous|Add|Remove|Move up|Move down|Expand|Collapse|Play|Pause|Refresh|Edit|Delete))"', a11y))
    keys = {html.unescape(k).replace("\\\\", "\\") for k in keys}  # "&amp;" shows as "&", "\\\\b" as "\\b"
    return sorted(k for k in keys if k and len(k) <= 600 and k not in IGNORE)


def placeholders(s):
    return sorted(set(re.findall(r"\{\d+\}", s)))


def main():
    keys = extract()
    os.makedirs(I18N, exist_ok=True)
    bad = 0
    if "--check" not in sys.argv:
        with open(os.path.join(I18N, "en.json"), "w", encoding="utf-8") as f:
            json.dump({"_name": "English", "_keys": keys}, f, ensure_ascii=False, indent=0)
    ks = set(keys)
    for f in sorted(glob.glob(os.path.join(I18N, "*.json"))):
        code = os.path.basename(f)[:-5]
        if code == "en":
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except ValueError as e:
            print(f"{code}: not valid JSON: {e}"); bad += 1; continue
        if not d.get("_name"):
            print(f"{code}: no _name (the language's own name, shown in the picker)"); bad += 1
        for k, v in d.items():
            if k.startswith("_"):
                continue
            if not isinstance(v, str) or not v.strip():
                print(f"{code}: empty translation for {k!r}"); bad += 1
            elif not set(placeholders(v)) <= set(placeholders(k)):  # leaving one out is fine (English plural endings)
                print(f"{code}: placeholders not in the English: {k!r} → {v!r}"); bad += 1
        have = {k for k in d if not k.startswith("_")}
        print(f"{code} ({d.get('_name')}): {len(have & ks)}/{len(ks)} texts translated ({100 * len(have & ks) // max(1, len(ks))}%), "
              f"{len(have - ks)} no longer used")
    print(f"{len(keys)} texts in the pages")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
