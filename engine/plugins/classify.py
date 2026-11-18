"""Rule-driven classification. Every rule comes from the profile; nothing here names a person, office or topic."""
import re, datetime as dt, os

NAME_DATE = [
    (re.compile(r"(20\d\d|19\d\d)[-_. ]?(0[1-9]|1[0-2])[-_. ]?(0[1-9]|[12]\d|3[01])"), lambda m: (m[1], m[2], m[3])),
    (re.compile(r"(0[1-9]|[12]\d|3[01])[-_.](0[1-9]|1[0-2])[-_.](20\d\d)"), lambda m: (m[3], m[2], m[1])),
]
EPOCH = re.compile(r"(?<!\d)(1[4-7]\d{8})(?!\d)")
_cache = {}


def rx(pattern):
    if pattern not in _cache:
        _cache[pattern] = re.compile(pattern, re.I)
    return _cache[pattern]


def hit(text, pats):
    return [p for p in pats if rx(p).search(text)]


class Dates:
    NAME, PLATFORMS, CONTENT = "metadata", {"any"}, False

    @staticmethod
    def run(batch, cfg):
        for r in batch:
            d, src = None, None
            for pat, f in NAME_DATE:
                m = pat.search(r["name"])
                if m:
                    try:
                        d = dt.date(*map(int, f(m))); src = "name"; break
                    except ValueError:
                        pass
            if not d:
                m = EPOCH.search(r["name"])
                if m:
                    d = dt.datetime.fromtimestamp(int(m[1])).date(); src = "name (timestamp)"
            taken = (r.get("extra") or {}).get("taken")
            if not d and taken:
                try:
                    d = dt.datetime.strptime(taken[:10], "%Y:%m:%d").date(); src = "camera"
                except ValueError:
                    pass
            if not d:
                ts = [t for t in (r.get("mtime"), r.get("birth")) if t and t > 315532800]
                if ts:
                    d = dt.date.fromtimestamp(min(ts)); src = "file dates"
            if d and 1980 <= d.year <= dt.date.today().year + 1:
                r["date"], r["date_source"], r["year"] = d.isoformat(), src, str(d.year)


class DocType:
    NAME, PLATFORMS, CONTENT = "doc_type", {"any"}, False

    @staticmethod
    def run(batch, cfg):
        rules = cfg["doc_types"]
        for r in batch:
            # code, notes-for-tools and installers contain words like "invoice" or "registry" without being those documents
            if r.get("unit") != "file" or r.get("kind") in ("Code", "Installer", "Font") or (r.get("ext") or "") in ("md", "json", "log"):
                continue
            name = r["name"].lower()
            text = (r.get("text") or "")[:20000]
            best, score = None, 0
            for rule in rules:
                if rule.get("kinds") and r.get("kind") not in rule["kinds"]:
                    continue
                s = 0
                if hit(name, rule.get("any_name", [])):
                    s += 1
                if text and (rule.get("all_text") or rule.get("any_text")) and len(text) <= rule.get("max_text_chars", 10**9):
                    ok_all = all(rx(p).search(text) for p in rule.get("all_text", []))
                    ok_any = not rule.get("any_text") or hit(text, rule["any_text"])
                    if ok_all and ok_any:
                        s += 2
                if s > score:
                    best, score = rule["name"], s
            if best:
                r["doc_type"], r["doc_conf"] = best, ("high" if score >= 3 else "medium" if score == 2 else "low (name only)")


HOLDER_LABEL = re.compile(
    r"(?im)^[ \t]*(?:[^\x00-\x7f/]+\s*/\s*)?"  # optional Hindi label before a slash, e.g. "नाम / Name"
    r"((?:name\s+of\s+(?:the\s+)?)?(?:policy\s*holder|proposer|insured|life\s+assured|account\s+holder|card\s*holder|employee|student|"
    r"candidate|customer|patient|passenger|applicant|assessee|tax\s*payer|elector|holder|member|beneficiary)?(?:'?s)?\s*(?:full\s+)?name"
    r"|policy\s*holder|proposer|life\s+assured|insured(?:\s+person)?|account\s+holder|employee|student|candidate|patient|passenger|elector"
    r"|beneficiary)"
    r"\s*[:\-.]?\s*(?P<v>[A-Za-z][A-Za-z .']{2,60})?[ \t]*$")
NOT_HOLDER = re.compile(r"(?i)father|mother|husband|wife|spouse|guardian|nominee|product|company|employer|bank|branch|plan|scheme|"
                        r"file|user|agent|doctor|hospital|school|college|institut|course|roll|number|\bno\b|registration|serial|"
                        r"date|signature|issued|government|department|certificate|board|university|examination|marks|total|subject")
