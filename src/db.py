"""Data-access layer: connection management + repository functions.
All SQL lives here so swapping SQLite -> PostgreSQL touches only this file."""
from __future__ import annotations
import sqlite3
import json
from datetime import datetime, timezone
from .config import DB_PATH, SCHEMA_PATH


def _database_is_initialised(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_user'"
    ).fetchone() is not None


def bootstrap_if_needed() -> None:
    """Build the database from the synthetic CSV if it is missing or empty.

    sqlite3.connect() silently creates an empty file when the database does not
    exist, so a missing DB surfaces later as 'no such table: app_user'. On hosts
    with an ephemeral filesystem (e.g. Streamlit Community Cloud) the store is
    wiped on every container rebuild, so the app must be able to reconstruct it
    from source data committed to the repository.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        if _database_is_initialised(conn):
            return
    finally:
        conn.close()
    from .ingest import build          # imported lazily to avoid a circular import
    build()


def get_connection() -> sqlite3.Connection:
    bootstrap_if_needed()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- Users ----------
def get_user_by_username(conn, username):
    return conn.execute("SELECT * FROM app_user WHERE username=? AND is_active=1",
                        (username,)).fetchone()


def list_users(conn):
    return conn.execute("SELECT user_id, username, display_name, role, is_active "
                        "FROM app_user ORDER BY role, username").fetchall()


# ---------- Programmes ----------
def list_programmes(conn):
    return conn.execute("SELECT * FROM programme ORDER BY programme_code").fetchall()


def programme_by_code(conn, code):
    return conn.execute("SELECT * FROM programme WHERE programme_code=?", (code,)).fetchone()


# ---------- Applications (enriched join used by the rules engine + UI) ----------
ENRICHED_SELECT = """
SELECT
    app.application_id, app.status, app.submitted_at,
    a.applicant_id, a.surname, a.forename, a.age, a.gender,
    a.country_code, c1.country_name AS country_name,
    a.nationality_code, c2.country_name AS nationality_name,
    a.subject_name, sa.quant_level AS subject_quant_level,
    a.graduation_year, a.grade_irish_eq, a.english_level,
    a.work_experience, a.years_experience, a.notes_flags, a.baseline_label,
    i.institution_name, i.tier_code AS institution_tier, it.tier_label,
    p.programme_id, p.programme_code, p.programme_name
