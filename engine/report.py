"""Problem report: what support needs to help, made only when you ask for it and sent only by you.

  uo report        writes exports/problem-report-<time>.txt and prints its path
  Settings → Help → Make a problem report   shows it first, then Download / Copy / Email support

It holds the version, system, health checks, settings that matter (no names of people or folders) and the last errors
from the logs. Paths, file names, web addresses, e-mail addresses and long numbers are replaced by placeholders, so
nothing about your files or family is in it. Nothing is sent anywhere by the program itself.
"""
import glob, os, platform, re, sys, time

from .config import DATA, ROOT
from .setup import VERSION

ERR = re.compile(r"error|failed|traceback|exception|refused|not (?:found|valid|signed)|could not|warning|stopped", re.I)
_PATH = re.compile(r"(?:\b[A-Za-z]:\\|\\\\|(?<![\w.])/(?=[\w~.])|~[\\/])[^\n\"'<>|]*?(?=: |\s\(|\s→|\s->|[\"'<>|]|$)", re.M)
_URL = re.compile(r"\b(?:https?|uo)://\S+")
_MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_NUM = re.compile(r"\b\d[\d -]{7,}\d\b")
_QUOTED = re.compile(r"[“\"']([^“”\"'\n]{2,120})[”\"']")


def redact(text):
    """Replace anything personal by a placeholder: paths keep only their extension ([path .pdf])."""
    def path(m):
        exts = re.findall(r"\.([A-Za-z0-9]{1,6})\b", m.group(0))
        return f"[path .{exts[-1].lower()}]" if exts else "[path]"
    text = _URL.sub("[address]", text)
    text = _MAIL.sub("[e-mail]", text)
    text = _PATH.sub(path, text)
    text = _NUM.sub("[number]", text)
    text = _QUOTED.sub("“[name]”", text)
    for who in {os.path.basename(os.path.expanduser("~")), os.environ.get("USER", ""), os.environ.get("USERNAME", "")}:
        if len(who) >= 3:
            text = re.sub(re.escape(who), "[user]", text, flags=re.I)
    return text


def _errors(limit=120):
    out = []
    logs = sorted(glob.glob(os.path.join(DATA, "logs", "*.log")), key=os.path.getmtime)[-12:]
    for f in logs:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()[-4000:]
        except OSError:
            continue
        hits = [ln for ln in lines if ERR.search(ln)]
        if hits:
            out.append(f"--- {os.path.basename(f)} ({len(hits)} lines)")
            out += hits[-25:]
    return out[-limit:]


def build(cfg=None):
    from . import platforms, setup as SU
    lines = [f"Universal Organiser problem report — {time.strftime('%Y-%m-%d %H:%M')}",
             f"version {VERSION} · {platforms.SYSTEM} {platform.release()} ({platform.machine()}) · Python {sys.version.split()[0]}",
             f"git copy: {'yes' if os.path.isdir(os.path.join(ROOT, '.git')) else 'no'}", ""]
    lines.append("Health checks")
    try:
        for c in SU.checks(cfg):
            lines.append(f"  [{c['status']}] {c['title']} ({c['need']}){': ' + c['detail'] if c.get('detail') else ''}")
    except Exception as e:
        lines.append(f"  could not run: {type(e).__name__}: {e}")
    if cfg:
        lines += ["", "Settings that matter"]
        try:
            from . import updates
            u = updates.settings(cfg)
            on = sorted(k for k, v in (cfg.get("plugins") or {}).items() if isinstance(v, dict) and v.get("enabled"))
            lines += [f"  profile preset: {cfg.get('profile')} · role: {(cfg.get('role') or 'standalone')} · "
                      f"folders to scan: {len(cfg.roots)} · owners: {len(cfg.get('entities') or [])} · topics: {len(cfg.get('topics') or [])}",
                      f"  catalogue: names only = {platforms.STORE.get('names_only')} · language: {(cfg.get('ui') or {}).get('language') or 'auto'}",
                      f"  updates: check {u['check']} · automatic {u['auto']} · source {'folder/web' if u['feed'] else 'GitHub'} · "
                      f"token saved {bool(updates.token())}",
                      f"  plug-ins on: {', '.join(on) or '-'}"]
        except Exception as e:
            lines.append(f"  could not read: {type(e).__name__}")
    lines += ["", "Recent errors and warnings (from the logs)"]
    lines += ["  " + ln for ln in _errors()] or ["  none"]
    lines += ["", "Paths, file names, addresses, e-mails, long numbers and quoted names are replaced by placeholders.",
              "Read it before you send it; nothing is sent by the program itself."]
    return redact("\n".join(lines))


def write(cfg=None):
    d = os.path.join(DATA, "exports")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, time.strftime("problem-report-%Y%m%d-%H%M%S.txt"))
    with open(p, "w", encoding="utf-8") as f:
        f.write(build(cfg))
    return p
