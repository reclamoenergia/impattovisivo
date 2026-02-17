# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

block_cipher = None

hiddenimports = []
hiddenimports += collect_submodules('rasterio')
hiddenimports += collect_submodules('numba')
hiddenimports += collect_submodules('llvmlite')

# rasterio / gdal / proj payload
rasterio_datas = collect_data_files('rasterio', include_py_files=False)
rasterio_bins = collect_dynamic_libs('rasterio')
numba_bins = collect_dynamic_libs('llvmlite')

# keep names predictable for runtime env setup (PROJ_LIB/GDAL_DATA)
datas = []
datas += rasterio_datas

gdal_data_guess = [
    ('C:/OSGeo4W/share/gdal', 'gdal_data'),
    ('C:/Program Files/GDAL/gdal-data', 'gdal_data'),
]
proj_data_guess = [
    ('C:/OSGeo4W/share/proj', 'proj_data'),
    ('C:/Program Files/GDAL/projlib', 'proj_data'),
]
for src, dst in gdal_data_guess + proj_data_guess:
    import os
    if os.path.isdir(src):
        datas.append((src, dst))

binaries = []
binaries += rasterio_bins
binaries += numba_bins


a = Analysis(
    ['wind_visible_height_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='wind_visible_height',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='wind_visible_height',
)