FROM application app
JOIN applicant a       ON app.applicant_id = a.applicant_id
JOIN country c1        ON a.country_code = c1.country_code
JOIN country c2        ON a.nationality_code = c2.country_code
JOIN subject_area sa   ON a.subject_name = sa.subject_name
JOIN institution i     ON a.institution_id = i.institution_id
JOIN institution_tier it ON i.tier_code = it.tier_code
JOIN programme p       ON app.programme_id = p.programme_id
"""


def list_applications(conn, programme_code=None, country=None, english=None,
                      grad_year_min=None, grad_year_max=None, completeness=None,
                      decision_status=None, search_id=None):
    """Return enriched application rows. Ordering is NEUTRAL (submission order) —
    never by any quality proxy (design invariant: no ranking)."""
    sql = ENRICHED_SELECT + " WHERE 1=1"
    params = []
    if programme_code:
        sql += " AND p.programme_code=?"; params.append(programme_code)
    if country:
        sql += " AND c1.country_name=?"; params.append(country)
    if english == "Pending":
        sql += " AND a.english_level IS NULL"
    elif english:
        sql += " AND a.english_level=?"; params.append(english)
    if grad_year_min:
        sql += " AND a.graduation_year>=?"; params.append(grad_year_min)
    if grad_year_max:
        sql += " AND a.graduation_year<=?"; params.append(grad_year_max)
    if completeness == "Ready to review":
        sql += " AND a.grade_irish_eq IS NOT NULL AND a.english_level IS NOT NULL"
    elif completeness == "Awaiting evidence":
        sql += " AND (a.grade_irish_eq IS NULL OR a.english_level IS NULL)"
    if search_id:
        sql += " AND a.applicant_id LIKE ?"; params.append(f"%{search_id}%")
    sql += " ORDER BY app.submitted_at ASC, app.application_id ASC"
    rows = conn.execute(sql, params).fetchall()
    if decision_status in ("Undecided", "Decided"):
        decided = decided_application_ids(conn)
        if decision_status == "Decided":
            rows = [r for r in rows if r["application_id"] in decided]
        else:
            rows = [r for r in rows if r["application_id"] not in decided]
    return rows


def get_application(conn, application_id):
    return conn.execute(ENRICHED_SELECT + " WHERE app.application_id=?",
                        (application_id,)).fetchone()


def distinct_countries(conn):
    return [r["country_name"] for r in conn.execute(
        "SELECT DISTINCT country_name FROM country ORDER BY country_name").fetchall()]


# ---------- Notes (append-only) ----------
def add_note(conn, application_id, user_id, body):
    conn.execute("INSERT INTO reviewer_note(application_id,user_id,body,created_at) "
                 "VALUES (?,?,?,?)", (application_id, user_id, body, now_iso()))
    conn.commit()


def list_notes(conn, application_id):
    return conn.execute(
        "SELECT n.*, u.display_name FROM reviewer_note n JOIN app_user u ON n.user_id=u.user_id "
        "WHERE application_id=? ORDER BY created_at DESC, note_id DESC", (application_id,)).fetchall()


# ---------- Decisions (append-only) ----------
def add_decision(conn, application_id, user_id, decision_value, rationale, indicator_snapshot):
    conn.execute(
        "INSERT INTO decision(application_id,user_id,decision_value,rationale,"
        "indicator_snapshot_json,created_at) VALUES (?,?,?,?,?,?)",
        (application_id, user_id, decision_value, rationale,
         json.dumps(indicator_snapshot), now_iso()))
    conn.commit()


def list_decisions(conn, application_id=None, user_id=None):
    sql = ("SELECT d.*, u.display_name, a.applicant_id, p.programme_code "
           "FROM decision d JOIN app_user u ON d.user_id=u.user_id "
           "JOIN application app ON d.application_id=app.application_id "
           "JOIN applicant a ON app.applicant_id=a.applicant_id "
           "JOIN programme p ON app.programme_id=p.programme_id WHERE 1=1")
    params = []
    if application_id:
        sql += " AND d.application_id=?"; params.append(application_id)
    if user_id:
        sql += " AND d.user_id=?"; params.append(user_id)
    sql += " ORDER BY d.created_at DESC, d.decision_id DESC"
    return conn.execute(sql, params).fetchall()


def decided_application_ids(conn):
    return {r["application_id"] for r in
            conn.execute("SELECT DISTINCT application_id FROM decision").fetchall()}


def latest_decision(conn, application_id):
    return conn.execute("SELECT * FROM decision WHERE application_id=? "
                        "ORDER BY created_at DESC, decision_id DESC LIMIT 1", (application_id,)).fetchone()


# ---------- Indicator evaluations (append-only, reproducible) ----------
def save_evaluations(conn, application_id, results, indicator_id_map, threshold_version=1):
    ts = now_iso()
    for r in results:
        ind_id = indicator_id_map.get(r.key)
        conn.execute(
            "INSERT INTO indicator_evaluation(application_id,indicator_id,colour,confidence,"
            "reasoning_text,input_snapshot_json,threshold_version,computed_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (application_id, ind_id, r.value, r.confidence, r.reasoning,
             json.dumps(r.inputs), threshold_version, ts))
    conn.commit()


def indicator_id_map(conn):
    return {r["indicator_key"]: r["indicator_id"]
            for r in conn.execute("SELECT indicator_key,indicator_id FROM indicator_definition")}


# ---------- Audit (append-only) ----------
def audit(conn, user_id, action, entity_type=None, entity_id=None, detail=None):
    conn.execute(
        "INSERT INTO audit_log(user_id,action,entity_type,entity_id,detail_json,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, action, entity_type, str(entity_id) if entity_id is not None else None,
         json.dumps(detail) if detail else None, now_iso()))
    conn.commit()


def list_audit(conn, limit=300):
    return conn.execute(
        "SELECT al.*, u.display_name FROM audit_log al "
        "LEFT JOIN app_user u ON al.user_id=u.user_id "
        "ORDER BY al.created_at DESC LIMIT ?", (limit,)).fetchall()


# ---------- Analytics (non-ranking aggregates only) ----------
def indicator_distribution(conn, programme_code=None):
    """Colour split per indicator, optionally by programme. For the fairness view.
    Aggregates across the cohort — never ranks individuals."""
    sql = ("SELECT id.indicator_key, ie.colour, COUNT(*) AS n "
           "FROM indicator_evaluation ie "
           "JOIN indicator_definition id ON ie.indicator_id=id.indicator_id "
           "JOIN application app ON ie.application_id=app.application_id "
           "JOIN programme p ON app.programme_id=p.programme_id ")
    params = []
    if programme_code:
        sql += "WHERE p.programme_code=? "; params.append(programme_code)
    sql += "GROUP BY id.indicator_key, ie.colour"
    return conn.execute(sql, params).fetchall()


# ---------- Editable, versioned thresholds ----------
# Only the editable numeric/scalar keys are overlaid from the DB; categorical
# subject sets stay in code defaults (rules.PROGRAMME_PROFILES).
EDITABLE_OVERLAY = {
    "academic_performance": "dict",        # {green_min, amber_min}
    "graduation_recency": "dict",          # {green_max, amber_max}
    "document_completeness": "dict",        # {amber_missing, red_missing}
    "quantitative_readiness": "quant_green_grade_min",  # scalar (BA)
    "work_experience": "work_experience_mode",          # scalar
}


def current_thresholds(conn, programme_code):
    """Return {indicator_key: rule_dict} for the CURRENT (open) version per indicator."""
    rows = conn.execute(
        "SELECT idf.indicator_key, tc.rule_json, tc.version "
        "FROM threshold_config tc "
        "JOIN programme p ON tc.programme_id=p.programme_id "
        "JOIN indicator_definition idf ON tc.indicator_id=idf.indicator_id "
        "WHERE p.programme_code=? AND tc.effective_to IS NULL "
        "ORDER BY idf.display_order", (programme_code,)).fetchall()
    return {r["indicator_key"]: {"rule": json.loads(r["rule_json"]), "version": r["version"]}
            for r in rows}


def load_profile(conn, programme_code):
    """Build the rules-engine profile from code defaults + current DB overrides.
    Lets in-app threshold edits take effect without touching code."""
    import copy
    from .rules import PROGRAMME_PROFILES
    prof = copy.deepcopy(PROGRAMME_PROFILES[programme_code])
    cur = current_thresholds(conn, programme_code)
    for key, how in EDITABLE_OVERLAY.items():
        if key not in cur:
            continue
        rule = cur[key]["rule"]
        if how == "dict":
            prof[key] = rule
        elif how in rule:                 # scalar key present in stored rule
            prof[how] = rule[how]
    return prof


def update_threshold(conn, programme_code, indicator_key, new_rule, user_id):
    """Append a NEW version (close the previous), never overwrite — so any past
    decision can still be replayed against the rules that were in force."""
    prog = conn.execute("SELECT programme_id FROM programme WHERE programme_code=?",
                        (programme_code,)).fetchone()["programme_id"]
    ind = conn.execute("SELECT indicator_id FROM indicator_definition WHERE indicator_key=?",
                       (indicator_key,)).fetchone()["indicator_id"]
    cur = conn.execute(
        "SELECT threshold_id, version FROM threshold_config "
        "WHERE programme_id=? AND indicator_id=? AND effective_to IS NULL "
        "ORDER BY version DESC LIMIT 1", (prog, ind)).fetchone()
    ts = now_iso()
    new_version = (cur["version"] + 1) if cur else 1
    if cur:
        conn.execute("UPDATE threshold_config SET effective_to=? WHERE threshold_id=?",
                     (ts, cur["threshold_id"]))
    conn.execute(
        "INSERT INTO threshold_config(indicator_id,programme_id,rule_json,version,"
        "effective_from,created_by) VALUES (?,?,?,?,?,?)",
        (ind, prog, json.dumps(new_rule), new_version, ts, user_id))
    conn.commit()
    return new_version


def threshold_history(conn, programme_code=None):
    sql = ("SELECT p.programme_code, idf.name, idf.scale_type, tc.rule_json, tc.version, "
           "tc.effective_from, tc.effective_to "
           "FROM threshold_config tc "
           "JOIN programme p ON tc.programme_id=p.programme_id "
           "JOIN indicator_definition idf ON tc.indicator_id=idf.indicator_id ")
    params = []
    if programme_code:
        sql += "WHERE p.programme_code=? "; params.append(programme_code)
    sql += "ORDER BY p.programme_code, idf.display_order, tc.version DESC"
    return conn.execute(sql, params).fetchall()


# ---------- Reference helpers for data entry ----------
def list_subjects(conn):
    return [r["subject_name"] for r in conn.execute(
        "SELECT subject_name FROM subject_area ORDER BY subject_name")]


def list_countries(conn):
    return [(r["country_code"], r["country_name"]) for r in conn.execute(
        "SELECT country_code, country_name FROM country ORDER BY country_name")]


def list_tiers(conn):
    return [(r["tier_code"], r["tier_label"]) for r in conn.execute(
        "SELECT tier_code, tier_label FROM institution_tier ORDER BY tier_code")]


def cohort_size(conn):
    return conn.execute("SELECT COUNT(*) FROM applicant").fetchone()[0]


def next_applicant_id(conn):
    row = conn.execute(
        "SELECT applicant_id FROM applicant WHERE applicant_id LIKE 'TBS-2026-%' "
        "ORDER BY applicant_id DESC LIMIT 1").fetchone()
    n = int(row["applicant_id"].split("-")[-1]) + 1 if row else 1
    return f"TBS-2026-{n:04d}"


def get_or_create_institution(conn, name, country_code, tier_code):
    row = conn.execute(
        "SELECT institution_id FROM institution WHERE institution_name=? AND country_code=?",
        (name, country_code)).fetchone()
    if row:
        return row["institution_id"]
    cur = conn.execute(
        "INSERT INTO institution(institution_name,country_code,tier_code) VALUES (?,?,?)",
        (name, country_code, tier_code))
    conn.commit()
    return cur.lastrowid


def add_applicant_and_application(conn, *, applicant_id, surname, forename, country_code,
                                  age, gender, nationality_code, institution_id, subject_name,
                                  graduation_year, grade_irish_eq, english_level, work_experience,
                                  years_experience, programme_code):
    conn.execute(
        "INSERT INTO applicant(applicant_id,surname,forename,country_code,age,gender,"
        "nationality_code,institution_id,subject_name,graduation_year,grade_irish_eq,"
        "english_level,work_experience,years_experience,notes_flags,baseline_label) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (applicant_id, surname, forename, country_code, age, gender, nationality_code,
         institution_id, subject_name, graduation_year, grade_irish_eq, english_level,
         work_experience, years_experience, None, None))
    prog = conn.execute("SELECT programme_id FROM programme WHERE programme_code=?",
                        (programme_code,)).fetchone()["programme_id"]
    cur = conn.execute(
        "INSERT INTO application(applicant_id,programme_id,submitted_at,status) VALUES (?,?,?,?)",
        (applicant_id, prog, now_iso(), "open"))
    conn.commit()
    return cur.lastrowid


def replace_all_evaluations(conn, eval_rows):
    """For recompute: clear and re-insert the cohort evaluation cache used by analytics."""
    conn.execute("DELETE FROM indicator_evaluation")
    ts = now_iso()
    for app_id, ind_id, r in eval_rows:
        conn.execute(
            "INSERT INTO indicator_evaluation(application_id,indicator_id,colour,confidence,"
            "reasoning_text,input_snapshot_json,threshold_version,computed_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (app_id, ind_id, r.value, r.confidence, r.reasoning,
             json.dumps(r.inputs), 1, ts))
    conn.commit()


def get_or_create_country(conn, name, code=None):
    """Resolve a country name to a code, creating the country on demand so
    applicants from any country can be added. Falls back to a generated code."""
    from .countries import COUNTRIES
    name = (name or "").strip()
    if not name:
        return None
    row = conn.execute("SELECT country_code FROM country WHERE country_name=?", (name,)).fetchone()
    if row:
        return row["country_code"]
    existing = {r["country_code"] for r in conn.execute("SELECT country_code FROM country")}
    base = (code or COUNTRIES.get(name) or "".join(ch for ch in name.upper() if ch.isalpha())[:2] or "XX")
    cand, i = base, 1
    while cand in existing:
        i += 1
        cand = (base[:2] + str(i))[:4]
    conn.execute("INSERT INTO country(country_code,country_name) VALUES (?,?)", (cand, name))
    conn.commit()
    return cand


def evaluations_for_applications(conn, app_ids):
    """Latest cached indicator outcomes for a set of applications (for analytics).
    Returns rows: application_id, indicator_key, colour, confidence."""
    if not app_ids:
        return []
    placeholders = ",".join("?" * len(app_ids))
    return conn.execute(
        f"SELECT ie.application_id, idf.indicator_key, ie.colour, ie.confidence "
        f"FROM indicator_evaluation ie "
        f"JOIN indicator_definition idf ON ie.indicator_id = idf.indicator_id "
        f"WHERE ie.application_id IN ({placeholders})", list(app_ids)).fetchall()


# ---------- School verification (which school under the declared university) ----------
_SV_DDL_DONE = False

def ensure_school_schema(conn):
    """Idempotent migration for databases created before this feature existed."""
    global _SV_DDL_DONE
    if _SV_DDL_DONE:
        return
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS school_verification (
            verification_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            applicant_id        TEXT NOT NULL,
            declared_university TEXT,
            detected_university TEXT,
            detected_school     TEXT,
            confidence          REAL,
            source_document     TEXT,
            source_page         INTEGER,
            evidence_snippet    TEXT,
            corroborated        INTEGER NOT NULL DEFAULT 0,
            university_mismatch INTEGER NOT NULL DEFAULT 0,
            notes               TEXT,
            status              TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','confirmed','corrected')),
            verified_school     TEXT,
            verified_by         INTEGER REFERENCES app_user(user_id),
            verified_at         TEXT,
            created_at          TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sv_applicant ON school_verification(applicant_id);
    """)
    conn.commit()
    _SV_DDL_DONE = True


