# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

script = 'tools/unified_view_to_points.py'

hiddenimports = [
    'rasterio',
    'rasterio._base',
    'rasterio._io',
    'rasterio._warp',
    'rasterio.sample',
    'fiona',
    'fiona._shim',
    'fiona.schema',
]

datas = []
binaries = []

for pkg in ('rasterio', 'fiona'):
    datas += collect_data_files(pkg)
    binaries += collect_dynamic_libs(pkg)


a = Analysis(
    [script],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='unified_view_to_points',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='unified_view_to_points',
)
