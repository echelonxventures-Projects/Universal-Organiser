"""Run a list of small folder steps (mkdir / rename / relink) with a log, and undo them in reverse.
  python3 -I projsteps.py run STEPS.json    -> logs/project-steps-<time>.jsonl
  python3 -I projsteps.py undo LOG.jsonl
Steps: {"op":"mkdir","path"} {"op":"rename","from","to"} {"op":"relink","path","to"}  (relink: an existing link gets a new target)
Every step is checked first; the run stops at the first problem, leaving the log of what was done."""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.abspath(os.path.expanduser(os.environ.get("UO_DATA") or ROOT))


def do(s):
    op = s["op"]
    if op == "mkdir":
        os.mkdir(s["path"])
    elif op == "rename":
        if os.path.lexists(s["to"]): raise OSError("already exists: " + s["to"])
        if os.stat(s["from"], follow_symlinks=False).st_dev != os.stat(os.path.dirname(s["to"])).st_dev: raise OSError("different disk")
        os.rename(s["from"], s["to"])
    elif op == "relink":
        if not os.path.islink(s["path"]): raise OSError("not a link: " + s["path"])
        s["was"] = os.readlink(s["path"]); os.unlink(s["path"]); os.symlink(s["to"], s["path"])
    elif op == "unlink":
        if not os.path.islink(s["path"]): raise OSError("not a link: " + s["path"])
        s["was"] = os.readlink(s["path"]); os.unlink(s["path"])
    elif op == "link":
        os.symlink(s["to"], s["path"])
    else:
        raise OSError("unknown step")


def undo_one(s):
    op = s["op"]
    if op == "mkdir": os.rmdir(s["path"])
    elif op == "rename":
        if os.path.lexists(s["from"]): raise OSError("old place occupied: " + s["from"])
        os.rename(s["to"], s["from"])
    elif op == "relink": os.unlink(s["path"]); os.symlink(s["was"], s["path"])
    elif op == "unlink": os.symlink(s["was"], s["path"])
    elif op == "link": os.unlink(s["path"])


if __name__ == "__main__":
    cmd, arg = sys.argv[1], sys.argv[2]
    if cmd == "run":
        log = os.path.join(DATA, "logs", time.strftime("project-steps-%Y%m%d-%H%M%S.jsonl"))
        for s in json.load(open(arg)):
            do(s)
            with open(log, "a") as f: f.write(json.dumps({**s, "t": time.time()}) + "\n")
        print("done; undo log:", log)
    else:
        for s in reversed([json.loads(l) for l in open(arg) if l.strip()]):
            undo_one(s); print("undone:", s["op"], s.get("from") or s.get("path"))
