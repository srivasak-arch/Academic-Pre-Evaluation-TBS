"""Workflow-level tests exercising the substantive persistence logic directly
(notes, decisions, frozen indicator snapshot, audit) — independent of the UI
navigation harness."""
import json
import pytest
from src import db, services


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """A disposable copy of the real database.

    Workflow tests exercise real writes (add_student, threshold edits), so they
    must never run against data/dashboard.db — earlier versions of this fixture
    did, and every pytest run permanently appended test applicants ('Ada Test',
    'Yuki Sato') to the shipped database.
    """
    import shutil, sqlite3
    dst = tmp_path / "dashboard.db"
    shutil.copy(db.DB_PATH, dst)
    monkeypatch.setattr(db, "DB_PATH", dst)
    c = sqlite3.connect(dst, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    yield c
    c.close()


def test_evaluate_for_display_returns_ten_and_does_not_persist(conn):
    before = conn.execute("SELECT COUNT(*) FROM indicator_evaluation").fetchone()[0]
    row = db.get_application(conn, 1)
    results = services.evaluate_for_display(row)
    after = conn.execute("SELECT COUNT(*) FROM indicator_evaluation").fetchone()[0]
    assert len(results) == 10
    assert before == after  # display path must not append evaluation rows


def test_note_is_append_only(conn):
    app_id = 2
    n0 = len(db.list_notes(conn, app_id))
    db.add_note(conn, app_id, 1, "First observation.")
    db.add_note(conn, app_id, 1, "Second observation.")
    notes = db.list_notes(conn, app_id)
    assert len(notes) == n0 + 2
    # newest first
    assert notes[0]["body"] == "Second observation."


def test_decision_persists_with_frozen_snapshot_and_audit(conn):
    app_id = 3
    row = db.get_application(conn, app_id)
    results = services.evaluate_for_display(row)
    snapshot = [{"key": r.key, "value": r.value, "confidence": r.confidence} for r in results]
    db.add_decision(conn, app_id, 1, "more_info", "English evidence pending.", snapshot)
    db.audit(conn, 1, "decision_record", entity_type="application", entity_id=app_id,
             detail={"decision": "more_info"})

    latest = db.latest_decision(conn, app_id)
    assert latest["decision_value"] == "more_info"
    frozen = json.loads(latest["indicator_snapshot_json"])
    assert len(frozen) == 10  # full evidence state frozen at decision time

    audits = [a for a in db.list_audit(conn) if a["action"] == "decision_record"]
    assert len(audits) >= 1


def test_decisions_are_appended_never_overwritten(conn):
    app_id = 4
    row = db.get_application(conn, app_id)
    snap = [{"key": r.key, "value": r.value} for r in services.evaluate_for_display(row)]
    db.add_decision(conn, app_id, 1, "defer", "Awaiting references.", snap)
    db.add_decision(conn, app_id, 1, "offer", "References received; strong profile.", snap)
    all_decs = db.list_decisions(conn, application_id=app_id)
    assert len(all_decs) >= 2
    assert db.latest_decision(conn, app_id)["decision_value"] == "offer"


def test_queue_ordering_is_neutral_not_by_quality(conn):
    """The queue must be ordered by submission, never by indicator outcomes."""
    rows = db.list_applications(conn, programme_code="BA")
    submitted = [r["submitted_at"] for r in rows]
    assert submitted == sorted(submitted)  # ascending submission order


def test_threshold_edit_creates_new_version_and_changes_results(conn):
    from src import services
    # baseline: a 62% grade is green for BA (green_min 65? no -> amber). Make green_min 60.
    row = db.get_application(conn, 1)
    before = services.evaluate_for_display(row, conn)
    ap_before = [r for r in before if r.key == "academic_performance"][0]
    # raise/lower the academic green threshold and confirm a new version + effect
    services.update_thresholds(conn, row["programme_code"],
                               {"academic_performance": {"green_min": 50, "amber_min": 40}}, 1)
    after = services.evaluate_for_display(row, conn)
    ap_after = [r for r in after if r.key == "academic_performance"][0]
    hist = [h for h in db.threshold_history(conn, row["programme_code"])
            if h["name"] == "Academic Performance"]
    assert max(h["version"] for h in hist) >= 2          # new version appended
    # with a much lower green threshold, a mid grade should now be green
    if ap_before.value in ("amber", "red") and row["grade_irish_eq"] and row["grade_irish_eq"] >= 50:
        assert ap_after.value == "green"


def test_add_student_appends_and_is_evaluated(conn):
    from src import services
    n0 = db.cohort_size(conn)
    data = dict(
        applicant_id=db.next_applicant_id(conn), surname="Test", forename="Ada",
        country_code="IE", nationality_code="IE", age=23, gender="Female",
        institution_name="New College of Analytics", tier_code="Tier2",
        subject_name="Data Science", graduation_year=2025, grade_irish_eq=71.0,
        english_level="High", work_experience="Internships", years_experience=0,
        programme_code="BA")
    app_id = services.add_student(conn, data, 1)
    assert db.cohort_size(conn) == n0 + 1
    row = db.get_application(conn, app_id)
    assert row["applicant_id"] == data["applicant_id"]
    # its evaluations were cached (10 indicators)
    n_eval = conn.execute("SELECT COUNT(*) FROM indicator_evaluation WHERE application_id=?",
                          (app_id,)).fetchone()[0]
    assert n_eval == 10


def test_add_applicant_from_new_country(conn):
    """A country not in the original seed set is accepted and created on demand."""
    from src import services
    import uuid
    cname = f"Testlandia-{uuid.uuid4().hex[:6]}"
    before = conn.execute("SELECT COUNT(*) FROM country WHERE country_name=?", (cname,)).fetchone()[0]
    data = dict(
        applicant_id=db.next_applicant_id(conn), surname="Sato", forename="Yuki",
        country_name=cname, nationality_name=cname, age=24, gender="Female",
        institution_name="Tokyo Institute", tier_code="Tier1",
        subject_name="Computer Science", graduation_year=2025, grade_irish_eq=74.0,
        english_level="High", work_experience="Internships", years_experience=0,
        programme_code="BA")
    app_id = services.add_student(conn, data, 1)
    row = db.get_application(conn, app_id)
    assert row["country_name"] == cname
    assert conn.execute("SELECT COUNT(*) FROM country WHERE country_name=?", (cname,)).fetchone()[0] == 1
    assert before == 0


def test_insights_data_loads_and_aggregates(conn):
    from src import insights
    data = insights.load_insight_data(conn)
    assert data.n > 0
    # derived columns present
    for col in ("grade_band", "years_since_grad", "readiness", "n_missing", "is_decided"):
        assert col in data.df.columns
    # indicator outcomes pivoted (10 indicators as columns)
    assert not data.eval_wide.empty
    assert data.eval_wide.shape[1] == 10
    # share table sums to ~100%
    st = insights.share_table(data.df, "programme_code")
    assert abs(st["pct"].sum() - 100) < 1.0


def test_insights_respects_filters(conn):
    from src import insights
    all_n = insights.load_insight_data(conn).n
    ba_n = insights.load_insight_data(conn, programme_code="BA").n
    im_n = insights.load_insight_data(conn, programme_code="IM").n
    assert ba_n + im_n == all_n and 0 < ba_n < all_n


def test_fairness_crosstab_suppresses_small_groups(conn):
    from src import insights
    data = insights.load_insight_data(conn)
    longdf, suppressed = insights.crosstab_rag(data.df, data.eval_wide,
                                               "country_name", "academic_performance", min_n=12)
    # every shown group must have at least min_n records
    if not longdf.empty:
        sizes = longdf.groupby("country_name")["n"].sum()
        assert (sizes >= 12).all()
