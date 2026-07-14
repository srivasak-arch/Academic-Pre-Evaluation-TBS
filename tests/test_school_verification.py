"""Tests for the school-verification feature: detection rules, document handling,
and the append-only DB round-trip."""
import sqlite3

import pytest

from src import db
from src.school_detect import verify_schooling, detect_university
from src.school_reference import resolve_university, school_names_for
from src.school_service import (applicant_key_from_filename, classify_document,
                                confirm_school)


def pages(text):
    return [{"page": 1, "text": text, "ocr": False}]


TRANSCRIPT_DU = pages(
    "Shri Ram College of Commerce\nA constituent college of the University of Delhi\n"
    "OFFICIAL ACADEMIC TRANSCRIPT\nCollege: Shri Ram College of Commerce")
REF_ACADEMIC_DU = pages(
    "Shri Ram College of Commerce, University of Delhi\nLetter of Recommendation")
CV_ONLY = pages("Education: B.Com (Hons.), University of Delhi, 2021-2024")


# ---------------- Reference data ----------------
def test_university_aliases_resolve():
    assert resolve_university("delhi university") == "University of Delhi"
    assert resolve_university("DU") == "University of Delhi"
    assert resolve_university("University of Pune") == "Savitribai Phule Pune University"
    assert resolve_university("nonexistent") is None


def test_school_lists_are_per_university():
    du = school_names_for("University of Delhi")
    assert "Hindu College" in du
    assert "Fergusson College" not in du          # belongs to Pune, not Delhi


# ---------------- Detection rules ----------------
def test_transcript_is_authoritative_and_corroborated():
    det = verify_schooling({"transcript": TRANSCRIPT_DU,
                            "reference_academic": REF_ACADEMIC_DU},
                           "University of Delhi")
    assert det.school == "Shri Ram College of Commerce"
    assert det.source_document == "transcript"
    assert det.corroborated is True
    assert det.confidence >= 80
    assert det.snippet and det.page == 1


def test_cv_alone_never_determines_school():
    """The CV names only the parent university — detection must not pick a school."""
    det = verify_schooling({"cv": CV_ONLY}, "University of Delhi")
    assert det.school is None


def test_abbreviation_matches():
    det = verify_schooling({"transcript": pages(
        "University of Delhi Marksheet College: SRCC")}, "DU")
    assert det.school == "Shri Ram College of Commerce"


def test_parent_auto_detected_when_not_declared():
    det = verify_schooling({"transcript": TRANSCRIPT_DU}, None)
    assert det.university == "University of Delhi"
    assert det.school == "Shri Ram College of Commerce"


def test_university_mismatch_is_flagged():
    det = verify_schooling({"transcript": TRANSCRIPT_DU}, "University of Mumbai")
    assert det.university_mismatch is True


def test_detect_university():
    assert detect_university(TRANSCRIPT_DU) == "University of Delhi"
    assert detect_university(pages("no university mentioned here at all")) is None


def test_unknown_university_yields_no_school_and_a_note():
    det = verify_schooling({"transcript": pages("Some College, Unknown University")},
                           "Unknown University")
    assert det.school is None
    assert det.notes


# ---------------- Document handling ----------------
def test_filename_grouping_and_classification():
    assert applicant_key_from_filename("APP-001_aarav_sharma_Transcript.pdf") == "APP-001"
    assert classify_document("x_Transcript.pdf", pages("")) == "transcript"
    assert classify_document("x_Reference_Academic.pdf", pages("")) == "reference_academic"
    assert classify_document("x_CV.pdf", pages("")) == "cv"
    assert classify_document("mystery.pdf",
                             pages("OFFICIAL ACADEMIC TRANSCRIPT")) == "transcript"


# ---------------- DB round-trip (in-memory) ----------------
@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE app_user (user_id INTEGER PRIMARY KEY, username TEXT, "
              "display_name TEXT, role TEXT, password_hash TEXT, is_active INTEGER)")
    c.execute("CREATE TABLE audit_log (log_id INTEGER PRIMARY KEY, user_id INTEGER, "
              "action TEXT, entity_type TEXT, entity_id TEXT, detail_json TEXT, "
              "created_at TEXT)")
    db._SV_DDL_DONE = False           # force DDL on this fresh connection
    db.ensure_school_schema(c)
    yield c
    db._SV_DDL_DONE = False
    c.close()


def test_verification_roundtrip_confirm_vs_corrected(conn):
    ver_id = db.add_school_verification(conn, {
        "applicant_id": "APP-999", "declared_university": "University of Delhi",
        "detected_university": "University of Delhi",
        "detected_school": "Hindu College", "confidence": 97.0,
        "source_document": "transcript", "source_page": 1,
        "evidence_snippet": "…Hindu College…", "corroborated": 1})
    row = db.latest_school_verification(conn, "APP-999")
    assert row["status"] == "pending"

    # reviewer agrees with the detection -> confirmed
    status = confirm_school(conn, ver_id, "Hindu College", "Hindu College", user_id=1)
    assert status == "confirmed"

    # a second run + an override -> corrected (append-only: both rows survive)
    ver2 = db.add_school_verification(conn, {"applicant_id": "APP-999",
                                             "detected_school": "Hindu College"})
    status2 = confirm_school(conn, ver2, "Hindu College", "Miranda House", user_id=1)
    assert status2 == "corrected"
    assert len(db.list_school_verifications(conn)) == 2
