"""Index of the projects home: one entry per folder directly inside it.

Writes two files into the projects home (rewritten each time, nothing else is touched):
  INDEX.md              plain text, for editors and AI tools
  Projects Index.html   the same, for double-click in Finder
Per project: what it is (README title / package description), its parts, technology, git state, last change,
size, working status, and where it lived before it was moved here. Read-only apart from the two index files."""
import os, re, json, time, html, subprocess, shutil, glob

SKIP = {"node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", "target", ".turbo", ".cache", ".git", ".nx"}
MARK = ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml", "pom.xml", "composer.json", "docker-compose.yml", "Dockerfile")
NAMES = ("INDEX.md", "Projects Index.html")


def _git(p, *a):
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", p, *a], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _git_info(p):
    if not os.path.exists(os.path.join(p, ".git")) or not shutil.which("git"):
        return None
    n = _git(p, "rev-list", "--count", "HEAD")
    if not n:
        return {"broken": True}
    remote = re.sub(r"//[^/@]+@", "//", _git(p, "remote", "get-url", "origin"))  # never show stored credentials
    return {"commits": int(n), "branch": _git(p, "branch", "--show-current"), "last": _git(p, "log", "-1", "--format=%cs"),
            "remote": remote, "dirty": len(_git(p, "status", "--porcelain", "-uno").splitlines())}


def _pkg(p):
    try:
        return json.load(open(os.path.join(p, "package.json"), encoding="utf-8"))
    except Exception:
        return {}


def _about(p):
    for n in sorted(os.listdir(p)):
        if n.lower().startswith("readme") and "(" not in n and os.path.isfile(os.path.join(p, n)):
            try:
                for line in open(os.path.join(p, n), encoding="utf-8", errors="ignore").read(4000).splitlines():
                    t = re.sub(r"[#*_`>\[\]]|<[^>]+>|!\(.*?\)", "", line).strip()
                    if len(t) > 3 and not t.startswith(("http", "![", "---", "===")):
                        return t[:140]
            except OSError:
                pass
    k = _pkg(p)
    return (k.get("description") or (("package “%s”" % k["name"]) if k.get("name") else ""))[:140]


def _tech(p):
    t, names = [], set(os.listdir(p))
    k = _pkg(p); deps = {**k.get("dependencies", {}), **k.get("devDependencies", {})}
    if "package.json" in names:
        fw = [lbl for key, lbl in (("next", "Next.js"), ("react", "React"), ("vue", "Vue"), ("@angular/core", "Angular"), ("express", "Express"),
                                   ("@nestjs/core", "NestJS"), ("fastify", "Fastify"), ("electron", "Electron"), ("vite", "Vite"), ("prisma", "Prisma"),
                                   ("typescript", "TypeScript")) if key in deps]
        t.append("Node.js" + (" (" + ", ".join(fw[:4]) + ")" if fw else ""))
    if names & {"pyproject.toml", "requirements.txt", "setup.py", "Pipfile"}: t.append("Python")
    if "go.mod" in names: t.append("Go")
    if "Cargo.toml" in names: t.append("Rust")
    if names & {"pom.xml", "build.gradle"}: t.append("Java")
    if "composer.json" in names or sum(n.endswith(".php") for n in names) >= 3: t.append("PHP")
    if names & {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}: t.append("Docker")
    return t


def _measure(p):
    """-> files, bytes, newest change (all without libraries/build output), and the bytes of that rebuildable part."""
    n = size = newest = reb = 0
    for dp, dn, fn in os.walk(p):
        for d in dn:
            if d in SKIP and d != ".git" and not os.path.islink(os.path.join(dp, d)):
                for dp2, _, fn2 in os.walk(os.path.join(dp, d)):
                    for f in fn2:
                        try:
                            reb += os.lstat(os.path.join(dp2, f)).st_size
                        except OSError:
                            pass
        dn[:] = [d for d in dn if d not in SKIP and not os.path.islink(os.path.join(dp, d))]
        for f in fn:
            if f == ".DS_Store": continue
            try:
                st = os.lstat(os.path.join(dp, f))
            except OSError:
                continue
            n += 1; size += st.st_size; newest = max(newest, st.st_mtime)
    return n, size, newest, reb


def _origins(root):
    """old place -> present place, from the signpost links recorded in the move logs."""
    o = {}
    for f in sorted(glob.glob(os.path.join(root, "logs", "project-move-*.jsonl"))):
        for l in open(f):
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if os.path.islink(d["src"]):
                o[os.readlink(d["src"])] = d["src"]
    return o


