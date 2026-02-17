@echo off
setlocal

echo [1/2] Install dependencies
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo [2/2] Build one-folder (FAST)
pyinstaller --noconfirm --clean wind_visible_height.spec
if errorlevel 1 exit /b 1

echo Build completed: dist\wind_visible_height\
endlocal
