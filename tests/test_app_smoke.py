"""Headless smoke test for the no-login build: the app opens straight into the
combined view. Verify core pages render without exceptions."""
from streamlit.testing.v1 import AppTest
import pathlib

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")


def test_app_opens_without_login():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert "user" in at.session_state                 # auto-entered
    assert at.session_state["user"]["role"] == "admin"


def test_queue_is_default_page():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert any("Work queue" in m.value for m in at.markdown if isinstance(m.value, str))


def test_queue_renders_selectable_dataframe():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert len(at.dataframe) == 1          # queue is now a single sortable dataframe
    assert not [b for b in at.button if b.label == "Review"]  # old per-row buttons gone


def test_profile_opens_when_application_selected():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.session_state["goto_application"] = 1
    at.run()
    assert not at.exception