def build(cfg, cat=None):
    from .config import DATA as ROOT
    home = cfg.projects_home
    if not home or not os.path.isdir(home):
        return None
    status = {}
    if cat is not None:
        try:
            status = dict(cat.db.execute("SELECT path, status FROM project_status"))
        except Exception:
            pass
    orig, H, out = _origins(ROOT), os.path.expanduser("~"), []
    for name in sorted(os.listdir(home), key=str.lower):
        p = os.path.join(home, name)
        if name.startswith(".") or not os.path.isdir(p) or os.path.islink(p):
            continue
        n, size, newest, reb = _measure(p)
        parts = []
        for sub in sorted(os.listdir(p), key=str.lower):
            q = os.path.join(p, sub)
            if sub.startswith(".") or sub in SKIP or not os.path.isdir(q) or os.path.islink(q):
                continue
            own = os.path.exists(os.path.join(q, ".git")) or any(os.path.exists(os.path.join(q, m)) for m in MARK)
            parts.append({"name": sub, "own": own, "about": _about(q) if own else "", "tech": _tech(q) if own else [],
                          "git": _git_info(q) if own else None, "from": orig.get(q, "").replace(H, "~")})
        tech = _tech(p)
        for pt in parts:
            for t in pt["tech"]:
                if t.split(" (")[0] not in [x.split(" (")[0] for x in tech]: tech.append(t)
        out.append({"name": name, "path": p, "about": _about(p) or next((x["about"] for x in parts if x["about"]), ""), "tech": tech,
                    "git": _git_info(p), "files": n, "size": size, "rebuildable": reb, "changed": newest, "status": status.get(p, ""),
                    "from": orig.get(p, "").replace(H, "~"), "parts": parts})
    return {"home": home, "at": time.time(), "projects": out}


