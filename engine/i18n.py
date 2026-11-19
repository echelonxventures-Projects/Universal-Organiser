"""Languages for the pages: engine/i18n/<code>.json dictionaries (English text → translation), applied in the browser
by engine/i18n.js. Missing texts stay in English. See tools/i18n_extract.py and CONTRIBUTING.md to add a language."""
import json, os

from .config import ROOT

DIR = os.path.join(ROOT, "engine", "i18n")
_cache = {}


def _load(code):
    p = os.path.join(DIR, code + ".json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {}
    if _cache.get(code, (None,))[0] != mt:
        try:
            with open(p, encoding="utf-8") as f:
                _cache[code] = (mt, json.load(f))
        except ValueError:
            _cache[code] = (mt, {})
    return _cache[code][1]


def languages():
    """{code: own name}, English first."""
    out = {"en": "English"}
    if os.path.isdir(DIR):
        for n in sorted(os.listdir(DIR)):
            if n.endswith(".json") and n != "en.json":
                d = _load(n[:-5])
                if d.get("_name"):
                    out[n[:-5]] = d["_name"]
    return out


def head(code):
    langs = languages()
    dct = {} if code == "en" else {k: v for k, v in _load(code).items() if not k.startswith("_")}
    data = {"lang": code, "dict": dct, "languages": [{"code": c, "name": n} for c, n in langs.items()]}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    with open(os.path.join(ROOT, "engine", "i18n.js"), encoding="utf-8") as f:
        js = f.read()
    return f"<script>window.UO_I18N={blob};</script>\n<script>\n{js}\n</script>\n"
