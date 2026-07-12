"""
One-step builder: produces a single double-clickable executable for YOUR operating
system. Run it once:

    python build.py

(Double-clicking build.py also works if .py files are associated with Python.)

It installs PyInstaller if needed, builds the database, and bundles everything into
one file placed in the `dist/` folder:
    Windows : dist/AcademicDashboard.exe
    macOS   : dist/AcademicDashboard       (right-click > Open the first time)
    Linux   : dist/AcademicDashboard

After that, just double-click the file in `dist/` — no terminal, no pip, no Python.
"""
import subprocess
import sys
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(cmd):
    print(">", " ".join(cmd))
    subprocess.check_call(cmd)


def main():
    os.chdir(HERE)

    # 1) ensure build + runtime deps are present in this Python
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

    # 2) make sure the seed database exists to bundle
    if not (HERE / "data" / "dashboard.db").exists():
        run([sys.executable, "-m", "src.ingest"])

    # 3) build the single file
    run([sys.executable, "-m", "PyInstaller", "AcademicDashboard.spec",
         "--noconfirm", "--clean"])

    exe = "AcademicDashboard.exe" if os.name == "nt" else "AcademicDashboard"
    out = HERE / "dist" / exe
    print("\n" + "=" * 60)
    if out.exists():
        print(f"Done. Your single-file dashboard is:\n    {out}")
        print("Double-click it to launch — it opens in your web browser.")
    else:
        print("Build finished but the expected file was not found in dist/.")
        print("Check the PyInstaller output above for errors.")
    print("=" * 60)


if __name__ == "__main__":
    main()
