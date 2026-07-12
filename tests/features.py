"""Feature engineering for the research-track predictive model.

Builds a numeric matrix from applicant rows, with explicit provenance for every
feature and a hard exclusion list for protected / proxy attributes (used only
in the fairness audit, never as model inputs). All choices are fixed in
PREREGISTRATION_ML.md.
"""
from __future__ import annotations
import hashlib

import numpy as np
import pandas as pd

CURRENT_YEAR = 2026
TARGET_POSITIVE = "Strong Fit"

# Attributes that must never enter the model (asserted by tests).
PROTECTED_ATTRIBUTES = {"gender", "nationality_code", "nationality_name",
                        "country_code", "country_name", "surname", "forename",
                        "age"}

_ENGLISH_ORD = {"Low": 0, "Moderate": 1, "High": 2}
_TIER_ORD = {"Tier3": 0, "Tier2": 1, "Tier1": 2}

# feature -> provenance (where it comes from / how it is computed)
FEATURE_PROVENANCE = {
    "grade_irish_eq": "applicant.grade_irish_eq; NULL -> train-median impute",
    "grade_missing": "1 if applicant.grade_irish_eq IS NULL",
    "english_ord": "applicant.english_level mapped Low=0/Moderate=1/High=2; NULL -> train-median",
    "english_missing": "1 if applicant.english_level IS NULL",
    "subject_quant_level": "subject_area.quant_level (0-2)",
    "tier_ord": "institution.tier_code mapped Tier3=0/Tier2=1/Tier1=2",
    "years_since_grad": f"{CURRENT_YEAR} - applicant.graduation_year",
    "years_experience": "applicant.years_experience",
    "subject one-hot": "applicant.subject_name, one column per subject",
}


def load_dataset(conn) -> pd.DataFrame:
    """Applicant-level frame including audit-only columns (kept OUT of X)."""
    df = pd.read_sql_query(
        """SELECT a.applicant_id, a.baseline_label, a.grade_irish_eq,
                  a.english_level, a.graduation_year, a.years_experience,
                  a.gender, a.nationality_code,
                  sa.quant_level AS subject_quant_level, a.subject_name,
                  i.tier_code
           FROM applicant a
           JOIN subject_area sa ON a.subject_name = sa.subject_name
           JOIN institution i   ON a.institution_id = i.institution_id
           WHERE a.baseline_label IS NOT NULL""", conn)
    df["y"] = (df["baseline_label"] == TARGET_POSITIVE).astype(int)
    return df


def build_matrix(df: pd.DataFrame, medians: dict | None = None):
    """df -> (X, y, feature_names, medians). Pass train medians for the test set
    so imputation never leaks test information."""
    out = pd.DataFrame(index=df.index)
    grade = df["grade_irish_eq"]
    eng = df["english_level"].map(_ENGLISH_ORD)
    if medians is None:
        medians = {"grade": float(grade.median()), "english": float(eng.median())}
    out["grade_irish_eq"] = grade.fillna(medians["grade"])
    out["grade_missing"] = grade.isna().astype(int)
    out["english_ord"] = eng.fillna(medians["english"])
    out["english_missing"] = eng.isna().astype(int)
    out["subject_quant_level"] = df["subject_quant_level"]
    out["tier_ord"] = df["tier_code"].map(_TIER_ORD)
    out["years_since_grad"] = CURRENT_YEAR - df["graduation_year"]
    out["years_experience"] = df["years_experience"]
    subj = pd.get_dummies(df["subject_name"], prefix="subj", dtype=int)
    out = pd.concat([out, subj], axis=1)

    leaked = PROTECTED_ATTRIBUTES.intersection(out.columns)
    assert not leaked, f"protected attributes leaked into features: {leaked}"
    return out, df["y"].to_numpy(), list(out.columns), medians


def align_columns(X: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Give the test matrix exactly the train columns (missing one-hots -> 0)."""
    return X.reindex(columns=columns, fill_value=0)


def data_hash(df: pd.DataFrame) -> str:
    """Reproducibility fingerprint of the modelling dataset."""
    return hashlib.sha256(
        pd.util.hash_pandas_object(df.sort_values("applicant_id"), index=False)
        .values.tobytes()).hexdigest()[:16]
