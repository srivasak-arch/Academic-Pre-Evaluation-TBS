"""
Desktop launcher for the Academic Pre-Evaluation Dashboard.

This is the entry point that PyInstaller freezes into a single executable. When
the user double-clicks the produced file, this:
  1. picks a writable data folder (in the user's home directory),
  2. copies the bundled seed database there on first run,
  3. starts the Streamlit server with no terminal prompts, and
  4. opens the dashboard in the default web browser.

No command prompt, no `pip`, no Python install required by the end user.
"""
import os
import sys
import time
import socket
import shutil
import threading
import webbrowser
from pathlib import Path

PORT = 8501


def resource_path(rel: str) -> str:
    """Locate a bundled resource both when frozen (PyInstaller _MEIPASS) and when
    run from source."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def writable_data_dir() -> Path:
    d = Path.home() / "AcademicPreEvalDashboard"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_seeds(data_dir: Path) -> None:
    """Copy the pre-built database and corpus into the writable folder on first run."""
    for fname in ("dashboard.db", "applicants.csv"):
        dst = data_dir / fname
        if not dst.exists():
            src = resource_path(os.path.join("data", fname))
            if os.path.exists(src):
                shutil.copy2(src, dst)


def open_browser_when_ready() -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", PORT)) == 0:
                webbrowser.open(f"http://localhost:{PORT}")
                return
        time.sleep(0.5)


def main() -> None:
    data_dir = writable_data_dir()
    ensure_seeds(data_dir)

    # Point the app at the writable data folder and silence first-run prompts.
    os.environ["DASHBOARD_DATA_DIR"] = str(data_dir)
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_SERVER_PORT"] = str(PORT)
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"

    # Skip Streamlit's first-run e-mail prompt (which would block with no console).
    cred = Path.home() / ".streamlit" / "credentials.toml"
    if not cred.exists():
        cred.parent.mkdir(parents=True, exist_ok=True)
        cred.write_text('[general]\nemail=""\n')

    threading.Thread(target=open_browser_when_ready, daemon=True).start()

    app_path = resource_path("app.py")
    sys.argv = ["streamlit", "run", app_path,
                f"--server.port={PORT}", "--server.headless=true",
                "--global.developmentMode=false"]
    import streamlit.web.cli as stcli
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
