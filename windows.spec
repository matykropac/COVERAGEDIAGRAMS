# -*- mode: python ; coding: utf-8 -*-
"""Build using: pyinstaller --noconfirm desktop/windows.spec"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).resolve().parent
# SPECPATH is the directory containing this spec (desktop/).
root = root.parent
packages = [
    'streamlit', 'streamlit_folium', 'folium', 'branca',
    'rasterio', 'pyproj', 'shapely', 'matplotlib',
]
all_datas = []
all_binaries = []
all_hidden = []
for name in packages:
    data, binaries, hidden = collect_all(name)
    all_datas.extend(data)
    all_binaries.extend(binaries)
    all_hidden.extend(hidden)

for name in ['numpy', 'pandas', 'PIL', 'webview']:
    all_hidden.extend(collect_submodules(name))

all_hidden.extend([
    'radar_core', 'web_support', 'ssr_custom', 'obstacles', 'obstacle_ui',
    'project_file', 'project_widgets', 'live_simulation', 'radar_window',
    'wind_turbines', 'wind_offline', 'site_picker', 'standalone_radar',
    'coverage_diagnostics', 'diagnostics_ui',
])

all_datas.extend([
    (str(root / 'streamlit_app.py'), '.'),
    (str(root / '.streamlit'), '.streamlit'),
    (str(root / 'assets'), 'assets'),
    (str(root / 'data'), 'data'),
])

analysis = Analysis(
    [str(root / 'desktop' / 'windows_launcher.py')],
    pathex=[str(root)],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'customtkinter'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [],
    exclude_binaries=True,
    name='COVERAGEDIAGRAMS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(exe, analysis.binaries, analysis.datas,
               strip=False, upx=False, name='COVERAGEDIAGRAMS')
