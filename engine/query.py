"""Forgiving, plain-language search.

parse("Sam insurance 2023") -> owner Sam (labelled, or their name in the text) + topic Insurance + year 2023.
Remaining words are matched with spelling variants taken from the catalogue's own vocabulary:
  - a sounds-alike key (aa/a, ee/i, w/v, sh/s, ph/f, double letters…) for romanised Hindi and Indian English spellings
  - a small typo distance for words that are rare or missing
  - synonyms from the profile (search.synonyms)
Every filter is "soft": a labelled file OR a file whose text says it, so unlabelled files are still found (labelled first)."""
import re, time, difflib, datetime
from collections import defaultdict

WORD = re.compile(r"[\wऀ-ॿ]+", re.U)


def phonetic(w):
    w = w.lower()
    for a, b in (("aa", "a"), ("ee", "i"), ("ii", "i"), ("oo", "u"), ("ou", "u"), ("w", "v"), ("ph", "f"), ("sh", "s"), ("ch", "c"),
                 ("z", "j"), ("q", "k"), ("ck", "k"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"), ("gh", "g"), ("y", "i")):
        w = w.replace(a, b)
    w = re.sub(r"(.)\1+", r"\1", w)          # double letters
    w = re.sub(r"(?<=[^aeiou])h", "", w)     # aspirated consonants
    return w.rstrip("aeh") or w


class Vocab:
    """The catalogue's own words, refreshed after each scan."""
    def __init__(self):
        self.stamp, self.freq, self.by_key, self.by_bucket = None, {}, defaultdict(list), defaultdict(list)

    def ensure(self, cat):
        stamp = (cat.get_meta("last_scan") or {}).get("at"), cat.db.execute("SELECT max(id) FROM files").fetchone()[0]
        if stamp == self.stamp and self.freq:
            return self
        cat.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.fts_vocab USING fts5vocab(main, 'fts', 'row')")
        freq = {t: n for t, n in cat.db.execute("SELECT term, doc FROM temp.fts_vocab WHERE length(term) BETWEEN 3 AND 24 AND term GLOB '[a-z]*' "
                                                "AND term NOT GLOB '*[0-9]*'")}
        by_key, by_bucket = defaultdict(list), defaultdict(list)
        for t in freq:
            by_key[phonetic(t)].append(t)
            by_bucket[(t[0], len(t))].append(t)
        self.freq, self.by_key, self.by_bucket, self.stamp = freq, by_key, by_bucket, stamp
        return self

    def variants(self, w, limit=5):
        """Other spellings of `w` that really occur in your files (most common first)."""
        w = w.lower()
        if len(w) < 3 or not w.isascii() or not w.isalpha():
            return []
        english = w in dictionary() or w.rstrip("s") in dictionary()
        out = set() if english else set(self.by_key.get(phonetic(w), []))
        if self.freq.get(w, 0) < 3:  # rare or missing: allow a typo
            pool = []
            for L in range(len(w) - 1, len(w) + 2):
                pool += [t for t in self.by_bucket.get((w[0], L), []) if self.freq.get(t, 0) >= 2]
            out |= set(difflib.get_close_matches(w, pool, n=4, cutoff=0.86 if len(w) <= 6 else 0.82))
        out.discard(w)
        return sorted(out, key=lambda t: -self.freq.get(t, 0))[:limit]


_DICT = None


def dictionary():
    """Ordinary English words (system word list). Sounds-alike spellings are for names and romanised Hindi, not for these."""
    global _DICT
    if _DICT is None:
        import os
        _DICT = set()
        for p in ("/usr/share/dict/words", "/usr/share/dict/american-english"):
            if os.path.exists(p):
                with open(p, errors="ignore") as f:
                    _DICT = {w.strip().lower() for w in f}
                break
    return _DICT


VOCAB = Vocab()


def _fts_term(words):
    """FTS5 expression for one search word and its variants."""
    alts = list(dict.fromkeys(w.replace('"', "") for w in words if w))
    return "(" + " OR ".join(f'"{a}"*' for a in alts) + ")" if len(alts) > 1 else f'"{alts[0]}"*'


def parse(cfg, cat, q, ignore=()):
    """Turn a typed query into soft filters + a forgiving text match. Returns where/params/boost/chips/fts."""
    sc = cfg.get("search", {})
    words = [w for w in WORD.findall(q or "")]
    low = [w.lower() for w in words]
    used = [False] * len(words)
    where, params, boost, bparams, chips = [], [], [], [], []
    ents = cfg.get("entities", [])
    syn = {k.lower(): [x.lower() for x in v] for k, v in (sc.get("synonyms") or {}).items()}

    def mark(i, n=1):
        for k in range(i, i + n):
            used[k] = True

    def fts_rows(expr):
        return "f.id IN (SELECT rowid FROM fts WHERE fts MATCH ?)", expr

    # year / financial year ("2023", "2024-25", "this year", "last year")
    if "year" not in ignore:
        ys = cfg.get("insights", {}).get("year_start_month", 1)
        for i, w in enumerate(low):
            m = re.fullmatch(r"(19|20)(\d\d)", w)
            if m and not used[i]:
                nxt = low[i + 1] if i + 1 < len(low) else ""
                if re.fullmatch(r"\d\d", nxt) and int(nxt) == (int(w) + 1) % 100 and ys != 1:
                    a = datetime.date(int(w), ys, 1); b = datetime.date(int(w) + 1, ys, 1)
                    where.append("f.date >= ? AND f.date < ?"); params += [a.isoformat(), b.isoformat()]
                    chips.append({"kind": "year", "label": f"Year {w}-{nxt}"}); mark(i, 2)
                else:
                    where.append("f.year = ?"); params.append(w); chips.append({"kind": "year", "label": f"Year {w}"}); mark(i)
                break
        this = datetime.date.today().year
        for i in range(len(low) - 1):
            if not used[i] and low[i] in ("this", "last") and low[i + 1] == "year":
                y = str(this if low[i] == "this" else this - 1)
                where.append("f.year = ?"); params.append(y); chips.append({"kind": "year", "label": f"Year {y}"}); mark(i, 2)
                break
    # owner: first names, full names, aliases (mum, dad…), "my"/"mine" = yourself
    if "owner" not in ignore:
        for e in ents:
            keys = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", e["name"]) if w.lower() not in ("late",)}
            keys |= {re.sub(r"\\b|[^a-z ]", "", a.lower()).strip() for a in e.get("aliases", [])}
            if e.get("type") == "Self":
                keys |= {"my", "mine", "me", "self"}
            hit = [i for i, w in enumerate(low) if not used[i] and w in keys]
            if hit:
                words_txt = " AND ".join(f'"{w}"' for w in (e.get("text_all") or [hit and low[hit[0]]]))
                cond, expr = fts_rows(words_txt)
                where.append(f"(f.entity = ? OR (f.entity IS NULL AND {cond}))"); params += [e["name"], expr]
                boost.append("CASE WHEN f.entity = ? THEN 0 ELSE 1 END"); bparams.append(e["name"])
                chips.append({"kind": "owner", "label": e["name"]})
                for i in hit:
                    mark(i)
                break
    # document type / topic words
    if "type" not in ignore:
        dmap = {k.lower(): v for k, v in (sc.get("doc_type_words") or {}).items()}
        for i, w in enumerate(low):
            if not used[i] and w in dmap:
                dt = dmap[w]
                alts = [w] + VOCAB.variants(w, 3) + [x.lower() for x in (sc.get("synonyms") or {}).get(w, [])]
                cond, expr = fts_rows(_fts_term(alts))
                where.append(f"(f.doc_type = ? OR {cond})"); params += [dt, expr]
                boost.append("CASE WHEN f.doc_type = ? THEN 0 ELSE 1 END"); bparams.append(dt)
                chips.append({"kind": "type", "label": dt}); mark(i)
                break
    if "topic" not in ignore:
        tops = {}
        for t in cfg.get("topics", []):
            for part in re.findall(r"[A-Za-z]{3,}", t["name"]):
                if part.lower() not in ("and", "the", "work", "finance"):
                    tops.setdefault(part.lower(), t["name"])
        for i, w in enumerate(low):
            if not used[i] and (w in tops or w.rstrip("s") in tops):
                tn = tops.get(w) or tops[w.rstrip("s")]
                cond, expr = fts_rows(_fts_term([w] + VOCAB.variants(w, 3) + syn.get(w, []) + syn.get(w.rstrip("s"), [])))
                where.append(f"(f.topic = ? OR f.topic LIKE ? OR {cond})"); params += [tn, tn + "/%", expr]
                boost.append("CASE WHEN f.topic = ? THEN 0 ELSE 1 END"); bparams.append(tn)
                chips.append({"kind": "topic", "label": tn}); mark(i)
                break
    # remaining words: forgiving text match
    terms, also = [], []
    stop = {"the", "and", "of", "for", "all", "show", "find", "files", "file", "documents", "document", "my"} if any(used) else set()
    for i, w in enumerate(low):
        if used[i] or w in stop:
            continue
        v = VOCAB.variants(w) if "spelling" not in ignore else []
        s = syn.get(w, [])
        also += v + s
        terms.append(_fts_term([w] + v + s))
    return {"where": where, "params": params, "boost": boost, "bparams": bparams, "chips": chips,
            "fts": " AND ".join(terms), "also": list(dict.fromkeys(also))[:12]}