def add_school_verification(conn, rec: dict) -> int:
    ensure_school_schema(conn)
    cur = conn.execute(
        """INSERT INTO school_verification
           (applicant_id, declared_university, detected_university, detected_school,
            confidence, source_document, source_page, evidence_snippet,
            corroborated, university_mismatch, notes, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rec["applicant_id"], rec.get("declared_university"),
         rec.get("detected_university"), rec.get("detected_school"),
         rec.get("confidence"), rec.get("source_document"), rec.get("source_page"),
         rec.get("evidence_snippet"), int(rec.get("corroborated", 0)),
         int(rec.get("university_mismatch", 0)), rec.get("notes"),
         rec.get("status", "pending"), now_iso()))
    conn.commit()
    return cur.lastrowid


def resolve_school_verification(conn, verification_id, verified_school, user_id, status):
    """status: 'confirmed' (matches detection) or 'corrected' (reviewer overrode)."""
    ensure_school_schema(conn)
    conn.execute(
        "UPDATE school_verification SET verified_school=?, verified_by=?, "
        "verified_at=?, status=? WHERE verification_id=?",
        (verified_school, user_id, now_iso(), status, verification_id))
    conn.commit()


def list_school_verifications(conn, status=None):
    ensure_school_schema(conn)
    sql = ("SELECT sv.*, u.display_name AS verified_by_name "
           "FROM school_verification sv "
           "LEFT JOIN app_user u ON sv.verified_by = u.user_id")
    params = []
    if status:
        sql += " WHERE sv.status=?"; params.append(status)
    sql += " ORDER BY sv.created_at DESC, sv.verification_id DESC"
    return conn.execute(sql, params).fetchall()


def latest_school_verification(conn, applicant_id):
    ensure_school_schema(conn)
    return conn.execute(
        "SELECT * FROM school_verification WHERE applicant_id=? "
        "ORDER BY verification_id DESC LIMIT 1", (applicant_id,)).fetchone()


# ---------- Research-track ML tables (NEVER feed the advisory indicators) ----------
_ML_DDL_DONE = False

def ensure_ml_schema(conn):
    global _ML_DDL_DONE
    if _ML_DDL_DONE:
        return
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ml_run (
            run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            seed           INTEGER NOT NULL,
            target_def     TEXT NOT NULL,
            n_train        INTEGER NOT NULL,
            n_test         INTEGER NOT NULL,
            data_hash      TEXT NOT NULL,
            selected_model TEXT NOT NULL,
            params_json    TEXT NOT NULL,
            results_json   TEXT NOT NULL,
            created_at     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ml_prediction (
            prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id        INTEGER NOT NULL REFERENCES ml_run(run_id),
            model_name    TEXT NOT NULL,
            applicant_id  TEXT NOT NULL,
            y_true        INTEGER NOT NULL,
            p_uncalibrated REAL NOT NULL,
            p_calibrated   REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mlpred_run ON ml_prediction(run_id);
    """)
    conn.commit()
    _ML_DDL_DONE = True


def add_ml_run(conn, rec: dict) -> int:
    ensure_ml_schema(conn)
    cur = conn.execute(
        """INSERT INTO ml_run (seed, target_def, n_train, n_test, data_hash,
                               selected_model, params_json, results_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (rec["seed"], rec["target_def"], rec["n_train"], rec["n_test"],
         rec["data_hash"], rec["selected_model"], rec["params_json"],
         rec["results_json"], now_iso()))
    conn.commit()
    return cur.lastrowid


def add_ml_predictions(conn, run_id, model_name, applicant_ids, y_true, p_uncal, p_cal):
    ensure_ml_schema(conn)
    conn.executemany(
        "INSERT INTO ml_prediction (run_id, model_name, applicant_id, y_true, "
        "p_uncalibrated, p_calibrated) VALUES (?,?,?,?,?,?)",
        [(run_id, model_name, a, int(y), float(pu), float(pc))
         for a, y, pu, pc in zip(applicant_ids, y_true, p_uncal, p_cal)])
    conn.commit()


def latest_ml_run(conn):
    ensure_ml_schema(conn)
    return conn.execute("SELECT * FROM ml_run ORDER BY run_id DESC LIMIT 1").fetchone()