CERTIFY = re.compile(r"(?i)(?:certif(?:y|ied)\s+that|awarded\s+to|presented\s+to|issued\s+to|in\s+the\s+name\s+of)\s*[:,]?\s*"
                     r"(?:(?:mr|mrs|ms|miss|shri|smt|kumari|dr)\.?\s+)?(?P<v>[A-Za-z][A-Za-z.']+(?:\s+[A-Za-z][A-Za-z.']+){0,3}?)"
                     r"(?=\s*(?:,|\(|\bs/o\b|\bd/o\b|\bw/o\b|\bson\b|\bdaughter\b|\bwife\b|\bhas\b|\bhad\b|\bis\b|\bwas\b|\bbearing\b|\bresiding\b|\bwith\b|\bfor\b|\bof\b|$))")
DOB_LINE = re.compile(r"(?i)\b(DOB|D\.O\.B|date\s+of\s+birth|year\s+of\s+birth)\b|जन्म")
NAMEISH = re.compile(r"^[A-Za-z][A-Za-z .']{2,50}$")
from .. import doctypes  # "dob": name printed above the date of birth; "holder": the holder named on it owns it


def _clean_name(v):
    v = re.sub(r"\s+", " ", v or "").strip(" .'-")
    w = v.split()
    if not (1 <= len(w) <= 5 and NAMEISH.match(v) and not NOT_HOLDER.search(v)):
        return None
    # names are written in Title Case or CAPITALS ("monitoring queues" is not a name)
    return v if all(x[0].isupper() for x in w if x.lower() not in ("de", "da", "van", "bin", "binti")) else None


def holder_names(text, doc_type=None, limit=4000):
    """Names written in the holder's field of a document (not names merely mentioned)."""
    t = (text or "")[:limit]
    lines = [l.strip() for l in t.splitlines()]
    out = []
    for i, l in enumerate(lines):
        # labels are often bilingual ("Beneficiary Name / लाभार्थी का नाम"): match on the English part only
        l = re.sub(r"\s+", " ", re.sub(r"\s*/\s*", " ", re.sub(r"[^\x00-\x7f]+", " ", l))).strip()
        m = HOLDER_LABEL.match(l)
        if not m or NOT_HOLDER.search(m.group(1)):
            continue
        v = _clean_name(m.group("v")) if m.group("v") else None
        if not v:  # label alone on its line: the value is on the next non-empty line
            nxt = next((x for x in lines[i + 1:i + 3] if x), "")
            v = _clean_name(nxt)
        if v:
            out.append(v)
    for i, l in enumerate(lines):  # invoices / receipts: the person's name is the first line under "Bill To", "Billing Address", …
        if re.match(r"(?i)^(billing address|shipping address|bill to|ship to|sold to|deliver(?:y)? to|consignee|buyer)\s*[:\-]?\s*$", l):
            v = _clean_name(next((x for x in lines[i + 1:i + 3] if x), ""))
            if v:
                out.append(v)
    for m in CERTIFY.finditer(t):  # "This is to certify that Mr. X has …"
        v = _clean_name(m.group("v"))
        if v:
            out.append(v)
    for m in re.finditer(r"(?i)certif(?:y|ied)\s+that", t):
        # the name is often printed a few lines below the phrase (after a roll number etc.)
        after = [x.strip() for x in t[m.end():m.end() + 400].splitlines() if x.strip()][:6]
        v = next((c for c in map(_clean_name, after) if c and len(c.split()) >= 2), None)
        if v:
            out.append(v)
    if doc_type in doctypes.tagged("dob"):  # ID cards: the English name is printed on the line just above the date of birth
        for i, l in enumerate(lines):
            if DOB_LINE.search(l):
                prev = next((x for x in reversed(lines[max(0, i - 2):i]) if x), "")
                v = _clean_name(prev)
                if v:
                    out.append(v)
                break
    seen, res = set(), []
    for v in out:
        k = v.lower()
        if k not in seen:
            seen.add(k); res.append(v)
    return res[:4]


def _word_like(a, b):
    if a == b:
        return True
    if min(len(a), len(b)) < 4:
        return False
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8  # small scanning slips (Jon / John)


def entity_in_name(e, holder):
    """Does a written holder name refer to this entity (all its name words present, allowing small slips)?"""
    hw = re.findall(r"[a-z]+", holder.lower())
    words = [w.lower() for w in e.get("text_all", [])] or [w.lower() for w in re.findall(r"[A-Za-z]+", e["name"]) if len(w) > 2]
    return bool(words) and all(any(_word_like(w, x) for x in hw) for w in words)


def _alias_rx(a):
    # "\bdad\b" should also match "Dad1" or "dad_passport": treat digits and _ as separators, not letters
    return rx(a.replace("\\b", "(?<![a-z])", 1)[::-1].replace("b\\", ")]z-a[!?(", 1)[::-1]) if a.startswith("\\b") else None


