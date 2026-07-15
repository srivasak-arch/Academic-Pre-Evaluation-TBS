"""Service layer for school verification.

Orchestrates: uploaded PDFs -> group by applicant -> classify document types ->
extract text -> detect school -> persist a pending verification row.
The UI never touches extraction, detection, or SQL directly.
"""
from __future__ import annotations
import re

from . import db
from .school_extract import extract_pages
from .school_detect import verify_schooling, SchoolDetection

# Filename conventions like APP-001_aarav_sharma_Transcript.pdf; content-based
# fallback below for files that don't follow them.
_FILENAME_HINTS = [
    (re.compile(r"transcript", re.I),                    "transcript"),
    (re.compile(r"reference[_\s-]*academic|academic[_\s-]*reference", re.I),
                                                          "reference_academic"),
    (re.compile(r"reference[_\s-]*professional|professional[_\s-]*reference", re.I),
                                                          "reference_professional"),
    (re.compile(r"(?:^|[\W_])cv(?:[\W_]|$)|resume|curriculum", re.I), "cv"),
]
_CONTENT_HINTS = [
    ("official academic transcript", "transcript"),
    ("statement of grades",          "transcript"),
    ("consolidated marksheet",       "transcript"),
    ("statement of marks",           "transcript"),
    ("letter of recommendation",     "reference_academic"),
    ("curriculum vitae",             "cv"),
]


def classify_document(filename: str, pages: list[dict]) -> str:
    for rx, doc_type in _FILENAME_HINTS:
        if rx.search(filename):
            return doc_type
    text = " ".join(p["text"] for p in pages[:1]).lower()
    for needle, doc_type in _CONTENT_HINTS:
        if needle in text:
            return doc_type
    return "other"


def applicant_key_from_filename(filename: str) -> str:
    """'APP-001_aarav_sharma_Transcript.pdf' -> 'APP-001'. Falls back to the stem."""
    m = re.match(r"([A-Za-z]+-\d+)", filename)
    return m.group(1) if m else filename.rsplit(".", 1)[0]


def group_uploads(files) -> dict[str, dict[str, list[dict]]]:
    """[(filename, bytes)] -> {applicant_key: {doc_type: pages}}.
    If two files of the same type collide for one applicant, the first wins."""
    grouped: dict[str, dict[str, list[dict]]] = {}
    for filename, data in files:
        pages = extract_pages(data)
        key = applicant_key_from_filename(filename)
        doc_type = classify_document(filename, pages)
        grouped.setdefault(key, {}).setdefault(doc_type, pages)
    return grouped


def run_verification(conn, applicant_id: str, docs: dict[str, list[dict]],
                     declared_university: str | None, user_id=None) -> tuple[int, SchoolDetection]:
    """Detect + persist one pending verification row. Returns (row id, detection)."""
    import json as _json
    from .doc_prefill import extract_prefill
    det = verify_schooling(docs, declared_university)
    prefill = extract_prefill(docs.get("transcript", [])) if docs.get("transcript") else {}
    ver_id = db.add_school_verification(conn, {
        "applicant_id": applicant_id,
        "declared_university": det.declared_university or declared_university,
        "detected_university": det.university,
        "detected_school": det.school,
        "confidence": det.confidence,
        "source_document": det.source_document,
        "source_page": det.page,
        "evidence_snippet": det.snippet,
        "corroborated": det.corroborated,
        "university_mismatch": det.university_mismatch,
        "notes": " | ".join(det.notes) if det.notes else None,
        "prefill_json": _json.dumps(prefill) if prefill else None,
    })
    db.audit(conn, user_id, "school_detection_run", entity_type="applicant",
             entity_id=applicant_id,
             detail={"detected_school": det.school, "confidence": det.confidence,
                     "source": det.source_document})
    return ver_id, det


def confirm_school(conn, verification_id: int, detected_school: str | None,
                   chosen_school: str, user_id) -> str:
    status = "confirmed" if chosen_school == detected_school else "corrected"
    db.resolve_school_verification(conn, verification_id, chosen_school, user_id, status)
    db.audit(conn, user_id, f"school_{status}", entity_type="school_verification",
             entity_id=str(verification_id), detail={"school": chosen_school})
    return status


def attach_to_applicant(conn, verification_id: int, applicant_id: str, user_id) -> None:
    """A: link a document-derived verification to an existing applicant record."""
    db.link_school_verification(conn, verification_id, applicant_id)
    db.audit(conn, user_id, "school_verification_linked",
             entity_type="school_verification", entity_id=str(verification_id),
             detail={"linked_applicant_id": applicant_id})
