@echo off
setlocal EnableExtensions

REM Bootstrap completo da clone pulito (Windows).
REM Esegue setup ambiente + smoke checks senza controlli manuali.

cd /d "%~dp0"

echo [1/5] Verifica Python...
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PY=py -3"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo ERRORE: Python non trovato nel PATH.
        exit /b 1
    )
    set "PY=python"
)

echo [2/5] Creazione/aggiornamento virtualenv .venv...
%PY% -m venv .venv
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

call .venv\Scripts\activate.bat
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo [3/5] Installazione dipendenze...
python -m pip install --upgrade pip
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
python -m pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo [4/5] Smoke checks automatici...
python -m compileall wind_visible_height_gui.py core_radial_visibility.py
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
python -c "import rasterio, numba, tkinter, wind_visible_height_gui, core_radial_visibility; print('SMOKE CHECK OK')"
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo [5/5] Ambiente pronto.
echo.
echo Avvio applicazione:
echo   .venv\Scripts\activate.bat
echo   python wind_visible_height_gui.py

exit /b 0
