-- ============================================================================
-- Academic Pre-Evaluation Dashboard — operational schema (SQLite)
-- Academic facts + reviewer workflow + versioned thresholds + audit.
-- Append-only by design for notes / decisions / evaluations / audit.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ---------- Reference / lookup ----------
CREATE TABLE IF NOT EXISTS country (
    country_code TEXT PRIMARY KEY,
    country_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS institution_tier (
    tier_code  TEXT PRIMARY KEY,
    tier_label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS institution (
    institution_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_name TEXT NOT NULL,
    country_code     TEXT NOT NULL REFERENCES country(country_code),
    tier_code        TEXT NOT NULL REFERENCES institution_tier(tier_code),
    UNIQUE (institution_name, country_code)
);

CREATE TABLE IF NOT EXISTS subject_area (
    subject_name TEXT PRIMARY KEY,
    quant_level  INTEGER NOT NULL CHECK (quant_level IN (0,1,2))
);

CREATE TABLE IF NOT EXISTS programme (
    programme_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    programme_code TEXT NOT NULL UNIQUE,         -- 'BA', 'IM'
    programme_name TEXT NOT NULL
);

-- ---------- Applicant (academic facts) ----------
CREATE TABLE IF NOT EXISTS applicant (
    applicant_id     TEXT PRIMARY KEY,
    surname          TEXT NOT NULL,
    forename         TEXT NOT NULL,
    country_code     TEXT NOT NULL REFERENCES country(country_code),
    age              INTEGER NOT NULL CHECK (age BETWEEN 20 AND 45),
    gender           TEXT NOT NULL,
    nationality_code TEXT NOT NULL REFERENCES country(country_code),
    institution_id   INTEGER NOT NULL REFERENCES institution(institution_id),
    subject_name     TEXT NOT NULL REFERENCES subject_area(subject_name),
    graduation_year  INTEGER NOT NULL CHECK (graduation_year BETWEEN 2014 AND 2026),
    grade_irish_eq   REAL CHECK (grade_irish_eq BETWEEN 0 AND 100),   -- nullable
    english_level    TEXT CHECK (english_level IN ('High','Moderate','Low')), -- nullable
    work_experience  TEXT NOT NULL,
    years_experience INTEGER NOT NULL CHECK (years_experience >= 0),
    notes_flags      TEXT,
    baseline_label   TEXT      -- legacy 'My Recommendation' kept as provenance ONLY (never shown as advice)
);

-- ---------- Application (applicant x target programme) ----------
CREATE TABLE IF NOT EXISTS application (
    application_id INTEGER PRIMARY KEY AUTOINCREMENT,
    applicant_id   TEXT NOT NULL REFERENCES applicant(applicant_id),
    programme_id   INTEGER NOT NULL REFERENCES programme(programme_id),
    submitted_at   TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open',
    UNIQUE (applicant_id, programme_id)
);

-- ---------- Users / roles ----------
CREATE TABLE IF NOT EXISTS app_user (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('reviewer','manager','governance','admin')),
    password_hash TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1
);

-- ---------- Indicator framework (versioned, reproducible) ----------
CREATE TABLE IF NOT EXISTS indicator_definition (
    indicator_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator_key TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL,
    scale_type    TEXT NOT NULL CHECK (scale_type IN ('rag','neutral','confidence')),
    display_order INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS threshold_config (
    threshold_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator_id   INTEGER NOT NULL REFERENCES indicator_definition(indicator_id),
    programme_id   INTEGER NOT NULL REFERENCES programme(programme_id),
    rule_json      TEXT NOT NULL,
    version        INTEGER NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to   TEXT,                       -- NULL = current
    created_by     INTEGER REFERENCES app_user(user_id)
);

-- Reproducible record of exactly what a reviewer saw and why (append-only).
CREATE TABLE IF NOT EXISTS indicator_evaluation (
    evaluation_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id     INTEGER NOT NULL REFERENCES application(application_id),
    indicator_id       INTEGER NOT NULL REFERENCES indicator_definition(indicator_id),
    colour             TEXT NOT NULL,          -- rag value / 'info' / confidence band
    confidence         TEXT NOT NULL,
    reasoning_text     TEXT NOT NULL,
    input_snapshot_json TEXT NOT NULL,
    threshold_version  INTEGER,
    computed_at        TEXT NOT NULL
);

-- ---------- Reviewer workflow (append-only) ----------
CREATE TABLE IF NOT EXISTS reviewer_note (
    note_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES application(application_id),
    user_id        INTEGER NOT NULL REFERENCES app_user(user_id),
    body           TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision (
    decision_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id         INTEGER NOT NULL REFERENCES application(application_id),
    user_id                INTEGER NOT NULL REFERENCES app_user(user_id),
    decision_value         TEXT NOT NULL CHECK (decision_value IN
                             ('offer','reject','more_info','defer')),
    rationale              TEXT NOT NULL,
    indicator_snapshot_json TEXT NOT NULL,
    created_at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES app_user(user_id),
    action      TEXT NOT NULL,
    entity_type TEXT,
    entity_id   TEXT,
    detail_json TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_setting (
    setting_key   TEXT PRIMARY KEY,
    setting_value TEXT
);

CREATE INDEX IF NOT EXISTS idx_app_applicant ON application(applicant_id);
CREATE INDEX IF NOT EXISTS idx_app_programme ON application(programme_id);
CREATE INDEX IF NOT EXISTS idx_note_app      ON reviewer_note(application_id);
CREATE INDEX IF NOT EXISTS idx_dec_app       ON decision(application_id);
CREATE INDEX IF NOT EXISTS idx_eval_app      ON indicator_evaluation(application_id);

-- ---------- School verification (which college/school under the declared university) ----------
-- No FK to applicant: verification can run for incoming applicants who are not
-- yet ingested into the applicant table. Append-friendly: re-runs insert new rows.
CREATE TABLE IF NOT EXISTS school_verification (
    verification_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    applicant_id        TEXT NOT NULL,
    declared_university TEXT,
    detected_university TEXT,
    detected_school     TEXT,
    confidence          REAL,
    source_document     TEXT,      -- 'transcript' / 'reference_academic'
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
