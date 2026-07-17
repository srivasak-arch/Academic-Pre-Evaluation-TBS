"""
Academic Pre-Evaluation Dashboard — Streamlit entrypoint.

Run:
    python -m src.ingest        # build the database (first time)
    streamlit run app.py

No login in this build: the app opens directly into a single combined view with
review, oversight, governance (thresholds), and administration all available.
Importing this module has no side effects; only main() (run by Streamlit) renders.
"""
import sys
from pathlib import Path

import streamlit as st

# Streamlit Cloud does not always place the app's own directory on sys.path,
# which makes `from src import ...` fail with ModuleNotFoundError. Adding it
# explicitly makes the import work regardless of how the app was launched.
_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from src import pages_impl as P
from src import db


def _default_user():
    """No-login build: act as the combined Admissions team (all roles), backed by
    a real user row so the audit trail still has a valid author."""
    if "user" in st.session_state:
        return
    conn = P.get_conn()
    admin = db.get_user_by_username(conn, "admin")
    st.session_state["user"] = (
        {"user_id": admin["user_id"], "display_name": "Admissions team", "role": "admin"}
        if admin else {"user_id": None, "display_name": "Admissions team", "role": "admin"})


def build_navigation():
    """Single combined view — every section is available (no role gating)."""
    queue = st.Page(P.queue_page, title="Work queue", icon=":material/list_alt:", default=True)
    profile = st.Page(P.profile_page, title="Applicant", icon=":material/person:")
    history = st.Page(P.history_page, title="Decision history", icon=":material/history:")
    school_ver = st.Page(P.school_verification_page, title="School verification",
                         icon=":material/fact_check:")
    analytics = st.Page(P.analytics_page, title="Indicators & fairness", icon=":material/insights:")
    ml_pg = st.Page(P.predictive_analytics_page, title="Predictive analytics (research)",
                    icon=":material/science:")
    insights_pg = st.Page(P.data_insights_page, title="Data insights", icon=":material/query_stats:")
    thresholds = st.Page(P.thresholds_page, title="Thresholds", icon=":material/tune:")
    data = st.Page(P.data_page, title="Applicant data", icon=":material/database:")
    admin = st.Page(P.admin_page, title="Administration", icon=":material/admin_panel_settings:")
    settings = st.Page(P.settings_page, title="Settings", icon=":material/settings:")

    st.session_state["_pages"] = {"profile": profile, "queue": queue,
                                  "school_ver": school_ver}
    return st.navigation({
        "Review": [queue, profile, school_ver, history],
        "Oversight & governance": [insights_pg, analytics, ml_pg, thresholds],
        "Data & admin": [data, admin],
        "Account": [settings],
    })


def main():
    st.set_page_config(page_title="Academic Pre-Evaluation Dashboard",
                       page_icon=":material/school:", layout="wide")
    _default_user()
    from src.ui import inject_css, brand_footer
    from src.config import LOGO_PATH
    inject_css()
    if LOGO_PATH.exists():
        try:
            st.logo(str(LOGO_PATH), size="large")   # sits above the nav menu
        except Exception:
            try:
                st.logo(str(LOGO_PATH))
            except Exception:
                pass
    with st.sidebar:
        st.caption("Decision-support, not decision-making. "
                   "Indicators are advisory; you make the call.")
    build_navigation().run()
    brand_footer()


# `streamlit run app.py` (and Streamlit's AppTest) execute this module with a
# ScriptRunContext present — render exactly once in that case, and do nothing on a
# plain `import app`. Using ONLY this guard avoids the double-render that happens
# if both this and an `if __name__ == "__main__"` block fire under `streamlit run`.
try:
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    _HAS_CTX = get_script_run_ctx() is not None
except Exception:
    _HAS_CTX = False

if _HAS_CTX:
    main()
