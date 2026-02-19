@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo [0/2] Check Python version (required: 3.10 or 3.11)
python -c "import sys; v=sys.version_info[:2]; raise SystemExit(0 if v in ((3,10),(3,11)) else 1)"
if errorlevel 1 (
    echo ERRORE: versione Python non supportata per build EXE.
    echo Usa Python 3.10 o 3.11 e ricrea ambiente/build.
    exit /b 1
)

echo [1/2] Build onefile (more fragile with geospatial/numba stacks)...
python -m PyInstaller --noconfirm --clean --onefile wind_visible_height.spec
if errorlevel 1 exit /b 1

echo [2/2] Build completed: dist\wind_visible_height.exe
endlocal
