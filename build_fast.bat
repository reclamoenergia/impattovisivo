@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo [0/3] Check Python version (required: 3.10 or 3.11)
python -c "import sys; v=sys.version_info[:2]; raise SystemExit(0 if v in ((3,10),(3,11)) else 1)"
if errorlevel 1 (
    echo ERRORE: versione Python non supportata per build EXE.
    echo Usa Python 3.10 o 3.11 e ricrea ambiente/build.
    exit /b 1
)

echo [1/3] Install dependencies
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo [2/3] Build one-folder (FAST)
python -m PyInstaller --noconfirm --clean wind_visible_height.spec
if errorlevel 1 exit /b 1

echo [3/3] Check bundled Python DLL
if not exist "dist\wind_visible_height\_internal\python*.dll" (
    echo ERRORE: python DLL non trovata in dist\wind_visible_height\_internal\
    exit /b 1
)

echo Build completed: dist\wind_visible_height\
endlocal
