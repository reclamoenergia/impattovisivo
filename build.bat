@echo off
setlocal

echo [1/2] Install dependencies
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  exit /b 1
)

echo [2/2] Build EXE
pyinstaller --noconfirm --onefile --windowed wind_turbine_visible_height_gui.py
if errorlevel 1 (
  echo.
  echo Standard build failed. Trying rasterio collect-all mode...
  pyinstaller --noconfirm --onefile --windowed --collect-all rasterio wind_turbine_visible_height_gui.py
)

if errorlevel 1 (
  echo Build failed even with --collect-all rasterio.
  exit /b 1
)

echo Build completed. Check dist\wind_turbine_visible_height_gui.exe
endlocal
