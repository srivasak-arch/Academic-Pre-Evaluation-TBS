"""
Data-preparation and aggregation layer for the Data Insights (BI) page.

Keeps computation out of the view: the page asks for tidy DataFrames and a few
derived helpers, and renders them. Everything here operates on a *filtered*
application set, so all downstream charts respond to the page filters.

No composite scoring or ranking is introduced — only cohort-level distributions
of independent, already-computed indicators (consistent with the app's design).
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

from . import db
from .rules import irish_band, CURRENT_YEAR, KEY_FIELDS

# RAG rendering (aligns with the app palette)
RAG_ORDER = ["green", "amber", "red", "pending", "info", "strong", "partial", "sparse"]
RAG_COLORS = {
    "green": "#3F8F63", "amber": "#D38B2C", "red": "#C44B5B", "pending": "#9AA0A6",
    "info": "#7E94AB", "strong": "#6E89A6", "partial": "#9AA0A6", "sparse": "#B0A48F",
}
GRADE_BANDS = ["First (1.1)", "Upper Second (2.1)", "Lower Second (2.2)",
               "Third", "Pass / below", "Not on file"]


def _band_short(pct):
    b = irish_band(pct)
    if b is None:
        return "Not on file"
    return {"First Class Honours (1.1)": "First (1.1)",
            "Upper Second (2.1)": "Upper Second (2.1)",
            "Lower Second (2.2)": "Lower Second (2.2)",
            "Third Class Honours": "Third",
            "Pass / below honours": "Pass / below"}[b]


@dataclass
class InsightData:
    df: pd.DataFrame           # one row per application (enriched + derived)
    eval_wide: pd.DataFrame    # index application_id, columns = indicator colours
    df_dec: pd.DataFrame       # recorded reviewer decisions for the filtered set
    n: int


def load_insight_data(conn, **filters) -> InsightData:
    """Fetch the filtered application set, its cached indicator outcomes, and the
    decisions recorded against it. Returns tidy DataFrames with derived columns."""
    rows = db.list_applications(conn, **filters)
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return InsightData(df, pd.DataFrame(), pd.DataFrame(), 0)

    # derived columns
    df["grade_band"] = df["grade_irish_eq"].apply(_band_short)
    df["years_since_grad"] = CURRENT_YEAR - df["graduation_year"]
    df["quant_label"] = df["subject_quant_level"].map(
        {0: "Low quant", 1: "Moderate quant", 2: "High quant"})
    df["readiness"] = df.apply(
        lambda r: "Awaiting evidence"
        if pd.isna(r["grade_irish_eq"]) or r["english_level"] in (None, "")
        else "Ready to review", axis=1)
    df["n_missing"] = df.apply(
        lambda r: sum(1 for f in KEY_FIELDS if _missing(r, f)), axis=1)

    app_ids = df["application_id"].tolist()
    ev = pd.DataFrame([dict(r) for r in db.evaluations_for_applications(conn, app_ids)])
    if not ev.empty:
        eval_wide = ev.pivot_table(index="application_id", columns="indicator_key",
                                   values="colour", aggfunc="last")
    else:
        eval_wide = pd.DataFrame()

    decided = db.decided_application_ids(conn)
    dec_rows = [dict(d) for d in db.list_decisions(conn) if d["application_id"] in set(app_ids)]
    df_dec = pd.DataFrame(dec_rows)
    df["is_decided"] = df["application_id"].isin(decided)

    return InsightData(df, eval_wide, df_dec, len(df))


def _missing(row, field):
    key = {"grade_irish_eq": "grade_irish_eq", "english_level": "english_level",
           "institution_tier": "institution_tier"}[field]
    v = row.get(key)
    return v is None or (isinstance(v, float) and pd.isna(v)) or v == ""


# ---------------------------------------------------------------------------
# Aggregation helpers (all return tidy DataFrames ready for Altair)
# ---------------------------------------------------------------------------
def pct(part, whole):
    return 0.0 if not whole else round(100 * part / whole, 1)


def share_table(df, col, dropna=False, order=None):
    """Counts + percentages for a categorical column, sorted by count desc."""
    s = df[col]
    if not dropna:
        s = s.fillna("Not recorded")
    vc = s.value_counts(dropna=dropna)
    out = vc.rename_axis(col).reset_index(name="n")
    out["pct"] = out["n"].apply(lambda x: pct(x, len(df)))
    if order:
        out[col] = pd.Categorical(out[col], categories=order, ordered=True)
        out = out.sort_values(col)
    return out


def rag_distribution(eval_wide, indicator):
    """Distribution of RAG (or neutral/confidence) values for one indicator."""
    if eval_wide.empty or indicator not in eval_wide.columns:
        return pd.DataFrame(columns=["colour", "n", "pct"])
    vc = eval_wide[indicator].value_counts()
    out = vc.rename_axis("colour").reset_index(name="n")
    total = out["n"].sum()
    out["pct"] = out["n"].apply(lambda x: pct(x, total))
    out["colour"] = pd.Categorical(out["colour"], categories=RAG_ORDER, ordered=True)
    return out.sort_values("colour")


def crosstab_rag(df, eval_wide, group_col, indicator, min_n=12):
    """RAG share of `indicator` within each group of `group_col`, suppressing
    groups smaller than min_n (privacy + noise). Returns (long_df, suppressed)."""
    if eval_wide.empty or indicator not in eval_wide.columns:
        return pd.DataFrame(), []
    merged = df[["application_id", group_col]].merge(
        eval_wide[[indicator]], left_on="application_id", right_index=True)
    merged[group_col] = merged[group_col].fillna("Not recorded")
    sizes = merged.groupby(group_col).size()
    keep = sizes[sizes >= min_n].index.tolist()
    suppressed = sizes[sizes < min_n].index.tolist()
    sub = merged[merged[group_col].isin(keep)]
    if sub.empty:
        return pd.DataFrame(), suppressed
    g = (sub.groupby([group_col, indicator]).size().reset_index(name="n"))
    totals = g.groupby(group_col)["n"].transform("sum")
    g["pct"] = (100 * g["n"] / totals).round(1)
    g = g.rename(columns={indicator: "colour"})
    g["colour"] = pd.Categorical(g["colour"], categories=RAG_ORDER, ordered=True)
    return g, suppressed


def green_share(eval_wide, indicator):
    d = rag_distribution(eval_wide, indicator)
    if d.empty:
        return None
    total = d["n"].sum()
    g = d.loc[d["colour"] == "green", "n"].sum()
    return pct(g, total)


def colour_share(eval_wide, indicator, colour):
    d = rag_distribution(eval_wide, indicator)
    if d.empty:
        return None
    total = d["n"].sum()
    c = d.loc[d["colour"] == colour, "n"].sum()
    return pct(c, total)
