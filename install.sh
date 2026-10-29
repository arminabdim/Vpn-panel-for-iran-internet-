#!/usr/bin/env bash
# OpenPath - zero-setup installer for Termux / Linux / macOS / WSL.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/arminabdim/Vpn-panel-for-iran-internet-/main/install.sh)
#
# It only clones the repository (no sudo, no pip, no compiling), then starts
# the panel so you get a real GUI in your browser.
set -e
REPO="${OPENPATH_REPO:-https://github.com/arminabdim/Vpn-panel-for-iran-internet-.git}"
DIR="${OPENPATH_DIR:-$HOME/openpath}"

say() { printf '\033[36m[openpath]\033[0m %s\n' "$*"; }

if ! command -v python3 >/dev/null 2>&1; then
  say "python3 not found - installing it"
  if command -v pkg >/dev/null 2>&1; then pkg install -y python
  elif command -v apt-get >/dev/null 2>&1; then sudo apt-get update -y && sudo apt-get install -y python3 git
  elif command -v brew >/dev/null 2>&1; then brew install python git
  else say "please install python3 first"; exit 1; fi
fi

if ! command -v git >/dev/null 2>&1; then
  say "git not found - installing it"
  if command -v pkg >/dev/null 2>&1; then pkg install -y git
  elif command -v apt-get >/dev/null 2>&1; then sudo apt-get install -y git
  else say "please install git first"; exit 1; fi
fi

if [ -d "$DIR/.git" ]; then
  say "updating $DIR"
  git -C "$DIR" pull --ff-only || true
else
  say "downloading OpenPath into $DIR"
  git clone --depth 1 "$REPO" "$DIR"
fi

say "starting the panel"
exec python3 "$DIR/openpath.py" panel "$@"
