"""Research-track experiment runner (Stage 4 calibration + Stage 5 fairness).

Everything here follows PREREGISTRATION_ML.md. Results persist to dedicated
ml_* tables ONLY -- never to indicator_evaluation, never to the advisory chips.
"""
from __future__ import annotations
import json

import numpy as np
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from .. import db
from . import calibration as cal
from .features import (align_columns, build_matrix, data_hash, load_dataset,
                       FEATURE_PROVENANCE)

SEED = 20260628                      # pre-registered (matches the synthetic-data seed)
TEST_SIZE = 0.30
ECE_PASS = 0.08                      # pre-registered criteria
AUC_DEGRADE_MAX = 0.02
DI_LOW, DI_HIGH = 0.80, 1.25
AUDIT_MIN_N = 30
NAT_BUCKETS = ("IN", "CN", "IE", "GB")   # rest -> 'Other'

MODEL_PARAMS = {
    "logistic_regression": dict(C=1.0, max_iter=2000),
    "lightgbm": dict(n_estimators=300, learning_rate=0.05, num_leaves=15,
                     min_child_samples=20, random_state=SEED, verbose=-1),
}


def _make_model(name):
    if name == "logistic_regression":
        return LogisticRegression(**MODEL_PARAMS[name])
    return LGBMClassifier(**MODEL_PARAMS[name])


def run_experiment(conn, user_id=None) -> dict:
    df = load_dataset(conn)
    tr_df, te_df = train_test_split(df, test_size=TEST_SIZE, random_state=SEED,
                                    stratify=df["y"])
    Xtr, ytr, cols, medians = build_matrix(tr_df)
    Xte_raw, yte, _, _ = build_matrix(te_df, medians=medians)
    Xte = align_columns(Xte_raw, cols)

    results = {"models": {}, "seed": SEED, "n_train": len(tr_df), "n_test": len(te_df),
               "base_rate_train": float(np.mean(ytr)),
               "climatological_brier": cal.climatological_brier(yte),
               "data_hash": data_hash(df), "feature_names": cols,
               "provenance": FEATURE_PROVENANCE}

    for name in MODEL_PARAMS:
        raw = _make_model(name).fit(Xtr, ytr)
        p_uncal = raw.predict_proba(Xte)[:, 1]
        calib = CalibratedClassifierCV(_make_model(name), method="sigmoid", cv=5)
        calib.fit(Xtr, ytr)
        p_cal = calib.predict_proba(Xte)[:, 1]

        m = {
            "brier_uncal": cal.brier(yte, p_uncal), "brier_cal": cal.brier(yte, p_cal),
            "ece_uncal": cal.ece(yte, p_uncal), "ece_cal": cal.ece(yte, p_cal),
            "auc_uncal": float(roc_auc_score(yte, p_uncal)),
            "auc_cal": float(roc_auc_score(yte, p_cal)),
            "reliability_uncal": cal.reliability_bins(yte, p_uncal),
            "reliability_cal": cal.reliability_bins(yte, p_cal),
            "p_cal": p_cal.tolist(), "p_uncal": p_uncal.tolist(),
        }
        m["passes"] = {
            "brier_beats_climatology": m["brier_cal"] < results["climatological_brier"],
            "ece_within_0.08": m["ece_cal"] <= ECE_PASS,
            "auc_not_degraded": (m["auc_uncal"] - m["auc_cal"]) <= AUC_DEGRADE_MAX,
        }
        m["shap"] = _explain(name, raw, Xtr, Xte, cols)
        results["models"][name] = m

    # pre-registered selection rule: lower calibrated Brier
    selected = min(results["models"], key=lambda k: results["models"][k]["brier_cal"])
    results["selected_model"] = selected
    results["fairness"] = _fairness_audit(
        te_df, np.array(results["models"][selected]["p_cal"]),
        yte, results["base_rate_train"])

    results["run_id"] = _persist(conn, results, te_df, yte, user_id)
    return results


def _explain(name, model, Xtr, Xte, cols):
    """Mean |SHAP| per feature on the test set (top 10)."""
    import shap
    if name == "lightgbm":
        sv = shap.TreeExplainer(model).shap_values(Xte)
        sv = sv[1] if isinstance(sv, list) else sv
    else:
        sv = shap.LinearExplainer(model, Xtr).shap_values(Xte)
    imp = np.abs(np.asarray(sv)).mean(axis=0)
    order = np.argsort(imp)[::-1][:10]
    return [{"feature": cols[i], "mean_abs_shap": float(imp[i])} for i in order]


def _fairness_audit(te_df, p_cal, yte, base_rate):
    """Pre-registered Stage 5 audit on the selected calibrated model."""
    thr = float(np.quantile(p_cal, 1.0 - base_rate))   # flag top-q, q = train base rate
    flagged = p_cal >= thr
    audit = {"threshold": thr, "flag_share": float(flagged.mean()), "groups": []}

    frames = [("gender", te_df["gender"].to_numpy()),
              ("nationality", np.where(np.isin(te_df["nationality_code"], NAT_BUCKETS),
                                       te_df["nationality_code"], "Other"))]
    for dim, values in frames:
        rates = {}
        for g in sorted(set(values)):
            mask = values == g
            n = int(mask.sum())
            entry = {"dimension": dim, "group": str(g), "n": n,
                     "selection_rate": float(flagged[mask].mean()),
                     "audited": n >= AUDIT_MIN_N,
                     "brier": cal.brier(yte[mask], p_cal[mask]) if n >= AUDIT_MIN_N else None}
            audit["groups"].append(entry)
            if entry["audited"]:
                rates[g] = entry["selection_rate"]
        ref = max(rates.values()) if rates else None
        for entry in audit["groups"]:
            if entry["dimension"] == dim and entry["audited"] and ref:
                ratio = entry["selection_rate"] / ref if ref > 0 else None
                entry["di_ratio"] = ratio
                entry["di_pass"] = (ratio is not None and DI_LOW <= ratio <= DI_HIGH)
    return audit


def _persist(conn, results, te_df, yte, user_id):
    db.ensure_ml_schema(conn)
    run_id = db.add_ml_run(conn, {
        "seed": SEED, "target_def": "baseline_label == 'Strong Fit'",
        "n_train": results["n_train"], "n_test": results["n_test"],
        "data_hash": results["data_hash"],
        "selected_model": results["selected_model"],
        "params_json": json.dumps(MODEL_PARAMS),
        "results_json": json.dumps({k: v for k, v in results.items()
                                    if k not in ("models",)} |
                                   {"models": {n: {kk: vv for kk, vv in m.items()
                                                   if kk not in ("p_cal", "p_uncal")}
                                               for n, m in results["models"].items()}}),
    })
    sel = results["models"][results["selected_model"]]
    db.add_ml_predictions(conn, run_id, results["selected_model"],
                          te_df["applicant_id"].tolist(), yte.tolist(),
                          sel["p_uncal"], sel["p_cal"])
    db.audit(conn, user_id, "ml_experiment_run", entity_type="ml_run",
             entity_id=str(run_id),
             detail={"selected": results["selected_model"],
                     "brier_cal": sel["brier_cal"], "ece_cal": sel["ece_cal"]})
    return run_id