def _sz(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB": return f"{n:.0f} {u}" if u in ("B", "KB") else f"{n:.1f} {u}"
        n /= 1024


def _gtxt(g):
    if not g: return "no git"
    if g.get("broken"): return "git folder present but not readable"
    return (f"{g['commits']} commits, branch {g['branch'] or '?'}, last {g['last']}" + (f", {g['dirty']} uncommitted changes" if g["dirty"] else "")
            + (f", {g['remote']}" if g["remote"] else ", no remote"))


def write(cfg, cat=None):
    d = build(cfg, cat)
    if d is None:
        return None
    day = lambda t: time.strftime("%Y-%m-%d", time.localtime(t)) if t else "-"
    P = d["projects"]
    md = [f"# Projects index", "", f"{len(P)} projects in `{d['home'].replace(os.path.expanduser('~'), '~')}`. Updated {time.strftime('%Y-%m-%d %H:%M')}. "
          "This file is rewritten automatically; do not edit it by hand.", "",
          "| Project | What it is | Status | Technology | Last change | Files | Size | Rebuildable |", "|---|---|---|---|---|---|---|---|"]
    for x in P:
        md.append(f"| [{x['name']}](#{re.sub(r'[^a-z0-9 -]', '', x['name'].lower()).replace(' ', '-')}) | {x['about'].replace('|', '/')} | {x['status'] or '-'} | "
                  f"{', '.join(x['tech']) or '-'} | {day(x['changed'])} | {x['files']:,} | {_sz(x['size'])} | {_sz(x['rebuildable']) if x['rebuildable'] else '-'} |")
    for x in P:
        md += ["", f"## {x['name']}", ""]
        if x["about"]: md.append(x["about"]); md.append("")
        md.append(f"- **Folder:** `{x['name']}/`")
        md.append(f"- **Status:** {x['status'] or 'not set'}")
        if x["tech"]: md.append(f"- **Technology:** {', '.join(x['tech'])}")
        md.append(f"- **git:** {_gtxt(x['git'])}")
        md.append(f"- **Last change:** {day(x['changed'])} · {x['files']:,} files · {_sz(x['size'])}"
                  + (f" · plus {_sz(x['rebuildable'])} of libraries and build output that can be recreated" if x["rebuildable"] else ""))
        if x["from"]: md.append(f"- **Was at:** `{x['from']}` (a link there points here)")
        if x["parts"]:
            md.append("- **Folders inside:**")
            for pt in x["parts"]:
                extra = "; ".join(v for v in (pt["about"], ", ".join(pt["tech"]), _gtxt(pt["git"]) if pt["git"] else "", ("was at `" + pt["from"] + "`") if pt["from"] else "") if v)
                md.append(f"  - `{pt['name']}/`" + (f": {extra}" if extra else ""))
    with open(os.path.join(d["home"], NAMES[0]), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    e = html.escape
    rows = "".join(f"<tr><td><a href='#p{i}'>{e(x['name'])}</a></td><td>{e(x['about'])}</td><td>{e(x['status'] or '-')}</td><td>{e(', '.join(x['tech']) or '-')}</td>"
                   f"<td class=r>{day(x['changed'])}</td><td class=r>{x['files']:,}</td><td class=r>{_sz(x['size'])}</td><td class=r>{_sz(x['rebuildable']) if x['rebuildable'] else '-'}</td></tr>" for i, x in enumerate(P))
    cards = ""
    for i, x in enumerate(P):
        parts = "".join(f"<li><code>{e(pt['name'])}/</code>" + (" — " + e("; ".join(v for v in (pt["about"], ", ".join(pt["tech"]), _gtxt(pt["git"]) if pt["git"] else "") if v)) if pt["own"] else "") + "</li>" for pt in x["parts"])
        cards += (f"<section id='p{i}'><h2><a href='{e(x['name'])}/'>{e(x['name'])}</a> <span class=st>{e(x['status'] or 'status not set')}</span></h2>"
                  + (f"<p>{e(x['about'])}</p>" if x["about"] else "") + "<dl>"
                  + (f"<dt>Technology</dt><dd>{e(', '.join(x['tech']))}</dd>" if x["tech"] else "")
                  + f"<dt>git</dt><dd>{e(_gtxt(x['git']))}</dd><dt>Last change</dt><dd>{day(x['changed'])} · {x['files']:,} files · {_sz(x['size'])}{(' · plus ' + _sz(x['rebuildable']) + ' rebuildable') if x['rebuildable'] else ''}</dd>"
                  + (f"<dt>Was at</dt><dd><code>{e(x['from'])}</code></dd>" if x["from"] else "") + "</dl>"
                  + (f"<details><summary>{len(x['parts'])} folders inside</summary><ul>{parts}</ul></details>" if parts else "") + "</section>")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Projects index</title><style>
:root{{--bg:#f4f5f2;--surface:#fff;--ink:#1d2320;--muted:#5d6862;--line:#dde1dc;--accent:#2d6a4f;--soft:#e3efe8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121614;--surface:#1a201d;--ink:#e4ebe6;--muted:#97a49c;--line:#2b342f;--accent:#7cc3a0;--soft:#1f3229;color-scheme:dark}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}}main{{max-width:1100px;margin:0 auto;padding:20px 16px 60px}}
h1{{font-size:22px;margin:0 0 4px}}.sub{{color:var(--muted);margin:0 0 16px}}a{{color:var(--accent)}}.tw{{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:10px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}}th{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
td.r{{white-space:nowrap;color:var(--muted);font-variant-numeric:tabular-nums}}section{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-top:12px}}
h2{{font-size:16px;margin:0 0 4px}}.st{{font-size:12px;font-weight:400;background:var(--soft);color:var(--accent);border-radius:999px;padding:1px 9px;margin-left:6px}}p{{margin:0 0 8px}}
dl{{display:grid;grid-template-columns:110px 1fr;gap:2px 10px;margin:0;font-size:13px}}dt{{color:var(--muted)}}dd{{margin:0;overflow-wrap:anywhere}}code{{font:12px ui-monospace,Menlo,monospace}}details{{margin-top:8px;font-size:13px}}ul{{margin:6px 0 0;padding-left:20px}}
</style></head><body><main><h1>Projects index</h1><p class="sub">{len(P)} projects in {e(d['home'].replace(os.path.expanduser('~'), '~'))} · updated {time.strftime('%Y-%m-%d %H:%M')} · rewritten automatically</p>
<div class="tw"><table><thead><tr><th>Project</th><th>What it is</th><th>Status</th><th>Technology</th><th>Last change</th><th>Files</th><th>Size</th><th title="Libraries and build output that can be recreated">Rebuildable</th></tr></thead><tbody>{rows}</tbody></table></div>{cards}</main></body></html>"""
    with open(os.path.join(d["home"], NAMES[1]), "w", encoding="utf-8") as f:
        f.write(page)
    return d
