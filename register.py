# SPDX-License-Identifier: MIT
"""Register marketing-mcp into the local Claude config(s).

Adds an `mcpServers` entry named "marketing-mcp" pointing at this repo's venv
Python (falling back to the running Python) and server.py, into:
  - Claude Desktop:  the platform config file, if Claude Desktop is installed
  - Claude Code:     ~/.claude.json

Idempotent (re-running just rewrites the entry) and cross-platform (macOS,
Windows, Linux). Backs up any file it edits to <file>.bak. Run it directly, or
let install.sh / install.bat run it for you.
"""
import json
import os
import platform
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "server.py")
NAME = "marketing-mcp"


def venv_python() -> str:
    """The repo venv interpreter if it exists, else the interpreter running this."""
    if os.name == "nt":
        cand = os.path.join(HERE, ".venv", "Scripts", "python.exe")
    else:
        cand = os.path.join(HERE, ".venv", "bin", "python")
    return cand if os.path.exists(cand) else sys.executable


def config_targets():
    """(kind, path, create_if_absent) for each Claude config on this platform."""
    home = os.path.expanduser("~")
    system = platform.system()
    if system == "Darwin":
        desktop = os.path.join(home, "Library", "Application Support", "Claude",
                               "claude_desktop_config.json")
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        desktop = os.path.join(appdata, "Claude", "claude_desktop_config.json")
    else:
        desktop = os.path.join(home, ".config", "Claude", "claude_desktop_config.json")
    # Desktop: only if Claude Desktop's dir exists (do not create the app folder).
    # Claude Code: ~/.claude.json, create if absent.
    return [
        ("Claude Desktop", desktop, False),
        ("Claude Code", os.path.join(home, ".claude.json"), True),
    ]


def _load(path: str) -> dict:
    if os.path.exists(path):
        try:
            d = json.load(open(path, encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def register() -> list:
    py = venv_python()
    entry = {"type": "stdio", "command": py, "args": [SERVER], "env": {}}
    written = []
    for kind, path, create in config_targets():
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            if not create:
                continue  # Claude Desktop not installed; skip
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(path) and not create:
            continue
        d = _load(path)
        d.setdefault("mcpServers", {})
        d["mcpServers"][NAME] = entry
        if os.path.exists(path):
            try:
                shutil.copy2(path, path + ".bak")
            except Exception:  # noqa: BLE001
                pass
        json.dump(d, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        written.append((kind, path))
    return written


def main() -> int:
    written = register()
    if written:
        print("Registered '%s' in:" % NAME)
        for kind, path in written:
            print("  %-14s %s" % (kind, path))
        print("\nRestart Claude Desktop and/or your Claude Code session to load it.")
    else:
        print("No Claude config found. Install Claude Desktop or run Claude Code once, "
              "then re-run: python register.py")
    print("\nServer command: %s %s" % (venv_python(), SERVER))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
