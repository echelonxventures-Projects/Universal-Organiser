#!/bin/sh
# Universal Organiser installer for macOS and Linux.
#   sh install/install.sh [--dir FOLDER] [--yes] [--no-start] [--autostart] [--no-link]
# Run it again later to update: program files are replaced, your profile, catalogue and logs are kept.
set -eu

SRC=$(cd "$(dirname "$0")/.." && pwd)
YES=0; START=1; AUTO=0; LINK=1; DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --no-start) START=0; shift ;;
    --autostart) AUTO=1; shift ;;
    --no-link) LINK=0; shift ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1"; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
ask() {  # ask "question" -> 0 for yes
  [ "$YES" = 1 ] && return 0
  printf '%s [y/N] ' "$1"; read -r a </dev/tty || return 1
  case "$a" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

OS=$(uname -s)
case "$OS" in
  Darwin) SYS=macos; DEF="$HOME/Library/Application Support/Universal Organiser" ;;
  Linux)  SYS=linux; DEF="${XDG_DATA_HOME:-$HOME/.local/share}/universal-organiser" ;;
  *) say "This installer is for macOS and Linux. On Windows run install\\install.cmd"; exit 1 ;;
esac
[ -z "$DIR" ] && DIR="$DEF"
if [ "$SYS" = linux ] && grep -qi microsoft /proc/version 2>/dev/null; then
  say "Note: this is Linux inside Windows (WSL). It can only see Windows files under /mnt/c; installing on Windows itself is usually better."
fi
say "Universal Organiser — installing for $SYS ($(uname -m))"
say "  program and your data: $DIR"

# ---- Python 3.9+
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then PY=$(command -v "$c"); break; fi
done
if [ -z "$PY" ]; then
  say "Python 3.9 or newer is needed and was not found."
  if [ "$SYS" = macos ]; then
    say "  Install it from https://www.python.org/downloads/ (or run: xcode-select --install), then run this installer again."
    exit 1
  fi
  if command -v apt-get >/dev/null; then CMD="sudo apt-get install -y python3"
  elif command -v dnf >/dev/null; then CMD="sudo dnf install -y python3"
  elif command -v pacman >/dev/null; then CMD="sudo pacman -S --noconfirm python"
  elif command -v zypper >/dev/null; then CMD="sudo zypper install -y python3"
  else CMD=""; fi
  if [ -n "$CMD" ] && ask "Install Python now with: $CMD ?"; then sh -c "$CMD"; PY=$(command -v python3); else exit 1; fi
fi
say "  Python: $("$PY" -c 'import sys; print(sys.version.split()[0])') ($PY)"
"$PY" -c 'import sqlite3; c=sqlite3.connect(":memory:"); c.execute("create virtual table t using fts5(x)")' 2>/dev/null \
  || { say "This Python has no SQLite full-text search (FTS5). Install Python from python.org or your package manager."; exit 1; }

# ---- copy the program (never the data)
if [ "$(cd "$SRC" && pwd)" != "$(mkdir -p "$DIR" && cd "$DIR" && pwd)" ]; then
  [ -d "$DIR/engine" ] && say "  existing install found: updating the program files only"
  mkdir -p "$DIR/profiles" "$DIR/helpers/macos"
  rm -rf "$DIR/engine.old"; [ -d "$DIR/engine" ] && mv "$DIR/engine" "$DIR/engine.old"
  cp -R "$SRC/engine" "$DIR/engine"
  for d in presets regions; do rm -rf "$DIR/profiles/$d"; cp -R "$SRC/profiles/$d" "$DIR/profiles/$d"; done
  cp "$SRC/profiles/base.json" "$DIR/profiles/base.json"
  cp "$SRC"/helpers/macos/*.swift "$DIR/helpers/macos/"
  for f in uo uo.cmd fe fe.cmd README.md LICENSE CHANGELOG.md SECURITY.md; do [ -f "$SRC/$f" ] && cp "$SRC/$f" "$DIR/$f"; done
  rm -rf "$DIR/docs" "$DIR/install"; cp -R "$SRC/docs" "$DIR/docs"; cp -R "$SRC/install" "$DIR/install"
  find "$DIR/engine" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
  rm -rf "$DIR/engine.old"
fi
chmod +x "$DIR/uo" "$DIR/fe"
chmod 700 "$DIR"

# ---- macOS reader (OCR, photos, transcripts) built from source on this Mac
if [ "$SYS" = macos ]; then
  if command -v swiftc >/dev/null 2>&1; then
    say "  building the macOS reader (a few minutes the first time)…"
    "$PY" -I "$DIR/engine/cli.py" doctor --build-helper >/dev/null 2>&1 || say "  the reader was not built; run: uo doctor --fix"
  else
    say "  The macOS reader needs Apple's Command Line Tools."
    if ask "Open Apple's installer for them now (then run this installer again)?"; then xcode-select --install || true; fi
  fi
fi

# ---- 'uo' on the PATH
if [ "$LINK" = 1 ]; then
  BIN="$HOME/.local/bin"; mkdir -p "$BIN"
  ln -sf "$DIR/uo" "$BIN/uo"
  case ":$PATH:" in *":$BIN:"*) ;; *) say "  Add $BIN to your PATH to type 'uo' anywhere (or use: \"$DIR/uo\")." ;; esac
fi

say ""
"$DIR/uo" doctor || true
[ "$AUTO" = 1 ] && "$DIR/uo" autostart on
say ""
if [ "$START" = 1 ]; then
  say "Starting. Your browser opens the page: create the admin account, then the set-up wizard asks the rest."
  exec "$DIR/uo" serve
else
  say "Done. Start with:  uo serve"
fi
