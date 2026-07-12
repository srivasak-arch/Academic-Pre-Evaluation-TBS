"""Detect which school/college an applicant studied at, from their documents.

Design rules (mirroring how the admissions team actually works):
  - The TRANSCRIPT is the authoritative source. The ACADEMIC REFERENCE is a
    secondary signal used only to corroborate (or as a fallback if the
    transcript fails to parse). The CV and professional reference are NEVER
    used to determine the school -- the CV is exactly the document that omits it.
  - Detection only selects from the known school list for the (declared or
    detected) parent university, so it cannot invent a school.
  - Every result carries evidence: source document, page, snippet, confidence,
    plus the runner-up candidates so a reviewer correcting a miss starts warm.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .school_reference import (UNIVERSITY_ALIASES, resolve_university, schools_for)

SNIPPET_PAD = 60
SCHOOL_THRESHOLD = 80.0      # min fuzzy score to accept a school match
UNIVERSITY_THRESHOLD = 85.0  # min fuzzy score to accept a university detection

# Which uploaded documents may determine the school, in priority order.
AUTHORITATIVE_DOCS = ("transcript", "reference_academic")


@dataclass
class SchoolDetection:
    university: str | None = None          # canonical parent actually used
    declared_university: str | None = None # what the applicant wrote (canonicalised)
    university_mismatch: bool = False      # declared vs detected disagree
    school: str | None = None
    confidence: float = 0.0
    source_document: str | None = None     # 'transcript' / 'reference_academic'
    page: int | None = None
    snippet: str | None = None
    corroborated: bool = False             # second document agrees
    candidates: list = field(default_factory=list)  # [(school, score), ...] top 5
    notes: list = field(default_factory=list)       # human-readable caveats


# --------------------------------------------------------------- text scanning
# Generic institution words that must never carry a match by themselves:
# "Anna University" must not match "Unknown University" just because both say
# "University", and "X College" must not match any other "... College".
_GENERIC_TOKENS = {"university", "college", "school", "institute", "institution",
                   "of", "the", "and", "for", "de", "la"}
_TOKEN_OK = 90.0    # per-token similarity needed inside the matched span (OCR slack)


def _distinctive_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z]+", name.lower())
            if len(t) >= 3 and t not in _GENERIC_TOKENS]


def _span_has_tokens(span: str, tokens: list[str]) -> bool:
    """Every distinctive token must appear (fuzzily) inside the matched span."""
    return all(fuzz.partial_ratio(t, span.lower()) >= _TOKEN_OK for t in tokens)


def _best_variant_match(variants: list[str], text: str):
    """Best validated (score, start, end) of any variant inside text.

    Long names: fuzzy alignment, then distinctive-token validation of the span.
    Short names / acronyms (<= 5 chars, e.g. SRCC, LSE, UCC): exact
    word-boundary match only -- fuzz on 3-4 letters is pure noise."""
    hay = text.lower()
    best = None
    for v in variants:
        vl = v.lower()
        if len(vl) <= 5:
            m = re.search(r"(?<![A-Za-z])" + re.escape(vl) + r"(?![A-Za-z])", hay)
            if m and (best is None or 100.0 > best[0]):
                best = (100.0, m.start(), m.end())
            continue
        aln = fuzz.partial_ratio_alignment(vl, hay)
        if not aln or (best and aln.score <= best[0]):
            continue
        # validate: the matched region must actually contain the words that make
        # this name THIS name (pad the span a little for alignment slop)
        s, e = max(0, aln.dest_start - 5), min(len(text), aln.dest_end + 5)
        if _span_has_tokens(text[s:e], _distinctive_tokens(vl)):
            best = (aln.score, aln.dest_start, aln.dest_end)
    return best


def _snippet(text: str, start: int, end: int) -> str:
    s, e = max(0, start - SNIPPET_PAD), min(len(text), end + SNIPPET_PAD)
    return (("…" if s else "") + " ".join(text[s:e].split())
            + ("…" if e < len(text) else ""))


def detect_university(pages: list[dict]) -> str | None:
    """Find the parent university named in a document (alias-aware)."""
    best_score, best_uni = -1.0, None
    for p in pages:
        if not p["text"]:
            continue
        for alias, canonical in UNIVERSITY_ALIASES.items():
            if len(alias) < 6:      # skip 2-4 letter acronyms: too fuzzy-noisy here
                continue
            m = _best_variant_match([alias], p["text"])
            if m and m[0] > best_score:
                best_score, best_uni = m[0], canonical
    return best_uni if best_score >= UNIVERSITY_THRESHOLD else None


def detect_school_in_doc(pages: list[dict], university: str):
    """Best school match for one document. Returns (school, score, page, snippet, cands)."""
    catalogue = schools_for(university)
    best = (None, -1.0, None, None)
    per_school: dict[str, float] = {}
    for p in pages:
        if not p["text"]:
            continue
        for school, variants in catalogue.items():
            m = _best_variant_match(variants, p["text"])
            if not m:
                continue
            score, s, e = m
            if score > per_school.get(school, -1.0):
                per_school[school] = score
            if score > best[1]:
                best = (school, score, p["page"], _snippet(p["text"], s, e))
    cands = sorted(per_school.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return best[0], best[1], best[2], best[3], cands


# ------------------------------------------------------------------- pipeline
def verify_schooling(docs: dict[str, list[dict]],
                     declared_university: str | None = None) -> SchoolDetection:
    """
    docs : {doc_type: pages} with doc_type in
           {'transcript','reference_academic','reference_professional','cv'}.
    declared_university : what the applicant wrote on the application/CV (optional --
           if absent, the parent is detected from the transcript itself).
    """
    det = SchoolDetection()
    det.declared_university = resolve_university(declared_university)
    if declared_university and not det.declared_university:
        det.notes.append(f"Declared university “{declared_university}” is not in the "
                         "reference catalogue — add it under Administration.")

    # 1. Establish the parent university: declaration first, else detect from transcript.
    detected_uni = detect_university(docs.get("transcript", []))
    det.university = det.declared_university or detected_uni
    if det.declared_university and detected_uni and detected_uni != det.declared_university:
        det.university_mismatch = True
        det.notes.append(f"Transcript names “{detected_uni}” but the application "
                         f"declares “{det.declared_university}” — check for a typo "
                         "or a wrong document.")
    if not det.university:
        det.notes.append("Could not establish the parent university from the "
                         "declaration or the transcript.")
        return det

    # 2. Detect the school in authoritative documents, in priority order.
    results = {}
    for doc_type in AUTHORITATIVE_DOCS:
        if doc_type in docs:
            results[doc_type] = detect_school_in_doc(docs[doc_type], det.university)

    primary = None
    for doc_type in AUTHORITATIVE_DOCS:            # transcript wins if it matched
        r = results.get(doc_type)
        if r and r[0] is not None and r[1] >= SCHOOL_THRESHOLD:
            primary = (doc_type, r)
            break

    if primary is None:
        # No confident hit anywhere: hand the reviewer the warmest candidates.
        for doc_type in AUTHORITATIVE_DOCS:
            r = results.get(doc_type)
            if r and r[4]:
                det.candidates = r[4]
                break
        det.notes.append("No school matched confidently — manual check of the "
                         "transcript needed.")
        return det

    doc_type, (school, score, page, snippet, cands) = primary
    det.school, det.confidence = school, round(score, 1)
    det.source_document, det.page, det.snippet = doc_type, page, snippet
    det.candidates = cands
    if doc_type != "transcript":
        det.notes.append("Detected from the academic reference (transcript did not "
                         "yield a match) — treat as secondary evidence.")

    # 3. Corroboration: does the other authoritative document agree?
    other = "reference_academic" if doc_type == "transcript" else "transcript"
    r2 = results.get(other)
    if r2 and r2[0] == school and r2[1] >= SCHOOL_THRESHOLD:
        det.corroborated = True

    # OCR caveat: flag if any page of the source document failed to yield text.
    src_pages = docs.get(doc_type, [])
    if any(not p["text"] for p in src_pages):
        det.notes.append("Some pages of the source document produced no text "
                         "(scan without OCR available) — evidence may be partial.")
    return det
