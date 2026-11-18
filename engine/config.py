"""Profile loading: base.json deep-merged with machine.json. Paths use tokens ({HOME}, {ICLOUD}, {ONEDRIVE}, …) so profiles are portable."""
import os, json, re
from . import platforms

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # program files (replaced on update)
# your data: profile, encrypted catalogue, logs. Same folder as the program unless UO_DATA says otherwise.
DATA = os.path.abspath(os.path.expanduser(os.environ.get("UO_DATA") or ROOT))
HOME = platforms.norm(os.path.expanduser("~"))
TOKENS = {k: platforms.norm(v) for k, v in platforms.tokens().items()}


def _merge(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = _merge(a[k], v) if k in a else v
        return out
    return b


def apply_region(base, name):
    """Add a country pack to the base rules: extra document types (placed before a named one), replaced ones, other settings."""
    if not name or name == "none":
        return base
    p = os.path.join(ROOT, "profiles", "regions", f"{name}.json")
    if not os.path.exists(p):
        raise SystemExit(f"Unknown region '{name}'. Available: " + ", ".join(regions()))
    r = json.load(open(p, encoding="utf-8"))
    out = _merge(base, r.get("set", {}))
    dts = [r.get("doc_types_replace", {}).get(d["name"], d) for d in out["doc_types"]]
    for it in r.get("doc_types_insert", []):
        names = [d["name"] for d in dts]
        i = names.index(it["before"]) if it.get("before") in names else len(dts)
        dts.insert(i, it["type"])
    out["doc_types"] = dts
    if r.get("topic_keywords_extra"):
        out["topic_keywords_extra"] = r["topic_keywords_extra"]
    return out


def regions():
    d = os.path.join(ROOT, "profiles", "regions")
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []


def expand(p):
    return platforms.norm(os.path.normpath(re.sub(r"\{(\w+)\}", lambda m: TOKENS.get(m[1], m[0]), p)))


class Config:
    def __init__(self, machine="machine.json"):
        base = json.load(open(os.path.join(ROOT, "profiles", "base.json"), encoding="utf-8"))
        mpath = os.path.join(DATA, "profiles", machine)
        mach = json.load(open(mpath, encoding="utf-8")) if os.path.exists(mpath) else {}
        self.path = mpath
        self.data = _merge(apply_region(base, mach.get("region", base.get("region"))), mach)
        for t in self.data.get("topics", []):  # region words for the topics (only when the topic has no such word yet)
            extra = self.data.get("topic_keywords_extra", {}).get(t.get("name"), [])
            t["keywords"] = t.get("keywords", []) + [w for w in extra if w not in t.get("keywords", [])]
        d = self.data
        self.roots = [expand(r) for r in d.get("roots", [])]
        self.exclude = [expand(r) for r in d.get("exclude", [])]
        self.protect = [expand(r) for r in d.get("protect", [])]
        self.library = expand(d.get("library", "{HOME}/Documents/Organized"))
        # optional: a folder where every folder directly inside is one project (its index is kept there). Off unless set.
        self.projects_home = expand(d["projects_home"]) if d.get("projects_home") else None
        self.kind_of = {e: k for k, es in d["kinds"].items() for e in es.split()}
        self.text_ext = {m: set(es.split()) for m, es in d["text_extract"].items()}
        self.skip_dirs = set(d["skip_dirs"])
        self.package_exts = set(d["package_exts"])
        self.markers = set(d["project_markers"]) | set(d.get("extra_project_markers", []))
        self.sensitive_rx = re.compile(d["sensitive"]["name_regex"], re.I)
        self.platform = platforms.SYSTEM  # always the real system, so a profile copied from another machine still works
        from . import doctypes
        doctypes.load(d)

    def plugin(self, name):
        return self.data["plugins"].get(name, {"enabled": False})

    def __getitem__(self, k):
        return self.data[k]

    def get(self, k, default=None):
        return self.data.get(k, default)
