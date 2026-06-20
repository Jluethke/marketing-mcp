@echo off
REM Marketing MCP installer for Windows.
REM Creates a virtual environment, installs dependencies, and registers the
REM server into your Claude config. Run from the repo:  install.bat
setlocal
cd /d "%~dp0"

echo Marketing MCP installer
echo.

where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)

%PY% -c "import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,10) else 1)"
if %errorlevel% neq 0 (
  echo Python 3.10 or newer is required. Install it from python.org and retry.
  exit /b 1
)

echo Creating .venv and installing dependencies...
%PY% -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
".venv\Scripts\python.exe" register.py

echo.
echo Done. Restart Claude Desktop (and/or your Claude Code session) to load marketing-mcp.
echo Try the no-auth tools, for example: use autocomplete_suggestions for "ppc agency"
endlocal