class Entities:
    """Owner, in this order of evidence:
       1. the holder's name written in the document's name field (Name / Policy holder / Employee name / … or, on ID cards,
          the line above the date of birth) - 'high';
       2. an alias in the file or folder name - 'high';
       3. an organisation or office named in the text (a letterhead) - 'medium'.
       A person merely mentioned somewhere in a document is only a suggestion, never the owner (no owner guessing)."""
    NAME, PLATFORMS, CONTENT = "entities", {"any"}, False
    ORG = ("Organisation", "Office", "Client")

    @staticmethod
    def run(batch, cfg):
        ents = cfg.get("entities", [])
        for r in batch:
            hay = r["path"].lower()
            for root in cfg.roots:
                if hay.startswith(root.lower() + "/"):
                    hay = hay[len(root) + 1:]
            text = (r.get("text") or "")[:50000]
            low = text.lower()
            holders = holder_names(text, r.get("doc_type")) if text else []
            fname = hay.rsplit("/", 1)[-1]
            by_file, by_folder, by_holder, mentioned = [], [], [], []
            for e in ents:
                if hit(hay, e.get("not_if", [])):
                    continue
                al = lambda where: any(((_alias_rx(a) or rx(a)).search(where) if a.startswith("\\b") else a.lower() in where) for a in e.get("aliases", []))
                if al(fname):
                    by_file.append(e)
                elif al(hay):
                    by_folder.append(e)
                if any(entity_in_name(e, h) for h in holders):
                    by_holder.append(e)
                elif low and e.get("text_all") and all(rx(r"\b" + re.escape(w) + r"\b").search(low) for w in e["text_all"]) \
                        and not hit(low, e.get("not_if", [])):
                    mentioned.append(e)
            for lst in (by_file, by_folder):  # a company name beats a person whose alias is part of it
                if len(lst) > 1:
                    orgs = [e for e in lst if e["type"] in Entities.ORG]
                    if len(orgs) == 1:
                        lst[:] = orgs
            is_id = r.get("doc_type") in doctypes.tagged("holder")
            owner = why = conf = None
            hn = {e["name"] for e in by_holder}
            if len(by_holder) == 1 and (not by_file or by_file[0]["name"] in hn):
                owner, why, conf = by_holder[0], "holder's name on the document", "high"
            elif len(by_file) == 1 and (not by_holder or by_file[0]["name"] in hn):
                owner, why, conf = by_file[0], "named in the file name", "high"   # file name and document disagree -> no owner (below)
            elif not by_file and len(by_folder) == 1 and not (is_id and holders and by_folder[0]["name"] not in hn) \
                    and (not by_holder or by_folder[0]["name"] in hn):
                owner, why, conf = by_folder[0], "folder", "high"
            elif not by_file and not by_folder and not by_holder:
                orgs = [e for e in mentioned if e["type"] in Entities.ORG]
                if len(orgs) == 1:
                    owner, why, conf = orgs[0], "organisation named in the document", "medium"
            by_name = by_file + by_folder
            if owner:
                r.update(entity=owner["name"], entity_type=owner["type"], entity_conf=conf, entity_why=why)
            cands = [e["name"] for e in by_holder + by_name + mentioned if not owner or e["name"] != owner["name"]]
            cands = list(dict.fromkeys(cands))
            if cands:
                r["suggestions"] = cands[:5]
            if holders:
                r.setdefault("extra", {})["holder"] = holders


class Topics:
    NAME, PLATFORMS, CONTENT = "topics", {"any"}, False


    @staticmethod
    def run(batch, cfg):
        topics = {t["name"]: t for t in cfg.get("topics", [])}
        for r in batch:
            if r.get("unit") != "file":
                continue
            t = None
            if r.get("doc_type") and (r.get("doc_conf") or "").startswith(("high", "medium")):
                t = cfg.get("doc_type_topics", {}).get(r["doc_type"])
            if not t:
                hay = r["name"].lower() + " " + (r.get("text") or "")[:3000].lower()
                for name, tp in topics.items():
                    if hit(hay, tp["keywords"]):
                        t = name; break
            if t and t in topics:
                r["topic"], r["lifecycle"] = t, topics[t].get("lifecycle")


class Finish:
    NAME, PLATFORMS, CONTENT = "metadata", {"any"}, False
    WS = re.compile(r"\s+")

    @staticmethod
    def run(batch, cfg):
        for r in batch:
            t = r.get("text") or ""
            if t:
                r["snippet"] = Finish.WS.sub(" ", t[:1200]).strip()[:300]
                if not r.get("title"):
                    first = next((l.strip() for l in t.splitlines() if len(l.strip()) > 3), "")
                    r["title"] = first[:120]
            if r.get("tags"):
                r["tags"] = list(dict.fromkeys(r["tags"]))
            if r.get("errs"):
                r["errors"] = "; ".join(r["errs"])
