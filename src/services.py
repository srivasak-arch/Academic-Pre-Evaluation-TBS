"""Thin services layer used by the Streamlit pages. Orchestrates repositories +
rules engine; the UI never touches SQL or business logic directly."""
from __future__ import annotations
import csv, io
from . import db
from .ingest import verify_pw, CODE, TIERS
from .rules import evaluate_application


def authenticate(conn, username, password):
    user = db.get_user_by_username(conn, username)
    if user and verify_pw(password, user["password_hash"]):
        return user
    return None


def evaluate_for_display(application_row, conn=None):
    """Compute indicators for display using the CURRENT thresholds (loaded from the
    DB when a connection is supplied, so in-app edits take effect immediately).
    Does not append an evaluation row — analytics uses the pre-computed cache and
    the decision snapshot freezes what the reviewer saw."""
    app = dict(application_row)
    profile = db.load_profile(conn, app["programme_code"]) if conn is not None else None
    return evaluate_application(app, app["programme_code"], profile=profile)


def evaluate_and_record(conn, application_row):
    """Run the engine for one application and persist the evaluation (append-only)."""
    app = dict(application_row)
    profile = db.load_profile(conn, app["programme_code"])
    results = evaluate_application(app, app["programme_code"], profile=profile)
    db.save_evaluations(conn, app["application_id"], results, db.indicator_id_map(conn))
    return results


def queue(conn, **filters):
    return db.list_applications(conn, **filters)


# ---------- Threshold editing ----------
def update_thresholds(conn, programme_code, changes, user_id):
    """changes: {indicator_key: new_rule_dict}. Returns count updated."""
    n = 0
    for key, rule in changes.items():
        db.update_threshold(conn, programme_code, key, rule, user_id)
        db.audit(conn, user_id, "threshold_update", entity_type="threshold",
                 entity_id=f"{programme_code}:{key}", detail=rule)
        n += 1
    return n


def recompute_all_evaluations(conn):
    """Re-evaluate the whole cohort with current DB thresholds and replace the
    analytics cache. Call after editing thresholds or adding data."""
    id_map = db.indicator_id_map(conn)
    rows = db.list_applications(conn)
    eval_rows = []
    for row in rows:
        app = dict(row)
        profile = db.load_profile(conn, app["programme_code"])
        for r in evaluate_application(app, app["programme_code"], profile=profile):
            eval_rows.append((app["application_id"], id_map[r.key], r))
    db.replace_all_evaluations(conn, eval_rows)
    return len(rows)


# ---------- Data entry ----------
def add_student(conn, data, user_id):
    """data is a dict of applicant fields (see data_page). Creates applicant +
    application, computes & caches its evaluations. Returns the new application_id.
    Country/nationality may be given as a name (resolved/created on demand) or a code."""
    country_code = (data.get("country_code")
                    or db.get_or_create_country(conn, data.get("country_name")))
    nationality_code = (data.get("nationality_code")
                        or db.get_or_create_country(conn, data.get("nationality_name"))
                        or country_code)
    inst_id = db.get_or_create_institution(
        conn, data["institution_name"], country_code, data["tier_code"])
    app_id = db.add_applicant_and_application(
        conn,
        applicant_id=data["applicant_id"], surname=data["surname"], forename=data["forename"],
        country_code=country_code, age=data["age"], gender=data["gender"],
        nationality_code=nationality_code, institution_id=inst_id,
        subject_name=data["subject_name"], graduation_year=data["graduation_year"],
        grade_irish_eq=data["grade_irish_eq"], english_level=data["english_level"],
        work_experience=data["work_experience"], years_experience=data["years_experience"],
        programme_code=data["programme_code"])
    # compute + cache evaluations for the new record so analytics includes it
    row = db.get_application(conn, app_id)
    evaluate_and_record(conn, row)
    db.audit(conn, user_id, "applicant_add", entity_type="applicant",
             entity_id=data["applicant_id"], detail={"programme": data["programme_code"]})
    return app_id


REQUIRED_CSV_COLS = ["Surname", "Forename", "Country", "Age", "Gender", "Nationality",
                     "Institution", "Further info on institution", "Subject area",
                     "Graduation Year", "Grade (Irish eq.)", "English", "Work Experience",
                     "Years' experience"]


def bulk_add_from_csv(conn, file_bytes, programme_assignment, user_id):
    """Append applicants from an uploaded CSV (same columns as applicants.csv).
    programme_assignment: 'alternate' | 'BA' | 'IM'. Returns (added, errors)."""
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED_CSV_COLS if c not in (reader.fieldnames or [])]
    if missing:
        return 0, [f"CSV is missing required column(s): {', '.join(missing)}"]
    subjects = set(db.list_subjects(conn))
    added, errors, idx = 0, [], 0
    for i, r in enumerate(reader, start=2):
        try:
            country = r["Country"].strip()
            nat = r["Nationality"].strip() or country
            if not country:
                errors.append(f"Row {i}: missing country"); continue
            if r["Subject area"].strip() not in subjects:
                errors.append(f"Row {i}: unknown subject '{r['Subject area'].strip()}'"); continue
            tier_label = r["Further info on institution"].strip() or "Established public / regional university"
            tier_code = TIERS.get(tier_label, "Tier2")
            grade = r["Grade (Irish eq.)"].strip()
            english = r["English"].strip()
            if programme_assignment == "alternate":
                pcode = "BA" if idx % 2 == 0 else "IM"
            else:
                pcode = programme_assignment
            data = dict(
                applicant_id=db.next_applicant_id(conn),
                surname=r["Surname"].strip(), forename=r["Forename"].strip(),
                country_name=country, age=int(r["Age"]), gender=r["Gender"].strip(),
                nationality_name=nat,
                institution_name=r["Institution"].strip(), tier_code=tier_code,
                subject_name=r["Subject area"].strip(), graduation_year=int(r["Graduation Year"]),
                grade_irish_eq=float(grade) if grade else None,
                english_level=english if english in ("High", "Moderate", "Low") else None,
                work_experience=r["Work Experience"].strip() or "No experience",
                years_experience=int(r["Years' experience"] or 0),
                programme_code=pcode)
            add_student(conn, data, user_id)
            added += 1; idx += 1
        except Exception as e:                       # noqa: BLE001 - report row, keep going
            errors.append(f"Row {i}: {e}")
    return added, errors
