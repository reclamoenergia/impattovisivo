@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo [0/3] Select Python 3.10/3.11 interpreter
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3.11 -c "import sys" >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set "PY=py -3.11"
    ) else (
        py -3.10 -c "import sys" >nul 2>nul
        if %ERRORLEVEL% EQU 0 (
            set "PY=py -3.10"
        ) else (
            echo ERRORE: Python 3.10/3.11 non trovato con launcher py.
            exit /b 1
        )
    )
) else (
    set "PY=python"
)

echo [1/3] Check Python version (required: 3.10 or 3.11)
%PY% -c "import sys; v=sys.version_info[:2]; raise SystemExit(0 if v in ((3,10),(3,11)) else 1)"
if errorlevel 1 (
    echo ERRORE: versione Python non supportata per build EXE.
    echo Usa Python 3.10 o 3.11 e ricrea ambiente/build.
    exit /b 1
)

echo [2/3] Build onefile (more fragile with geospatial/numba stacks)...
%PY% -m PyInstaller --noconfirm --clean --onefile wind_visible_height.spec
if errorlevel 1 exit /b 1

echo [3/3] Build completed: dist\wind_visible_height.exe
endlocal
