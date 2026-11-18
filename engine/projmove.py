"""Move chosen projects into a projects home, leaving a signpost link at the old place.

  python3 -I projmove.py preview PLAN.json     show what would happen, change nothing
  python3 -I projmove.py run PLAN.json         move; writes logs/project-move-<time>.jsonl
  python3 -I projmove.py undo LOG.jsonl        put everything back exactly

PLAN.json: {"home": "~/Desktop/Projects", "moves": [{"src": "...", "subject": "Web", "name": "my-shop"}]}
A move is one rename on the same disk (nothing is copied, nothing can be half-moved).
Refuses: destination exists, different disk, source is a link, a program has files open in the project.
"""
import json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.abspath(os.path.expanduser(os.environ.get("UO_DATA") or ROOT))
X = os.path.expanduser


def open_paths():
    try:
        out = subprocess.run(["lsof", "-Fn"], capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return None
    return {l[1:] for l in out.splitlines() if l.startswith("n/")}


def check(plan):
    home = X(plan["home"]); used = open_paths(); rows = []; seen = set()
    hd = os.stat(os.path.dirname(home)).st_dev
    for m in plan["moves"]:
        src = X(m["src"]).rstrip("/"); dest = os.path.join(home, m["subject"], m["name"]); why = ""
        if os.path.islink(src): why = "source is a link"
        elif not os.path.isdir(src): why = "source not found"
        elif os.path.lexists(dest) or dest in seen: why = "destination already exists"
        elif os.stat(src).st_dev != hd: why = "different disk"
        elif used is None: why = "could not check open files"
        elif any(p == src or p.startswith(src + "/") for p in used): why = "in use by a running program"
        seen.add(dest); rows.append({"src": src, "dest": dest, "skip": why})
    return rows


def run(plan, do):
    rows = check(plan); log = None
    if do:
        os.makedirs(os.path.join(DATA, "logs"), exist_ok=True)
        log = os.path.join(DATA, "logs", time.strftime("project-move-%Y%m%d-%H%M%S.jsonl"))
    for r in rows:
        if r["skip"]:
            print(f"SKIP  {r['src']}  ({r['skip']})"); continue
        if not do:
            print(f"MOVE  {r['src']}\n   -> {r['dest']}"); continue
        made = []
        d = os.path.dirname(r["dest"])
        while not os.path.isdir(d):
            made.append(d); d = os.path.dirname(d)
        os.makedirs(os.path.dirname(r["dest"]), exist_ok=True)
        os.rename(r["src"], r["dest"])
        link = False
        try:
            os.symlink(r["dest"], r["src"]); link = True
        except OSError as e:
            print(f"   (no signpost link: {e})")
        with open(log, "a") as f:
            f.write(json.dumps({"src": r["src"], "dest": r["dest"], "link": link, "made": made, "t": time.time()}) + "\n")
        print(f"MOVED {r['src']}\n   -> {r['dest']}")
    if log and os.path.exists(log): print("undo log:", log)


def undo(log):
    for r in reversed([json.loads(l) for l in open(log) if l.strip()]):
        if not os.path.isdir(r["dest"]) or os.path.islink(r["dest"]):
            print("SKIP (not where it was put):", r["dest"]); continue
        if os.path.islink(r["src"]): os.unlink(r["src"])
        if os.path.lexists(r["src"]):
            print("SKIP (old place is occupied):", r["src"]); continue
        os.rename(r["dest"], r["src"]); print("BACK ", r["src"])
        for d in r.get("made", []):
            try: os.rmdir(d)
            except OSError: pass


if __name__ == "__main__":
    cmd, arg = sys.argv[1], sys.argv[2]
    if cmd == "undo": undo(arg)
    else: run(json.load(open(arg)), cmd == "run")
