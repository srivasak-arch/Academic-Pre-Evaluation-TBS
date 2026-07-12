"""
Ingestion / bootstrap. Builds the SQLite database from the synthetic CSV and
seeds operational data: programmes, users, indicator definitions, versioned
thresholds, and one application per applicant (assigned to a target programme).

Run:  python -m src.ingest        (from the project root)
Idempotent: drops and rebuilds dashboard.db.
"""
from __future__ import annotations
import sqlite3, json, hashlib, hmac, os, csv
from datetime import datetime, timezone

from .config import DB_PATH, CSV_PATH, SCHEMA_PATH, PROGRAMMES, INDICATOR_ORDER
from .rules import ALL_SUBJECTS, PROGRAMME_PROFILES, NAMES

CODE = {"Ireland":"IE","United Kingdom":"GB","United States":"US","India":"IN","China":"CN",
        "Nigeria":"NG","Germany":"DE","Brazil":"BR","Pakistan":"PK","France":"FR"}
TIERS = {"Research-intensive flagship university":"Tier1",
         "Established public / regional university":"Tier2",
         "Teaching-focused or private college":"Tier3"}
TIER_LABEL = {v:k for k,v in TIERS.items()}

# --- lightweight password hashing (POC). Production: bcrypt/argon2 via streamlit-authenticator ---
_SALT = b"tbs-team-a-poc-salt"
def hash_pw(pw: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), _SALT, 100_000).hex()

def verify_pw(pw: str, stored: str) -> bool:
    return hmac.compare_digest(hash_pw(pw), stored)

SCALE = {  # indicator -> scale type
    "academic_performance":"rag","programme_prerequisites":"rag","quantitative_readiness":"rag",
    "english_requirement":"rag","institution_context":"neutral","subject_alignment":"rag",
    "work_experience":"rag","graduation_recency":"rag","document_completeness":"rag",
    "evidence_confidence":"confidence",
}
DESC = {
    "academic_performance":"Prior degree result, normalised to Irish equivalent.",
    "programme_prerequisites":"Whether subject prerequisites for the target programme are covered (gate).",
    "quantitative_readiness":"Depth of maths/analytical preparation for the programme.",
    "english_requirement":"Postgraduate-level English proficiency.",
    "institution_context":"Awarding institution context. Neutral metadata — never scored.",
    "subject_alignment":"Fit/breadth of the field versus the programme core.",
    "work_experience":"Relevant professional experience (programme-weighted).",
    "graduation_recency":"How recent the academic record is.",
    "document_completeness":"Whether the evidence base is complete enough to review (routing).",
    "evidence_confidence":"Meta-signal on evidence quality — not applicant quality.",
}

