"""File renaming for the Sorter: a clear, consistent name made from what the catalogue knows.

Only when you tick “Rename files” in the Sorter, and only for files the Sorter is moving anyway. The new name is shown
in the plan before anything happens; undoing the run puts back the old name together with the old place.

Which style:
  - naming_preset "original" (the default) → no renaming at all
  - a document type with its own style (presets.naming_by_type): identity documents → id-docs, invoices and receipts
    → invoice, screenshots → screenshot
  - every other document → the style you chose (naming_preset)
Never renamed: sensitive files, and photos, videos and audio that are not documents (holiday photos keep IMG_1234).

Tokens: {date} {time} {entity_tag} {doc_type} {vendor} {amount}, {original} (the whole old name) and {title}: what the
old name says beyond the date, owner and document type the new name already carries (an old date prefix, the owner's
name and the type's words are taken out). Every style except screenshots keeps {title}, so a new name never loses what
the old one told you. A token with no value is left out with its separator: "{date}_{vendor}_Invoice_{amount}_{title}"
becomes "2024-03-05_Invoice_1499.00_march" when no vendor is known.
"""
import os, re, time

from . import doctypes

TOKEN = re.compile(r"\{(\w+)\}")
BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
PERSON_TYPES = {"Self", "Family", "Friend"}
ORG_TYPES = {"Office", "Organisation", "Client"}
DEFAULT_BY_TYPE = {"tag:id": "id-docs", "Invoice": "invoice", "Receipt": "invoice", "Screenshot": "screenshot"}
DEFAULT_KINDS = ["PDF", "Document", "Spreadsheet", "Presentation", "Email"]
# "Grand total: ₹ 1,499.00", "Amount due 1499", "Total amount (USD) 23.50" — the last such line wins (totals come last)
AMOUNT = re.compile(r"(?i)\b(?:grand\s+total|total\s+amount|amount\s+due|invoice\s+total|net\s+payable|total\s+payable|total)\b"
                    r"[^0-9\n]{0,25}?(\d{1,3}(?:[,\s]\d{2,3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")
DATE_PREFIX = re.compile(r"^\d{4}[-_.]?\d{2}[-_.]?\d{2}[ _-]*")


def clean(s, limit=120):
    s = BAD.sub("-", str(s or ""))
    s = re.sub(r"\s+", " ", s).strip(" .-_")
    return s[:limit].rstrip(" .-_")


def style_for(cfg, r):
    """The template name for this file, or None (keep its name)."""
    chosen = cfg.get("naming_preset") or "original"
    if chosen == "original" or r.get("sensitive"):
        return None
    by_type = (cfg.get("presets") or {}).get("naming_by_type") or DEFAULT_BY_TYPE
    dt = r.get("doc_type") or ""
    if dt and dt in by_type:
        return by_type[dt]
    if dt and dt in doctypes.tagged("id") and "tag:id" in by_type:
        return by_type["tag:id"]
    kinds = (cfg.get("presets") or {}).get("naming_kinds") or DEFAULT_KINDS
    if r.get("kind") in kinds or dt:
        return chosen
    return None


def _amount(text):
    hits = AMOUNT.findall(text or "")
    if not hits:
        return ""
    v = re.sub(r"[,\s]", "", hits[-1])
    return v if re.fullmatch(r"\d+(\.\d{1,2})?", v) and float(v) > 0 else ""


def _entity_tag(cfg, name):
    if not name:
        return ""
    e = next((x for x in cfg.get("entities", []) if x.get("name") == name), {})
    if e.get("tag"):
        return clean(e["tag"], 40)
    if e.get("type") in PERSON_TYPES:
        return clean(re.sub(r"\(.*?\)", "", name).split()[0], 40)
    return clean(name, 40)


def _short(s, limit=60):
    """At most `limit` characters, cut at a word boundary."""
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0]
    return (cut if len(cut) >= limit // 2 else s[:limit]).rstrip(" .-_,;")


def _rest(stem, drop_words, drop_date):
    """What the original name says beyond what the new name adds back (its date, owner, document type). Only those
    are taken out, and only where they are; everything else of the old name stays exactly as it was."""
    t = DATE_PREFIX.sub("", stem) if drop_date else stem
    for w in sorted({w for w in drop_words if w}, key=len, reverse=True):
        t = re.sub(r"(?i)(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z])", "\x01", t)
    while "\x01" in t:  # a removed word and the separators around it become one separator
        t = re.sub(r"([\s_.-]*)\x01+([\s_.-]*)", lambda m: (m[1] or m[2])[:1].replace(".", " ") if (m[1] or m[2]) else "", t)
    t = t.strip(" _.-")
    return _short(clean(t)) if len(re.sub(r"[^A-Za-z0-9\u0080-\uffff]", "", t)) >= 2 else ""


def values(cfg, r, text=None, template=""):
    stem = os.path.splitext(r["name"])[0]
    tag = _entity_tag(cfg, r.get("entity"))
    e = next((x for x in cfg.get("entities", []) if x.get("name") == r.get("entity")), {})
    dt = (r.get("doc_type") or "")
    drop = []
    if "{entity_tag}" in template:
        drop += [tag, re.sub(r"\(.*?\)", "", e.get("name", "")).strip()]
    if "{doc_type}" in template:
        drop += re.findall(r"[A-Za-z0-9]+", dt)
    drop += re.findall(r"[A-Za-z]{3,}", TOKEN.sub(" ", template))  # words the style writes itself ("Invoice")
    if "{vendor}" in template and e.get("type") in ORG_TYPES:
        drop.append(r.get("entity"))
    mt = r.get("mtime")
    return {
        "date": r.get("date") or "",
        "time": time.strftime("%H.%M", time.localtime(mt)) if mt else "",
        "entity_tag": tag,
        "title": _rest(stem, drop, drop_date="{date}" in template and bool(r.get("date"))),
        "original": clean(stem),
        "doc_type": clean(dt.replace(" / ", " - ")),
        "vendor": clean(r.get("entity"), 40) if e.get("type") in ORG_TYPES else "",
        "amount": _amount(text) if text is not None else "",
    }


def render(template, vals):
    parts = TOKEN.split(template)  # literal, token, literal, token, …
    out = []
    for i, p in enumerate(parts):
        out.append((vals.get(p) or "\x00") if i % 2 else p)
    s = re.sub(r"[_ ]*\x00", "", "".join(out))  # an empty token goes, with the separator before it
    return clean(s.strip("_ "))


def new_name(cfg, r, text_of=lambda fid: None):
    """The new file name (with the original extension), or None to keep the current one."""
    style = style_for(cfg, r)
    if not style:
        return None
    tpl = ((cfg.get("presets") or {}).get("naming") or {}).get(style)
    if not tpl or tpl == "{original}":
        return None
    vals = values(cfg, r, text_of(r["id"]) if "{amount}" in tpl else None, tpl)
    stem = render(tpl, vals)
    ext = os.path.splitext(r["name"])[1]
    if not stem or stem.lower() == os.path.splitext(r["name"])[0].lower():
        return None
    return stem + ext


def distinct(name, original, taken):
    """Two files that would get the same name: the later one keeps its old name as a suffix (more telling than “(2)”)."""
    if name.lower() not in taken:
        return name
    stem, ext = os.path.splitext(name)
    alt = clean(f"{stem}_{os.path.splitext(original)[0]}", 160) + ext
    return alt
