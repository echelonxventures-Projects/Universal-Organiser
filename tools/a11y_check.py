"""Accessibility check for the pages in engine/*.html (run by CI):  python tools/a11y_check.py

Static checks on each page's markup:
  - language, title, viewport that allows zooming, one <h1>, a <main> landmark
  - every form control in the markup has a name (a wrapping <label>, <label for>, aria-label, aria-labelledby or title)
  - every button in the markup has text or an aria-label; every image has alt text
  - no element that only reacts to a mouse (onclick on a div/span/td… without role and tabindex)
  - colour contrast of the page's colour tokens, light and dark: text ≥ 4.5:1, accent/warn/amber as text ≥ 4.5:1,
    tag colours on their soft backgrounds ≥ 4.5:1
And the server adds engine/a11y.js to every page (skip link, navigation landmark, dialogs that trap focus and close with
Escape, names for controls the pages build in script, keyboard access for clickable rows, live status messages).
"""
import glob, os, re, sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORM = {"input", "select", "textarea"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.problems, self.label_for, self.controls = [], [], set(), []
        self.h1 = 0; self.main = False; self.lang = False; self.title = False; self.viewport = ""
        self.buttons = []  # [attrs, text]
        self.in_script = False

    def handle_starttag(self, tag, a):
        a = dict(a)
        if self.in_script:
            return
        if tag == "script" or tag == "style":
            self.in_script = True
            return
        if tag == "html" and a.get("lang"):
            self.lang = True
        if tag == "title":
            self.title = True
        if tag == "meta" and a.get("name") == "viewport":
            self.viewport = a.get("content", "")
        if tag == "h1":
            self.h1 += 1
        if tag == "main" or a.get("role") == "main":
            self.main = True
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        if tag in FORM and a.get("type") not in ("hidden", "submit", "button"):
            self.controls.append((tag, a, any(t == "label" for t, _ in self.stack), self.getpos()))
        if tag == "img" and "alt" not in a:
            self.problems.append(f"line {self.getpos()[0]}: image without alt text")
        if "onclick" in a and tag in ("div", "span", "td", "tr", "li", "p", "section") and not (a.get("role") and "tabindex" in a):
            self.problems.append(f"line {self.getpos()[0]}: clickable <{tag}> without role and tabindex (keyboard cannot use it)")
        if tag == "button":
            self.buttons.append([a, "", self.getpos()])
        if tag not in VOID:
            self.stack.append((tag, a))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.in_script = False
            return
        if self.in_script:
            return
        while self.stack:
            t, _ = self.stack.pop()
            if t == tag:
                break

    def handle_data(self, data):
        if self.in_script:
            return
        for t, _ in self.stack:
            if t == "button" and self.buttons:
                self.buttons[-1][1] += data


def lum(hexc):
    hexc = hexc.lstrip("#")
    if len(hexc) == 3:
        hexc = "".join(c * 2 for c in hexc)
    rgb = [int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


PAIRS = [("ink", "bg"), ("ink", "surface"), ("muted", "bg"), ("muted", "surface"), ("accent", "surface"), ("accent", "bg"),
         ("warn", "surface"), ("amber", "surface"), ("accent", "soft"), ("warn", "warnsoft"), ("amber", "ambersoft"),
         ("surface", "accent")]  # last: text on a filled accent button


def tokens(block):
    return {k: v for k, v in re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,6})\b", block)}


def contrast(src):
    out = []
    m = re.search(r":root\{([^}]*)\}", src)
    if not m:
        return out
    light = tokens(m[1])
    d = re.search(r"prefers-color-scheme:\s*dark\)\s*\{\s*:root\{([^}]*)\}", src)
    dark = {**light, **tokens(d[1])} if d else None
    for name, t in (("light", light), ("dark", dark)):
        if not t:
            continue
        for fg, bg in PAIRS:
            if fg in t and bg in t:
                r = ratio(t[fg], t[bg])
                if r < 4.5:
                    out.append(f"{name} theme: --{fg} on --{bg} is {r:.2f}:1 (needs 4.5:1)")
    return out


def check(path):
    src = open(path, encoding="utf-8").read()
    p = Page()
    p.feed(src)
    probs = list(p.problems)
    if not p.lang: probs.append("no lang on <html>")
    if not p.title: probs.append("no <title>")
    if "width=device-width" not in p.viewport: probs.append("no responsive viewport")
    if re.search(r"user-scalable\s*=\s*no|maximum-scale\s*=\s*1(\.0)?\b", p.viewport): probs.append("viewport blocks zooming")
    if p.h1 != 1: probs.append(f"{p.h1} <h1> headings (should be one)")
    if not p.main: probs.append("no <main> landmark")
    for tag, a, wrapped, pos in p.controls:
        named = wrapped or a.get("id") in p.label_for or a.get("aria-label") or a.get("aria-labelledby") or a.get("title")
        if not named:
            probs.append(f"line {pos[0]}: <{tag} {('id=' + a['id']) if a.get('id') else ''}> has no label")
    for a, text, pos in p.buttons:
        if not (text.strip() and re.search(r"\w", text)) and not a.get("aria-label") and not a.get("title"):
            probs.append(f"line {pos[0]}: button without a readable name ({text.strip() or 'empty'})")
    probs += contrast(src)
    return probs


def main():
    bad = 0
    srv = open(os.path.join(ROOT, "engine", "server.py"), encoding="utf-8").read()
    if "a11y.js" not in srv or not os.path.exists(os.path.join(ROOT, "engine", "a11y.js")):
        print("engine/a11y.js is missing or not added to pages by server.py"); bad += 1
    for f in sorted(glob.glob(os.path.join(ROOT, "engine", "*.html"))):
        probs = check(f)
        if probs:
            bad += len(probs)
            print(f"{os.path.basename(f)}:")
            for x in probs:
                print("  - " + x)
    print(f"accessibility check: {'ok' if not bad else str(bad) + ' problem(s)'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
