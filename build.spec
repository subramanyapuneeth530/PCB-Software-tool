# build.spec
# ──────────────────────────────────────────────────────────────────
# PyInstaller build spec for PCB Gerber Viewer Pro
#
# Usage:
#   pip install pyinstaller
#   pyinstaller build.spec
#
# Output: dist/PCBViewerPro/  (folder)  or dist/PCBViewerPro.exe (onefile)
# ──────────────────────────────────────────────────────────────────

import sys
from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PyQt6.QtSvg',
        'PyQt6.QtOpenGL',
        'core.primitives',
        'core.parser',
        'core.drill_parser',
        'core.spatial',
        'core.layers',
        'render.canvas',
        'ui.theme',
        'ui.layer_panel',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PCBViewerPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no console window (windowed app)
    icon=None,              # set to 'icon.ico' if you have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PCBViewerPro',
)
