# -*- mode: python ; coding: utf-8 -*-
"""Cross-platform onedir bundle: pyinstaller --clean --noconfirm desktop.spec"""
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).resolve()
required = [
    'streamlit', 'streamlit_folium', 'folium', 'branca',
    'rasterio', 'pyproj', 'shapely', 'matplotlib', 'plotly', 'scipy',
]
datas, binaries, hiddenimports = [], [], []
for package in required:
    data, bins, hidden = collect_all(package)
    datas += data
    binaries += bins
    hiddenimports += hidden

for package in ['numpy', 'pandas', 'PIL', 'webview']:
    hiddenimports.extend(collect_submodules(package))

# Streamlit has dynamic imports from the script not visible to the analyzer.
hiddenimports.extend([
    'coverage_viewer', 'viewer_bridge', 'viewer_export', 'viewer_workspace_file', 'workspace_theme', 'antenna_workspace_preview', 'map_workspace', 'radar_core', 'web_support', 'ssr_custom', 'obstacles', 'obstacle_ui',
    'project_file', 'project_widgets', 'live_simulation', 'radar_window',
    'wind_turbines', 'wind_offline', 'site_picker', 'standalone_radar',
    'coverage_diagnostics', 'diagnostics_ui', 'environment_layers',
    'aviation_layers', 'canopy_layers', 'traffic_history', 'microsoft_buildings',
])

datas += [
    (str(root / 'streamlit_app.py'), '.'),
    (str(root / '.streamlit'), '.streamlit'),
    (str(root / 'assets'), 'assets'),
    (str(root / 'data'), 'data'),
]
# Include Streamlit's static files and bundled JS for streamlit-folium via
# collect_all(), not via download-on-startup.

a = Analysis(
    [str(root / 'desktop_launcher.py')],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=list(dict.fromkeys(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['customtkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='COVERAGEDIAGRAMS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas,
               strip=False, upx=False, name='COVERAGEDIAGRAMS')
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='COVERAGEDIAGRAMS.app',
        bundle_identifier='cz.coveragediagrams.desktop',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleDisplayName': 'COVERAGEDIAGRAMS',
            'CFBundleName': 'COVERAGEDIAGRAMS',
        },
    )
