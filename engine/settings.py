"""Settings editing for the local page. Only the machine profile is edited (base.json stays the shared, generic
default). Every save keeps the previous file in profiles/versions/ so it can be restored.
Fixed by design and not editable here: cloud AI (always 'never'), removing a protected folder, read-only mode."""
import os, re, json, time, shutil
from .config import ROOT, DATA, expand

PDIR = os.path.join(DATA, "profiles")  # your profile and its versions
MACHINE = os.path.join(PDIR, "machine.json")
VERSIONS = os.path.join(PDIR, "versions")
BASE = os.path.join(ROOT, "profiles", "base.json")  # shipped defaults
FIXED_PLUGINS = {"metadata": "always on", "hash": "always on",
                 }
PLUGIN_LABELS = {"metadata": "File details", "hash": "Identical-copy detection", "text": "Text from PDF / Office / web pages",
                 "archive": "List what is inside zip / rar / 7z", "image_meta": "Photo details (camera, date, size)",
                 "ocr": "Read text in images and scans", "image_classify": "Recognise what a photo shows",
                 "faces": "Count faces (suggestions only)", "transcribe": "Audio / video transcripts",
                 "doc_type": "Detect document type", "entities": "Detect owner", "topics": "Detect topic",
                 "near_duplicate_photos": "Similar-photo grouping"}


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def current(cfg):
    """Everything the settings page shows: editable values + the choices around them."""
    base, mach = _load(BASE), _load(MACHINE)
    d = cfg.data
    plugins = []
    for k, v in base["plugins"].items():
        plugins.append({"key": k, "label": PLUGIN_LABELS.get(k, k), "enabled": bool(cfg.plugin(k).get("enabled")),
                        "fixed": FIXED_PLUGINS.get(k), "mode": cfg.plugin(k).get("mode")})
    ai = d["engine"]["ai"]
    return {
        "values": {
            "entity_types": d.get("entity_types", []),
            "entities": d.get("entities", []),
            "topics": d.get("topics", []),
            "doc_type_topics": d.get("doc_type_topics", {}),
            "layout_preset": d.get("layout_preset", ""),
            "naming_preset": d.get("naming_preset", "original"),
            "group_labels": d.get("group_labels", {}),
            "roots": mach.get("roots", []), "exclude": mach.get("exclude", []), "protect": mach.get("protect", []),
            "plugins": {p["key"]: p["enabled"] for p in plugins},
            "ollama": {"enabled": bool(ai["ollama"].get("enabled")), "model": ai["ollama"].get("model", "")},
        },
        "choices": {
            "lifecycles": list(d.get("lifecycles", {}).keys()),
            "doc_types": [r["name"] for r in d.get("doc_types", [])],
            "layouts": d["presets"]["layouts"], "naming": d["presets"]["naming"],
            "plugins": plugins, "cloud_ai": ai.get("cloud", "never"), "apple_ai": bool(ai.get("apple_builtin")),
            "profile": d.get("profile"), "platform": cfg.platform,
            "tokens": {"{" + k + "}": v for k, v in __import__("engine.config", fromlist=["TOKENS"]).TOKENS.items()},
        },
    }


def _rx_ok(p, where, errs):
    try:
        re.compile(p, re.I)
    except re.error as e:
        errs.append(f"{where}: pattern “{p}” is not valid ({e}).")


