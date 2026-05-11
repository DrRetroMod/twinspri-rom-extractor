@echo off
setlocal
cd /d "%~dp0"

echo Running Dotemu NeoGeo extractor from:
echo %CD%
echo.

python "%~dp0extract_dotemu_neogeo.py"

echo.
pause
