"""
Rules engine — the explainable, deterministic heart of the dashboard.

Design invariants (asserted by tests in tests/):
  * Each indicator is computed INDEPENDENTLY.
  * NOTHING combines indicator colours into a score, count, or rank.
  * `evidence_confidence` aggregates ONLY evidence quality (confidence +
    completeness), never applicant-quality colours.
  * Every result carries a plain-English reason and an input snapshot, so it
    is reproducible and explainable by construction (no black box).

Programme-parameterised: thresholds and subject mappings differ for
MSc Business Analytics (BA) and MSc International Management (IM).
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dataclass
class IndicatorResult:
    key: str
    name: str
    scale: str                 # 'rag' | 'neutral' | 'confidence'
    value: str                 # rag: green/amber/red/pending | neutral: info | confidence: strong/partial/sparse
    confidence: str            # 'high' | 'moderate' | 'low'
    reasoning: str             # plain-English, cites inputs + rule
    inputs: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Programme profiles  (the versioned config; seeded into threshold_config too)
# ---------------------------------------------------------------------------
# Subject quant levels mirror the synthetic corpus.
ALL_SUBJECTS = {
    "Mathematics & Statistics": 2, "Computer Science": 2, "Data Science": 2,
    "Engineering": 2, "Physics": 2, "Economics": 2, "Actuarial Science": 2,
    "Finance": 1, "Accounting": 1, "Information Systems": 1,
    "Business Administration": 1, "Management": 1, "Commerce": 1,
    "Marketing": 0, "Psychology": 0, "International Relations": 0,
}

PROGRAMME_PROFILES = {
    "BA": {
        "academic_performance": {"green_min": 65, "amber_min": 55},
        "graduation_recency":   {"green_max": 3, "amber_max": 8},
        "document_completeness": {"amber_missing": 1, "red_missing": 2},
        # prerequisites gate by subject quant level
        "prereq_green_quant": [2], "prereq_amber_quant": [1], "prereq_red_quant": [0],
        "quant_green_grade_min": 60,   # quant_level 2 AND grade>=60 -> green
        "work_experience_mode": "neutral",   # BA: experience supplementary -> neutral chip
        # subject alignment sets (fit/breadth, distinct from the prereq gate)
        "align_strong": {"Mathematics & Statistics", "Computer Science", "Data Science",
                          "Engineering", "Physics", "Economics", "Actuarial Science"},
        "align_adjacent": {"Finance", "Accounting", "Information Systems",
                           "Business Administration", "Management"},
        # everything else -> distant (red)
    },
    "IM": {
        "academic_performance": {"green_min": 65, "amber_min": 55},
        "graduation_recency":   {"green_max": 3, "amber_max": 8},
        "document_completeness": {"amber_missing": 1, "red_missing": 2},
        "prereq_green_subjects": {"Business Administration", "Management", "Commerce",
                                  "Economics", "Finance", "Accounting", "Marketing"},
        "prereq_amber_subjects": {"International Relations", "Psychology", "Information Systems"},
        # else -> red (no business foundation)
        "quant_green_quant": [1, 2],   # IM: quant_level>=1 -> green; ==0 -> amber (no red)
        "work_experience_mode": "rag",      # IM: experience material -> rag
        "align_strong": {"Business Administration", "Management", "Commerce",
                         "International Relations", "Economics", "Marketing",
                         "Finance", "Accounting"},
        "align_adjacent": {"Psychology", "Information Systems", "Data Science"},
        # everything else -> distant (red)
    },
}

NAMES = {
    "academic_performance": "Academic Performance",
    "programme_prerequisites": "Programme Prerequisites",
    "quantitative_readiness": "Quantitative Readiness",
    "english_requirement": "English Requirement",
    "institution_context": "Institution Context",
    "subject_alignment": "Subject Alignment",
    "work_experience": "Work Experience",
    "graduation_recency": "Graduation Recency",
    "document_completeness": "Document Completeness",
    "evidence_confidence": "Confidence in Available Evidence",
}

CURRENT_YEAR = 2026
KEY_FIELDS = ("grade_irish_eq", "english_level", "institution_tier")  # completeness basis


def irish_band(pct: Optional[float]) -> Optional[str]:
    if pct is None:
        return None
    if pct >= 70: return "First Class Honours (1.1)"
    if pct >= 60: return "Upper Second (2.1)"
    if pct >= 50: return "Lower Second (2.2)"
    if pct >= 45: return "Third Class Honours"
    return "Pass / below honours"


# ---------------------------------------------------------------------------
# Individual indicators.  Each takes the enriched application row + profile.
# `app` keys expected: grade_irish_eq, english_level, subject_name,
# subject_quant_level, institution_tier, tier_label, graduation_year,
# work_experience, years_experience.
# ---------------------------------------------------------------------------
def _academic_performance(app, prof) -> IndicatorResult:
    g = app.get("grade_irish_eq")
    t = prof["academic_performance"]
    if g is None:
        return IndicatorResult("academic_performance", NAMES["academic_performance"], "rag",
            "pending", "low",
            "No grade is on file yet, so academic performance cannot be assessed. "
            "Shown as pending rather than as a pass or fail.",
            {"grade_irish_eq": None})
    band = irish_band(g)
    if g >= t["green_min"]:
        v = "green"
    elif g >= t["amber_min"]:
        v = "amber"
    else:
        v = "red"
    return IndicatorResult("academic_performance", NAMES["academic_performance"], "rag", v, "high",
        f"Irish-equivalent grade {g:.1f}% places this applicant in the {band} band. "
        f"This programme treats {t['green_min']}% and above as a strong result and "
        f"below {t['amber_min']}% as a concern.",
        {"grade_irish_eq": g, "band": band, "green_min": t["green_min"], "amber_min": t["amber_min"]})


def _programme_prerequisites(app, prof, programme_code) -> IndicatorResult:
    subj = app.get("subject_name")
    q = app.get("subject_quant_level")
    if programme_code == "BA":
        if q in prof["prereq_green_quant"]:
            v, msg = "green", "covers the quantitative foundation this programme requires"
        elif q in prof["prereq_amber_quant"]:
            v, msg = "amber", "provides a partial quantitative foundation; check specific modules"
        else:
            v, msg = "red", "does not evidence the required quantitative foundation"
    else:  # IM
        if subj in prof["prereq_green_subjects"]:
            v, msg = "green", "provides the business/management foundation this programme expects"
        elif subj in prof["prereq_amber_subjects"]:
            v, msg = "amber", "is adjacent to the expected business foundation; check coverage"
        else:
            v, msg = "red", "does not evidence the expected business/management foundation"
    return IndicatorResult("programme_prerequisites", NAMES["programme_prerequisites"], "rag",
        v, "moderate",
        f"Subject of study ({subj}) {msg}. This is assessed at subject-area level only "
        f"(course-level data is not available), so confidence is moderate.",
        {"subject_name": subj, "subject_quant_level": q})


def _quantitative_readiness(app, prof, programme_code) -> IndicatorResult:
    q = app.get("subject_quant_level")
    g = app.get("grade_irish_eq")
    desc = {2: "a highly quantitative subject", 1: "a moderately quantitative subject",
            0: "a low-quantitative subject"}[q]
    if programme_code == "BA":
        if g is None:
            v, conf = ("amber" if q >= 1 else "red"), "low"
            reason = (f"The field of study is {desc}, but no grade is on file, so quantitative "
                      f"readiness rests on partial evidence.")
        elif q == 2 and g >= prof["quant_green_grade_min"]:
            v, conf = "green", "high"
            reason = f"{desc.capitalize()} with grade {g:.1f}% indicates strong quantitative readiness."
        elif q == 2 or q == 1:
            v, conf = "amber", "high"
            reason = f"{desc.capitalize()} with grade {g:.1f}% indicates moderate quantitative readiness."
        else:
            v, conf = "red", "high"
            reason = f"{desc.capitalize()} provides limited quantitative preparation for this programme."
    else:  # IM — lower quantitative bar, no red
        if q in prof["quant_green_quant"]:
            v, conf = "green", "high"
            reason = f"{desc.capitalize()} meets the quantitative needs of this programme."
        else:
            v, conf = "amber", "high"
            reason = (f"{desc.capitalize()}; this programme is less quantitative, so this is advisory "
                      f"rather than disqualifying.")
        if g is None:
            conf = "low"
    return IndicatorResult("quantitative_readiness", NAMES["quantitative_readiness"], "rag",
        v, conf, reason, {"subject_quant_level": q, "grade_irish_eq": g})


def _english_requirement(app, prof) -> IndicatorResult:
    e = app.get("english_level")
    if e is None:
        return IndicatorResult("english_requirement", NAMES["english_requirement"], "rag",
            "pending", "low",
            "No English evidence is on file yet. Shown as pending rather than as a pass or fail; "
            "we recommend requesting evidence before a final decision.",
            {"english_level": None})
    v = {"High": "green", "Moderate": "amber", "Low": "red"}[e]
    msg = {"High": "meets the postgraduate English requirement",
           "Moderate": "is near the requirement; may warrant a closer look",
           "Low": "is below the postgraduate English requirement"}[e]
    return IndicatorResult("english_requirement", NAMES["english_requirement"], "rag", v, "high",
        f"Recorded English level is {e}, which {msg}.", {"english_level": e})


def _institution_context(app, prof) -> IndicatorResult:
    # NEUTRAL by design — institution prestige is context, never a pass/fail (bias-mitigation).
    tier_label = app.get("tier_label") or "Institution type not recorded"
    return IndicatorResult("institution_context", NAMES["institution_context"], "neutral",
        "info", "high" if app.get("tier_label") else "low",
        f"Awarded by: {tier_label}. Institution is shown for context only and is deliberately "
        f"excluded from any pass/fail logic to avoid prestige and country-of-origin bias.",
        {"tier_label": app.get("tier_label")})


def _subject_alignment(app, prof) -> IndicatorResult:
    subj = app.get("subject_name")
    if subj in prof["align_strong"]:
        v, msg = "green", "aligns strongly with this programme's intellectual core"
    elif subj in prof["align_adjacent"]:
        v, msg = "amber", "is adjacent to this programme's core"
    else:
        v, msg = "red", "is a more distant field from this programme's core"
    return IndicatorResult("subject_alignment", NAMES["subject_alignment"], "rag", v, "high",
        f"The applicant's field ({subj}) {msg}. This describes fit and breadth, separately from "
        f"whether prerequisites are met.", {"subject_name": subj})


def _work_experience(app, prof, programme_code) -> IndicatorResult:
    we = app.get("work_experience")
    yrs = app.get("years_experience")
    if prof["work_experience_mode"] == "neutral":
        # BA: experience is supplementary -> neutral context chip, never red/amber.
        return IndicatorResult("work_experience", NAMES["work_experience"], "neutral", "info", "high",
            f"Work experience: {we}"
            + (f" ({yrs} yr logged)." if yrs else ".")
            + " For this programme, experience is supplementary, so it is shown as context only.",
            {"work_experience": we, "years_experience": yrs})
    # IM: experience is material -> rag.
    v = {"3+ years": "green", "1-2 years": "amber", "Internships": "amber",
         "No experience": "red"}.get(we, "amber")
    msg = {"green": "is a strong, relevant base of experience for this programme",
           "amber": "is a partial base of experience",
           "red": "shows no professional experience, which this programme weighs"}[v]
    return IndicatorResult("work_experience", NAMES["work_experience"], "rag", v, "high",
        f"Recorded experience ({we}) {msg}.", {"work_experience": we, "years_experience": yrs})


def _graduation_recency(app, prof) -> IndicatorResult:
    gy = app.get("graduation_year")
    t = prof["graduation_recency"]
    since = CURRENT_YEAR - gy
    if since <= t["green_max"]:
        v, msg = "green", "recent"
    elif since <= t["amber_max"]:
        v, msg = "amber", "moderately recent"
    else:
        v, msg = "red", "dated; knowledge currency may warrant a closer look"
    return IndicatorResult("graduation_recency", NAMES["graduation_recency"], "rag", v, "high",
        f"Graduated {gy} ({since} year{'s' if since != 1 else ''} ago) — {msg}.",
        {"graduation_year": gy, "years_since_graduation": since})


def _document_completeness(app, prof) -> IndicatorResult:
    missing = [f for f in KEY_FIELDS if app.get(f) in (None, "")]
    t = prof["document_completeness"]
    n = len(missing)
    if n == 0:
        v, msg = "green", "All key evidence fields are present."
    elif n >= t["red_missing"]:
        v, msg = "red", f"{n} key evidence fields are missing."
    else:
        v, msg = "amber", "One key evidence field is missing."
    pretty = {"grade_irish_eq": "grade", "english_level": "English evidence",
              "institution_tier": "institution detail"}
    miss_txt = ", ".join(pretty.get(m, m) for m in missing) if missing else "none"
    return IndicatorResult("document_completeness", NAMES["document_completeness"], "rag", v, "high",
        f"{msg} Missing: {miss_txt}. This indicator routes readiness; it is not a quality verdict.",
        {"missing_fields": missing, "n_missing": n})


def _evidence_confidence(app, prof, others) -> IndicatorResult:
    """META indicator — aggregates EVIDENCE QUALITY only (completeness + how many
    indicators rest on low confidence). It deliberately ignores RAG colours, so it
    is not a back-door composite of applicant quality."""
    n_missing = sum(1 for f in KEY_FIELDS if app.get(f) in (None, ""))
    n_low = sum(1 for r in others if r.confidence == "low")
    if n_missing == 0 and n_low == 0:
        v = "strong"
        reason = "All key evidence is present and every indicator rests on solid inputs."
    elif n_missing >= 2 or n_low >= 3:
        v = "sparse"
        reason = (f"{n_missing} key field(s) missing and {n_low} indicator(s) on weak evidence — "
                  f"treat the colours above cautiously.")
    else:
        v = "partial"
        reason = (f"{n_missing} key field(s) missing and {n_low} indicator(s) on partial evidence — "
                  f"some indicators are less certain than others.")
    return IndicatorResult("evidence_confidence", NAMES["evidence_confidence"], "confidence",
        v, "high", reason, {"n_missing": n_missing, "n_low_confidence": n_low})


# ---------------------------------------------------------------------------
# Orchestration — returns INDEPENDENT results in display order. No total.
# ---------------------------------------------------------------------------
def evaluate_application(app: dict, programme_code: str, profile: dict = None) -> list[IndicatorResult]:
    prof = profile if profile is not None else PROGRAMME_PROFILES[programme_code]
    results = [
        _academic_performance(app, prof),
        _programme_prerequisites(app, prof, programme_code),
        _quantitative_readiness(app, prof, programme_code),
        _english_requirement(app, prof),
        _institution_context(app, prof),
        _subject_alignment(app, prof),
        _work_experience(app, prof, programme_code),
        _graduation_recency(app, prof),
        _document_completeness(app, prof),
    ]
    results.append(_evidence_confidence(app, prof, results))
    return results
