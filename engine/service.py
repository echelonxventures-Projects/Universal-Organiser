"""Start automatically at login, with the system's own tool (nothing extra installed):
  macOS   a LaunchAgent in ~/Library/LaunchAgents
  Linux   a systemd user service in ~/.config/systemd/user
  Windows a Task Scheduler task that runs at log-on
A hub or a standalone computer starts the page (`uo serve --no-browser`); an agent starts `uo agent run`.
"""
import os, subprocess, sys

from .config import ROOT, DATA, Config
from . import platforms

LABEL = "org.universal-organiser"
H = os.path.expanduser("~")


def _command():
    cfg = Config()
    py = sys.executable
    cli = os.path.join(ROOT, "engine", "cli.py")
    if cfg.get("role") == "agent":
        return [py, "-I", cli, "agent", "run", "--every", str((cfg.get("agent") or {}).get("every_minutes", 60))], "agent"
    return [py, "-I", cli, "serve", "--no-browser"], "page"


def _env():
    return {"UO_DATA": DATA} if DATA != ROOT else {}


def _plist(cmd):
    from xml.sax.saxutils import escape
    args = "".join(f"<string>{escape(c)}</string>" for c in cmd)
    env = "".join(f"<key>{escape(k)}</key><string>{escape(v)}</string>" for k, v in _env().items())
    log = escape(os.path.join(DATA, "logs", "autostart.log"))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            f'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict><key>Label</key><string>{LABEL}</string>'
            f'<key>ProgramArguments</key><array>{args}</array><key>EnvironmentVariables</key><dict>{env}</dict>'
            f'<key>RunAtLoad</key><true/><key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>'
            f'<key>ThrottleInterval</key><integer>60</integer>'
            f'<key>StandardOutPath</key><string>{log}</string><key>StandardErrorPath</key><string>{log}</string></dict></plist>\n')


def _paths():
    if platforms.SYSTEM == "macos":
        return os.path.join(H, "Library", "LaunchAgents", LABEL + ".plist")
    if platforms.SYSTEM == "linux":
        return os.path.join(H, ".config", "systemd", "user", "universal-organiser.service")
    return None


def enable():
    cmd, what = _command()
    os.makedirs(os.path.join(DATA, "logs"), exist_ok=True)
    p = _paths()
    if platforms.SYSTEM == "macos":
        os.makedirs(os.path.dirname(p), exist_ok=True)
        subprocess.run(["launchctl", "unload", p], capture_output=True)
        open(p, "w").write(_plist(cmd))
        r = subprocess.run(["launchctl", "load", "-w", p], capture_output=True, text=True)
        return f"Starts at login ({what}): {p}" + (f"\n  launchctl: {r.stderr.strip()}" if r.returncode else "")
    if platforms.SYSTEM == "linux":
        os.makedirs(os.path.dirname(p), exist_ok=True)
        q = lambda c: '"' + c.replace('"', '\\"') + '"'
        env = "".join(f"Environment={k}={v}\n" for k, v in _env().items())
        open(p, "w").write(f"[Unit]\nDescription=Universal Organiser ({what})\nAfter=network-online.target\n\n[Service]\n{env}"
                           f"ExecStart={' '.join(q(c) for c in cmd)}\nRestart=on-failure\nRestartSec=60\n\n[Install]\nWantedBy=default.target\n")
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        r = subprocess.run(["systemctl", "--user", "enable", "--now", "universal-organiser.service"], capture_output=True, text=True)
        return f"Starts at login ({what}): {p}" + (f"\n  systemctl: {r.stderr.strip()}" if r.returncode else "")
    # Windows: a log-on task for this user only
    line = subprocess.list2cmdline(cmd)
    if _env():
        line = f'cmd /c set UO_DATA={DATA}&& {line}'
    r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/RL", "LIMITED", "/TN", "Universal Organiser", "/TR", line],
                       capture_output=True, text=True)
    return "Starts at log-on (Task Scheduler: “Universal Organiser”)." if r.returncode == 0 else "Could not create the task: " + (r.stderr or r.stdout)


def disable():
    p = _paths()
    if platforms.SYSTEM == "macos":
        if os.path.exists(p):
            subprocess.run(["launchctl", "unload", "-w", p], capture_output=True)
            os.remove(p)
        return "No longer starts at login."
    if platforms.SYSTEM == "linux":
        subprocess.run(["systemctl", "--user", "disable", "--now", "universal-organiser.service"], capture_output=True)
        if os.path.exists(p):
            os.remove(p)
        return "No longer starts at login."
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", "Universal Organiser"], capture_output=True)
    return "No longer starts at log-on."


def status():
    p = _paths()
    on = os.path.exists(p) if p else subprocess.run(["schtasks", "/Query", "/TN", "Universal Organiser"], capture_output=True).returncode == 0
    return ("Starts automatically at login." if on else "Does not start automatically.") + "  (uo autostart on|off)"