DEFAULT_USERS = [
    ("rkelly",  "Reviewer Kelly",    "reviewer",   "reviewer123"),
    ("rsingh",  "Reviewer Singh",    "reviewer",   "reviewer123"),
    ("mmanager","Admissions Manager","manager",    "manager123"),
    ("qgov",    "Governance Officer","governance", "gov123"),
    ("admin",   "System Admin",      "admin",      "admin123"),
]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())

    # ----- reference -----
    for name, code in CODE.items():
        conn.execute("INSERT INTO country VALUES (?,?)", (code, name))
    for code, label in TIER_LABEL.items():
        conn.execute("INSERT INTO institution_tier VALUES (?,?)", (code, label))
    for subj, q in ALL_SUBJECTS.items():
        conn.execute("INSERT INTO subject_area VALUES (?,?)", (subj, q))

    prog_id = {}
    for code, name in PROGRAMMES.items():
        cur = conn.execute("INSERT INTO programme(programme_code,programme_name) VALUES (?,?)",
                           (code, name))
        prog_id[code] = cur.lastrowid

    # ----- users -----
    for username, display, role, pw in DEFAULT_USERS:
        conn.execute("INSERT INTO app_user(username,display_name,role,password_hash) VALUES (?,?,?,?)",
                     (username, display, role, hash_pw(pw)))
    admin_id = conn.execute("SELECT user_id FROM app_user WHERE username='admin'").fetchone()[0]

    # ----- indicator definitions -----
    ind_id = {}
    for order, key in enumerate(INDICATOR_ORDER):
        cur = conn.execute(
            "INSERT INTO indicator_definition(indicator_key,name,description,scale_type,display_order) "
            "VALUES (?,?,?,?,?)", (key, NAMES[key], DESC[key], SCALE[key], order))
        ind_id[key] = cur.lastrowid

    # ----- versioned thresholds (one row per indicator per programme) -----
    for pcode, prof in PROGRAMME_PROFILES.items():
        for key in INDICATOR_ORDER:
            rule = _rule_for(prof, key)
            conn.execute(
                "INSERT INTO threshold_config(indicator_id,programme_id,rule_json,version,"
                "effective_from,created_by) VALUES (?,?,?,?,?,?)",
                (ind_id[key], prog_id[pcode], json.dumps(rule, default=list), 1,
                 now_iso(), admin_id))

    # ----- applicants + applications -----
    inst_map = {}
    def inst_lookup(name, country_name, tier_label):
        key = (name, country_name)
        if key in inst_map:
            return inst_map[key]
        tier = TIERS.get(tier_label, "Tier2")
        cur = conn.execute(
            "INSERT INTO institution(institution_name,country_code,tier_code) VALUES (?,?,?)",
            (name, CODE[country_name], tier))
        inst_map[key] = cur.lastrowid
        return cur.lastrowid

    # alternate applicants across the two programmes so both have a full queue
    n = 0
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            country = row["Country"]
            tier_label = row["Further info on institution"].strip() or "Established public / regional university"
            inst_id = inst_lookup(row["Institution"], country, tier_label)
            grade = row["Grade (Irish eq.)"].strip()
            english = row["English"].strip()
            conn.execute(
                "INSERT INTO applicant(applicant_id,surname,forename,country_code,age,gender,"
                "nationality_code,institution_id,subject_name,graduation_year,grade_irish_eq,"
                "english_level,work_experience,years_experience,notes_flags,baseline_label) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["ID"], row["Surname"], row["Forename"], CODE[country], int(row["Age"]),
                 row["Gender"], CODE[row["Nationality"]], inst_id, row["Subject area"],
                 int(row["Graduation Year"]), float(grade) if grade else None,
                 english if english else None, row["Work Experience"],
                 int(row["Years' experience"]), row["Notes"].strip() or None,
                 row["My Recommendation"].strip() or None))
            pcode = "BA" if (n % 2 == 0) else "IM"
            conn.execute(
                "INSERT INTO application(applicant_id,programme_id,submitted_at,status) "
                "VALUES (?,?,?,?)", (row["ID"], prog_id[pcode], now_iso(), "open"))
            n += 1

    conn.execute("INSERT INTO audit_log(user_id,action,detail_json,created_at) VALUES (?,?,?,?)",
                 (admin_id, "ingest_complete", json.dumps({"applicants": n}), now_iso()))
    conn.commit()

    # pre-compute evaluations for the whole cohort: validates the engine at scale
    # and powers the analytics/fairness view before any profile is opened.
    from .db import ENRICHED_SELECT
    from .rules import evaluate_application
    rows = conn.execute(ENRICHED_SELECT).fetchall()
    ts = now_iso()
    for r in rows:
        app = dict(r)
        for res in evaluate_application(app, app["programme_code"]):
            conn.execute(
                "INSERT INTO indicator_evaluation(application_id,indicator_id,colour,confidence,"
                "reasoning_text,input_snapshot_json,threshold_version,computed_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (app["application_id"], ind_id[res.key], res.value, res.confidence,
                 res.reasoning, json.dumps(res.inputs), 1, ts))
    conn.commit()

    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("applicant","application","programme","app_user",
                        "indicator_definition","threshold_config","institution",
                        "indicator_evaluation")}
    conn.close()
    return counts


def _rule_for(prof, key):
    """Extract the relevant slice of the programme profile for a given indicator,
    so the threshold is stored as versioned config (auditable, replayable)."""
    if key == "academic_performance":
        return prof["academic_performance"]
    if key == "graduation_recency":
        return prof["graduation_recency"]
    if key == "document_completeness":
        return prof["document_completeness"]
    if key == "programme_prerequisites":
        return {k: prof[k] for k in prof if k.startswith("prereq")}
    if key == "quantitative_readiness":
        return {k: prof[k] for k in prof if k.startswith("quant")}
    if key == "subject_alignment":
        return {"align_strong": prof["align_strong"], "align_adjacent": prof["align_adjacent"]}
    if key == "work_experience":
        return {"work_experience_mode": prof["work_experience_mode"]}
    return {"note": "deterministic; see rules engine"}


if __name__ == "__main__":
    c = build()
    print("Database built at", DB_PATH)
    for k, v in c.items():
        print(f"  {k:24s} {v}")
