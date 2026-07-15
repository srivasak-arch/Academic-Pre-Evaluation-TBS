"""Extract pre-fill suggestions for a NEW applicant record from their documents.

Design rule (mirrors the school-verification philosophy): every extracted value
is a SUGGESTION carrying its evidence, surfaced for human confirmation — never
silently written. Fields split into two classes:

  SAFE TO PRE-FILL (regular, validated formats on the synthetic transcripts):
    forename/surname, subject area (mapped to the catalogue), graduation year,
    institution (from the confirmed school verification).

  EVIDENCE-ONLY (shown to the reviewer, never auto-filled):
    the transcript's CGPA / classification — converting a 10-point CGPA to an
    Irish-equivalent percentage is a domain judgement, so the number is displayed
    as evidence and the reviewer enters the equivalent themselves;
    medium of instruction — a weak signal for English level, never a substitute
    for a certificate.
"""
from __future__ import annotations
import re

from rapidfuzz import fuzz

# transcript field patterns (single consistent synthetic format)
_RX = {
    "name":        re.compile(r"Student Name:\s*\n*\s*([A-Z][A-Za-z .'-]+)"),
    "programme":   re.compile(r"Programme:\s*\n*\s*([^\n]+)"),
    "period":      re.compile(r"Period of Study:\s*\n*\s*(\d{4})\s*[–-]\s*(\d{4})"),
    "cgpa":        re.compile(r"Official Grade\s*\n*\s*([\d.]+)\s*/\s*([\d.]+)", re.I),
    "result":      re.compile(r"Result Awarded\s*\n*\s*([^\n]+)"),
    "medium_en":   re.compile(r"Medium of Instruction:\s*English", re.I),
}

# programme text -> subject-area catalogue, via fuzzy best match
_SUBJECT_HINTS = {
    "economics": "Economics", "finance": "Finance", "commerce": "Commerce",
    "accounting": "Accounting", "business": "Business Administration",
    "management": "Management", "marketing": "Marketing",
    "computer": "Computer Science", "information": "Information Systems",
    "data": "Data Science", "math": "Mathematics & Statistics",
    "statistics": "Mathematics & Statistics", "physics": "Physics",
    "engineering": "Engineering", "psychology": "Psychology",
    "actuarial": "Actuarial Science", "international": "International Relations",
}


def extract_prefill(pages: list[dict], known_subjects: list[str] | None = None) -> dict:
    """Transcript pages -> {field: {'value': ..., 'evidence': str}} suggestions."""
    text = "\n".join(p["text"] for p in pages)
    out: dict[str, dict] = {}

    if m := _RX["name"].search(text):
        full = m.group(1).strip()
        parts = full.split()
        out["forename"] = {"value": " ".join(parts[:-1]) or full,
                           "evidence": f"Transcript: “Student Name: {full}”"}
        out["surname"] = {"value": parts[-1] if len(parts) > 1 else "",
                          "evidence": f"Transcript: “Student Name: {full}”"}

    if m := _RX["programme"].search(text):
        prog = m.group(1).strip()
        subject = _map_subject(prog, known_subjects)
        if subject:
            out["subject_name"] = {"value": subject,
                                   "evidence": f"Transcript: “Programme: {prog}”"}
        out["programme_text"] = {"value": prog, "evidence": "Transcript programme line"}

    if m := _RX["period"].search(text):
        out["graduation_year"] = {"value": int(m.group(2)),
                                  "evidence": f"Transcript: “Period of Study: "
                                              f"{m.group(1)}–{m.group(2)}”"}

    # EVIDENCE-ONLY items -------------------------------------------------
    if m := _RX["cgpa"].search(text):
        res = _RX["result"].search(text)
        label = f"{m.group(1)} / {m.group(2)}" + (f" ({res.group(1).strip()})" if res else "")
        out["grade_evidence"] = {
            "value": None,
            "evidence": f"Transcript shows Official Grade {label}. Enter the "
                        "Irish-equivalent percentage manually — scale conversion "
                        "is a reviewer judgement and is not automated."}
    if _RX["medium_en"].search(text):
        out["english_evidence"] = {
            "value": None,
            "evidence": "Transcript notes medium of instruction: English. This is "
                        "a weak signal only — confirm English level from a "
                        "certificate, not from this."}
    return out


def _map_subject(programme_text: str, known_subjects: list[str] | None) -> str | None:
    pl = programme_text.lower()
    for hint, subject in _SUBJECT_HINTS.items():
        if hint in pl:
            if known_subjects and subject not in known_subjects:
                continue
            return subject
    if known_subjects:  # fuzzy fallback against the catalogue
        best = max(known_subjects, key=lambda s: fuzz.partial_ratio(s.lower(), pl))
        if fuzz.partial_ratio(best.lower(), pl) >= 85:
            return best
    return None