def _strs(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def validate(new, cfg):
    errs, base = [], _load(BASE)
    types = new.get("entity_types") or []
    if not _strs(types) or not types or len(set(types)) != len(types):
        errs.append("Owner types: need a list of unique names.")
    names = set()
    for i, e in enumerate(new.get("entities", [])):
        n = (e.get("name") or "").strip()
        w = f"Owner “{n or '#' + str(i + 1)}”"
        if not n:
            errs.append(f"Owner #{i + 1}: name is empty."); continue
        if n.lower() in names:
            errs.append(f"{w}: listed twice.")
        names.add(n.lower())
        if e.get("type") not in types:
            errs.append(f"{w}: type “{e.get('type')}” is not one of the owner types.")
        for k in ("aliases", "text_all", "not_if"):
            if not _strs(e.get(k, [])):
                errs.append(f"{w}: {k} must be a list of words.")
        if not e.get("aliases") and not e.get("text_all"):
            errs.append(f"{w}: give at least one name word or content word, otherwise nothing can match.")
        for a in e.get("aliases", []):
            if len(a.strip()) < 3 and not a.startswith("\\b"):
                errs.append(f"{w}: name word “{a}” is too short (it would match inside other words).")
            if a.startswith("\\b"):
                _rx_ok(a, w, errs)
        for p in e.get("not_if", []):
            _rx_ok(p, w, errs)
    lifes = set(cfg.get("lifecycles", {}))
    tnames = set()
    for t in new.get("topics", []):
        n = (t.get("name") or "").strip()
        if not n:
            errs.append("A topic has no name."); continue
        if n in tnames:
            errs.append(f"Topic “{n}”: listed twice.")
        tnames.add(n)
        if t.get("lifecycle") not in lifes:
            errs.append(f"Topic “{n}”: lifecycle must be one of {', '.join(sorted(lifes))}.")
        if not _strs(t.get("keywords", [])):
            errs.append(f"Topic “{n}”: keywords must be a list.")
        for k in t.get("keywords", []):
            _rx_ok(k, f"Topic “{n}”", errs)
    dts = {r["name"] for r in cfg.get("doc_types", [])}
    for k, v in (new.get("doc_type_topics") or {}).items():
        if k not in dts:
            errs.append(f"Document type “{k}” does not exist.")
        if v and v not in tnames:
            errs.append(f"Document type “{k}” points to topic “{v}”, which does not exist.")
    if new.get("layout_preset") not in cfg["presets"]["layouts"]:
        errs.append("Choose one of the layout presets.")
    if new.get("naming_preset") not in cfg["presets"]["naming"]:
        errs.append("Choose one of the naming presets.")
    for k in ("roots", "exclude", "protect"):
        if not _strs(new.get(k, [])):
            errs.append(f"{k}: must be a list of folder paths.")
    for p in new.get("roots", []):
        if not os.path.isdir(expand(p)):
            errs.append(f"Folder to scan “{p}” does not exist on this computer.")
    old_protect = {expand(p) for p in _load(MACHINE).get("protect", [])}
    gone = old_protect - {expand(p) for p in new.get("protect", [])}
    if gone:
        errs.append("Protected folders cannot be removed from this page (removed: " + ", ".join(sorted(gone)) + ").")
    for k, v in (new.get("plugins") or {}).items():
        if k not in base["plugins"]:
            errs.append(f"Unknown plug-in “{k}”.")
        elif k in FIXED_PLUGINS and bool(v) != bool(cfg.plugin(k).get("enabled")):
            errs.append(f"Plug-in “{PLUGIN_LABELS.get(k, k)}” is {FIXED_PLUGINS[k]} and cannot be changed yet.")
    o = new.get("ollama") or {}
    if o.get("enabled") and not re.fullmatch(r"[\w.:/-]{1,80}", o.get("model") or ""):
        errs.append("Local AI (Ollama): give a model name, e.g. llama3.2:3b.")
    return errs


def _named(lst):
    return {x.get("name"): x for x in lst or []}


def diff(new, cfg):
    old = current(cfg)["values"]
    out = []
    for key, label in (("entities", "Owner"), ("topics", "Topic")):
        a, b = _named(old[key]), _named(new.get(key))
        out += [f"{label} added: {n}" for n in b if n not in a]
        out += [f"{label} removed: {n}" for n in a if n not in b]
        for n in b:
            if n in a and a[n] != b[n]:
                ch = [k for k in set(a[n]) | set(b[n]) if a[n].get(k) != b[n].get(k)]
                out.append(f"{label} changed: {n} ({', '.join(sorted(ch))})")
    for key, label in (("entity_types", "Owner type"), ("roots", "Folder to scan"), ("exclude", "Folder to skip"), ("protect", "Protected folder")):
        a, b = old[key], new.get(key, [])
        out += [f"{label} added: {x}" for x in b if x not in a] + [f"{label} removed: {x}" for x in a if x not in b]
    for k in set(old["doc_type_topics"]) | set(new.get("doc_type_topics", {})):
        x, y = old["doc_type_topics"].get(k), new.get("doc_type_topics", {}).get(k)
        if x != y:
            out.append(f"Document type “{k}” → topic: {x or 'by keywords'} ⟶ {y or 'by keywords'}")
    for k in set(old["group_labels"]) | set(new.get("group_labels", {})):
        x, y = old["group_labels"].get(k), new.get("group_labels", {}).get(k)
        if x != y:
            out.append(f"Folder label for {k}: {x or '—'} ⟶ {y or '—'}")
    for k, label in (("layout_preset", "Layout"), ("naming_preset", "File naming")):
        if old[k] != new.get(k):
            out.append(f"{label}: {old[k]} ⟶ {new.get(k)}")
    for k, v in (new.get("plugins") or {}).items():
        if bool(old["plugins"].get(k)) != bool(v):
            out.append(f"Plug-in {PLUGIN_LABELS.get(k, k)}: {'on' if v else 'off'}")
    if old["ollama"] != new.get("ollama", old["ollama"]):
        o = new["ollama"]
        out.append(f"Local AI (Ollama): {'on, model ' + o.get('model', '') if o.get('enabled') else 'off'}")
    return out


def save(new, by):
    """Write the machine profile. Keeps the old one in versions/. Returns the version name of the old copy."""
    os.makedirs(VERSIONS, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    keep = os.path.join(VERSIONS, f"machine-{stamp}.json")
    shutil.copy2(MACHINE, keep)
    base, m = _load(BASE), _load(MACHINE)
    for k in ("entity_types", "entities", "topics", "doc_type_topics", "layout_preset", "naming_preset", "group_labels",
              "roots", "exclude", "protect"):
        if k in new:
            m[k] = new[k]
    if m.get("entity_types") == base.get("entity_types"):
        m.pop("entity_types", None)
    plug = m.setdefault("plugins", {})
    for k, v in (new.get("plugins") or {}).items():
        if k in FIXED_PLUGINS:
            continue
        if bool(v) == bool(base["plugins"][k].get("enabled")):
            plug.get(k, {}).pop("enabled", None)
            if not plug.get(k):
                plug.pop(k, None)
        else:
            plug.setdefault(k, {})["enabled"] = bool(v)
    if not plug:
        m.pop("plugins", None)
    if "ollama" in new:
        ol = m.setdefault("engine", {}).setdefault("ai", {}).setdefault("ollama", {})
        ol["enabled"], ol["model"] = bool(new["ollama"].get("enabled")), new["ollama"].get("model", "")
    m["_saved"] = {"by": by, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    tmp = MACHINE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MACHINE)
    return os.path.basename(keep)


def versions():
    if not os.path.isdir(VERSIONS):
        return []
    out = []
    for n in sorted((x for x in os.listdir(VERSIONS) if x.startswith("machine-") and x.endswith(".json")), reverse=True):
        try:
            s = _load(os.path.join(VERSIONS, n)).get("_saved", {})
        except ValueError:
            s = {}
        out.append({"name": n, "at": n[8:23], "by": s.get("by")})
    return out[:50]


def restore(name, by):
    if not re.fullmatch(r"machine-\d{8}-\d{6}\.json", name or ""):
        raise ValueError("bad version name")
    src = os.path.join(VERSIONS, name)
    old = _load(src)
    kept = save({}, by)  # keeps today's file as a version first
    old["_saved"] = {"by": by, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "restored_from": name}
    with open(MACHINE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, indent=2)
    os.replace(MACHINE + ".tmp", MACHINE)
    return kept
