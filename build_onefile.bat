@echo off
setlocal

echo Building onefile (more fragile with geospatial/numba stacks)...

pyinstaller --noconfirm --clean wind_visible_height.spec

if errorlevel 1 exit /b 1

echo Build completed: dist\wind_visible_height.exe
endlocal
