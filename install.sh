#!/usr/bin/env bash
# Marketing MCP installer for macOS / Linux.
# Creates a virtual environment, installs dependencies, and registers the server
# into your Claude config (Desktop and/or Claude Code). Run from the repo:
#   bash install.sh
set -e
cd "$(dirname "$0")"

echo "Marketing MCP installer"
echo

# 1. Python 3.10+ (the type hints need 3.10).
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found."
  echo "  macOS:  brew install python@3.11   (or: xcode-select --install)"
  echo "  Linux:  install python3 (3.10+) with your package manager"
  exit 1
fi
PYV="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,10) else 1)'; then
  echo "Found Python $PYV, but 3.10 or newer is required."
  echo "  macOS:  brew install python@3.11"
  exit 1
fi
echo "Using python3 ($PYV)"

# 2. Virtual environment + dependencies.
echo "Creating .venv and installing dependencies (this can take a minute)..."
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip >/dev/null
./.venv/bin/python -m pip install -r requirements.txt

# 3. Register into the Claude config(s).
echo
./.venv/bin/python register.py

echo
echo "Done."
echo "Restart Claude Desktop (and/or your Claude Code session) to load marketing-mcp,"
echo "then try the no-auth tools, for example:"
echo "  use autocomplete_suggestions for 'ppc agency'"
echo
echo "To connect Google Ads / Meta / GA4, copy .env.example to .env and fill it in"
echo "(see SETUP.md). The server auto-loads that .env."
