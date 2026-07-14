"""Tests for the rules engine and the design invariants the dissertation relies on."""
import inspect
import pytest
from src import rules
from src.rules import evaluate_application, IndicatorResult, PROGRAMME_PROFILES


def base_app(**over):
    app = dict(
        grade_irish_eq=68.0, english_level="High", subject_name="Data Science",
        subject_quant_level=2, institution_tier="Tier1",
        tier_label="Research-intensive flagship university",
        graduation_year=2024, work_experience="1-2 years", years_experience=2,
    )
    app.update(over)
    return app


# ---------------- Correctness ----------------
def test_returns_ten_independent_results():
    res = evaluate_application(base_app(), "BA")
    assert len(res) == 10
    assert all(isinstance(r, IndicatorResult) for r in res)
    keys = [r.key for r in res]
    assert len(set(keys)) == 10  # all distinct


def test_academic_performance_bands():
    assert evaluate_application(base_app(grade_irish_eq=72), "BA")[0].value == "green"
    assert evaluate_application(base_app(grade_irish_eq=58), "BA")[0].value == "amber"
    assert evaluate_application(base_app(grade_irish_eq=48), "BA")[0].value == "red"


def test_missing_grade_is_pending_not_red():
    r = evaluate_application(base_app(grade_irish_eq=None), "BA")[0]
    assert r.value == "pending" and r.confidence == "low"


def test_english_pending_not_red():
    eng = [r for r in evaluate_application(base_app(english_level=None), "BA")
           if r.key == "english_requirement"][0]
    assert eng.value == "pending" and eng.confidence == "low"


def test_institution_context_is_neutral_never_rag():
    for pc in ("BA", "IM"):
        ic = [r for r in evaluate_application(base_app(), pc) if r.key == "institution_context"][0]
        assert ic.scale == "neutral" and ic.value == "info"
        assert ic.value not in ("green", "amber", "red")


def test_work_experience_neutral_for_BA_rag_for_IM():
    we_ba = [r for r in evaluate_application(base_app(work_experience="No experience"), "BA")
             if r.key == "work_experience"][0]
    assert we_ba.scale == "neutral"           # BA: supplementary -> never red
    we_im = [r for r in evaluate_application(base_app(work_experience="No experience"), "IM")
             if r.key == "work_experience"][0]
    assert we_im.scale == "rag" and we_im.value == "red"


def test_graduation_recency_bands():
    assert [r for r in evaluate_application(base_app(graduation_year=2024), "BA")
            if r.key == "graduation_recency"][0].value == "green"
    assert [r for r in evaluate_application(base_app(graduation_year=2020), "BA")
            if r.key == "graduation_recency"][0].value == "amber"
    assert [r for r in evaluate_application(base_app(graduation_year=2015), "BA")
            if r.key == "graduation_recency"][0].value == "red"


def test_document_completeness_counts_missing():
    full = [r for r in evaluate_application(base_app(), "BA") if r.key == "document_completeness"][0]
    assert full.value == "green"
    two_missing = [r for r in evaluate_application(
        base_app(grade_irish_eq=None, english_level=None), "BA")
        if r.key == "document_completeness"][0]
    assert two_missing.value == "red"


def test_every_result_has_reasoning_and_inputs():
    for pc in ("BA", "IM"):
        for r in evaluate_application(base_app(), pc):
            assert r.reasoning and len(r.reasoning) > 10
            assert isinstance(r.inputs, dict)


# ---------------- Invariants (the methodological guarantees) ----------------
def test_no_aggregation_function_exists():
    """No function in the rules module should combine indicator colours into a
    score, total, rank, or overall verdict."""
    banned = ("composite", "overall_score", "total_score", "rank", "aggregate_score",
              "fit_score", "final_score")
    names = [n for n, _ in inspect.getmembers(rules, inspect.isfunction)]
    for n in names:
        assert not any(b in n.lower() for b in banned), f"banned aggregator: {n}"


def test_evidence_confidence_ignores_colours():
    """The meta indicator must depend only on evidence quality, not on RAG colours.
    Two applicants with identical completeness/confidence but opposite colours must
    receive the same evidence_confidence."""
    strong = base_app(grade_irish_eq=80, english_level="High")      # all green-ish
    weak = base_app(grade_irish_eq=46, english_level="Low",          # all red-ish
                    subject_name="Marketing", subject_quant_level=0)
    ec_strong = [r for r in evaluate_application(strong, "BA") if r.key == "evidence_confidence"][0]
    ec_weak = [r for r in evaluate_application(weak, "BA") if r.key == "evidence_confidence"][0]
    # both have complete evidence and no low-confidence inputs -> identical meta result
    assert ec_strong.value == ec_weak.value == "strong"


def test_result_carries_no_numeric_total():
    res = evaluate_application(base_app(), "BA")
    # results are a flat list; there is no summary element appended
    assert all(r.key != "total" and r.key != "score" for r in res)
    assert not hasattr(res, "score")


def test_thresholds_present_for_both_programmes():
    for pc in ("BA", "IM"):
        prof = PROGRAMME_PROFILES[pc]
        assert prof["academic_performance"]["green_min"] == 65


# ---------------- Design iteration: evaluation-driven context demotion ----------------
def test_contextual_facets_are_separated_from_scored_chips():
    """Stage 4/5 evaluation found institutional tier carries no reliable signal
    (single-facet AUC 0.47). Contextual facets must render in a separate strip,
    never among the scored advisory chips."""
    from src.ui import split_results
    results = evaluate_application(base_app(), "BA")
    scored, contextual = split_results(results)
    assert "institution_context" in [r.key for r in contextual]
    assert "institution_context" not in [r.key for r in scored]
    assert all(r.scale != "neutral" for r in scored)
    assert len(scored) + len(contextual) == 10   # nothing dropped — shown, not scored


def test_work_experience_contextual_only_where_supplementary():
    """Work experience is contextual for BA (supplementary) but scored for IM."""
    from src.ui import split_results
    _, ctx_ba = split_results(evaluate_application(base_app(), "BA"))
    scored_im, _ = split_results(evaluate_application(base_app(), "IM"))
    assert "work_experience" in [r.key for r in ctx_ba]
    assert "work_experience" in [r.key for r in scored_im]
