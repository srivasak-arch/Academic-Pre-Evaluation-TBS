# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds the dashboard into ONE self-contained executable.
Build with:  python build.py     (or:  pyinstaller AcademicDashboard.spec --noconfirm --clean)
"""
from PyInstaller.utils.hooks import collect_all, copy_metadata, collect_submodules

datas, binaries, hiddenimports = [], [], []

# Collect Streamlit and its data-heavy dependencies (static files, metadata, libs).
for pkg in ("streamlit", "pandas", "altair", "pyarrow", "numpy"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# Streamlit reads its own (and some deps') distribution metadata at runtime.
for meta in ("streamlit", "pandas", "altair", "pyarrow", "numpy", "click",
             "tornado", "rich", "blinker", "packaging", "gitpython"):
    try:
        datas += copy_metadata(meta)
    except Exception:
        pass

# Our application package + the script Streamlit runs + the seed data + theme.
hiddenimports += collect_submodules("src")
datas += [
    ("app.py", "."),
    ("src", "src"),
    ("data", "data"),
    ("assets", "assets"),
    (".streamlit", ".streamlit"),
]

a = Analysis(
    ["desktop_launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# Including binaries + datas directly in EXE produces a single-file build.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AcademicDashboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,        # no terminal window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
