#!/usr/bin/env python3
"""Stops personal data from reaching the repository.

  python3 tools/privacy_check.py            check the files staged for a commit (used by the git hooks)
  python3 tools/privacy_check.py --all      check every file in the repository

It blocks: private keys and tokens; profiles, catalogues, logs and certificates; and, when this computer has a real
install, the people, organisations and profile name in its machine profile, your login name and home folder, your git
e-mail and this computer's network address. Those words are read at check time from your own files; they are never
written into the repository. Extra words: one per line in ~/.config/universal-organiser/privacy-words.txt.
"""
import fnmatch, getpass, glob, json, os, re, socket, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = os.path.expanduser("~")

NEVER_PATHS = ["profiles/machine.json", "profiles/versions/*", "vault/*", "vault.sparsebundle/*", "catalogue/*", "logs/*",
               "exports/*", "agent/*"]
NEVER_NAMES = ["*.sparsebundle", "*.pem", "*.key", "*.crt", "*.p12", "*.db", "*.db-wal", "*.db-shm", "*.jsonl", ".env", "*.env",
               "catalogue.db"]
SECRETS = [
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----", "a private key"),
    (r"\bAKIA[0-9A-Z]{16}\b", "an AWS access key"),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}\b", "a GitHub token"),
    (r"\bxox[abpr]-[A-Za-z0-9-]{10,}", "a Slack token"),
    (r"\bsk-[A-Za-z0-9_-]{32,}", "an API key"),
]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_OK = re.compile(r"(?i)@(example\.(com|org|net)|users\.noreply\.github\.com|anthropic\.com)$|^noreply@|^security@")
COMMON = set("""self family friend office organisation client property vehicle media home main test name type admin member
user users documents desktop downloads files photos music movies library mobile other others general misc school college bank
""".split())


def _profiles():
    cands = [os.environ.get("UO_PRIVACY_PROFILE", "")]
    for base in (os.path.join(H, "Library", "Application Support"), os.environ.get("LOCALAPPDATA", ""),
                 os.environ.get("XDG_DATA_HOME") or os.path.join(H, ".local", "share")):
        if base:
            cands += glob.glob(os.path.join(base, "*", "profiles", "machine.json"))
    return [p for p in cands if p and os.path.exists(p) and not os.path.realpath(p).startswith(os.path.realpath(ROOT) + os.sep)]


def personal_words():
    words = set()
    for p in _profiles():
        try:
            m = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for e in m.get("entities", []):
            name = re.sub(r"\(.*?\)", "", e.get("name", "")).strip()
            words.add(name)
            if e.get("type") in ("Self", "Family", "Friend"):  # a person's first and last names on their own too
                words.update(x for x in name.split() if len(x) >= 4)
            for a in e.get("aliases", []):
                words.add(re.sub(r"\\b|[\\^$()|?*+\[\]]", "", str(a)).strip())
        if m.get("profile"):
            words.add(str(m["profile"]))
    user = getpass.getuser()
    if user and len(user) >= 3:
        words.add(user)
    f = os.path.join(H, ".config", "universal-organiser", "privacy-words.txt")
    if os.path.exists(f):
        words.update(l.strip() for l in open(f, encoding="utf-8") if l.strip() and not l.startswith("#"))
    shipped = _shipped_vocabulary()
    return {w for w in words if len(w) >= 3 and w.lower() not in COMMON and w.lower() not in shipped}


def _shipped_vocabulary():
    """Words that are part of the generic rules (document types, topics, presets) are not personal."""
    voc = set()
    for p in [os.path.join(ROOT, "profiles", "base.json")] + glob.glob(os.path.join(ROOT, "profiles", "regions", "*.json")) \
            + glob.glob(os.path.join(ROOT, "profiles", "presets", "*.json")):
        try:
            t = open(p, encoding="utf-8").read().lower()
        except OSError:
            continue
        voc.update(re.findall(r"[a-z0-9][a-z0-9 &/.-]*[a-z0-9]", re.sub(r"\\\\b", " ", t)))
        voc.update(re.findall(r"[a-z0-9]+", t))
    return voc


def literal_values():
    vals = {H: "your home folder path"}
    try:
        em = subprocess.run(["git", "config", "user.email"], capture_output=True, text=True, timeout=5).stdout.strip()
        if em:
            vals[em] = "your git e-mail"
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("192.0.2.1", 9)); ip = s.getsockname()[0]; s.close()
        if not ip.startswith("127."):
            vals[ip] = "this computer's network address"
    except OSError:
        pass
    return vals


def files(all_files):
    if os.path.isdir(os.path.join(ROOT, ".git")):
        cmd = ["git", "-C", ROOT, "ls-files", "--cached", "--others", "--exclude-standard"] if all_files else \
              ["git", "-C", ROOT, "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
        return [l for l in subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines() if l]
    out = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in (".git", "__pycache__")]
        out += [os.path.relpath(os.path.join(dp, f), ROOT) for f in fn]
    return out


def check(paths):
    words = personal_words()
    wrx = re.compile(r"(?i)(?<![A-Za-z])(" + "|".join(sorted(map(re.escape, words), key=len, reverse=True)) + r")(?![A-Za-z])") if words else None
    lits = literal_values()
    probs = []
    for rel in paths:
        r = rel.replace("\\", "/")
        if any(fnmatch.fnmatch(r, pat) for pat in NEVER_PATHS) or any(fnmatch.fnmatch(os.path.basename(r), pat) for pat in NEVER_NAMES):
            probs.append((rel, 0, "this kind of file holds personal data and must never be committed"))
            continue
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p) or os.path.getsize(p) > 5_000_000 or r == "tools/privacy_check.py":
            continue
        try:
            text = open(p, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for rx, what in SECRETS:
                if re.search(rx, line):
                    probs.append((rel, i, what))
            for v, what in lits.items():
                if v and v in line:
                    probs.append((rel, i, what))
            for em in EMAIL.findall(line):
                if not EMAIL_OK.search(em) and not em.endswith((".png", ".jpg")):
                    probs.append((rel, i, f"an e-mail address ({em})"))
            if wrx:
                m = wrx.search(line)
                if m:
                    probs.append((rel, i, f"a personal name or word from your own profile (“{m[1]}”)"))
    return probs


def main():
    all_files = "--all" in sys.argv
    probs = check(files(all_files))
    if not probs:
        print("privacy check: nothing personal found")
        return 0
    print("privacy check: these must not go into the repository:")
    for rel, i, what in probs[:200]:
        print(f"  {rel}{':' + str(i) if i else ''}  {what}")
    print("Remove them (use neutral examples such as “Alex Example”), then try again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
