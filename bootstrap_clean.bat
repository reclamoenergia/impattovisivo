@echo off
setlocal EnableExtensions

REM Bootstrap completo da clone pulito (Windows).
REM Esegue setup ambiente + smoke checks senza controlli manuali.

cd /d "%~dp0"

echo [1/6] Verifica Python 3.10/3.11...
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
    where python >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo ERRORE: Python non trovato nel PATH.
        exit /b 1
    )
    set "PY=python"
)

echo [2/6] Creazione/aggiornamento virtualenv .venv...
%PY% -m venv .venv
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

call .venv\Scripts\activate.bat
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo [3/6] Verifica versione Python ambiente...
python -c "import sys; v=sys.version_info[:2]; raise SystemExit(0 if v in ((3,10),(3,11)) else 1)"
if %ERRORLEVEL% NEQ 0 (
    echo ERRORE: .venv non usa Python 3.10/3.11.
    exit /b 1
)

echo [4/6] Installazione dipendenze...
python -m pip install --upgrade pip
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
python -m pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo [5/6] Smoke checks automatici...
python -m compileall wind_visible_height_gui.py core_radial_visibility.py
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
python -c "import rasterio, numba, tkinter, wind_visible_height_gui, core_radial_visibility; print('SMOKE CHECK OK')"
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo [6/6] Ambiente pronto.
echo.
echo Avvio applicazione:
echo   .venv\Scripts\activate.bat
echo   python wind_visible_height_gui.py

exit /b 0
