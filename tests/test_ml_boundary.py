"""Tests for the research-track ML layer.

The critical ones are the BOUNDARY tests: the predictive model must never leak
into the operational advisory system. These make the report claim 'separation is
enforced by test, not convention' literally true.
"""
import numpy as np
import pytest

from src.config import INDICATOR_ORDER
from src.ml import calibration as cal
from src.ml.features import PROTECTED_ATTRIBUTES, build_matrix, load_dataset


# ---------------- Boundary: research track never touches operations ----------------
def test_ml_keys_never_in_indicator_order():
    """The advisory chip row is defined by INDICATOR_ORDER; no model output there."""
    forbidden = {"ml", "model", "prediction", "probability", "shap"}
    for key in INDICATOR_ORDER:
        assert not any(f in key.lower() for f in forbidden)


def test_rules_engine_has_no_ml_imports():
    """The operational rules engine must not depend on the research track."""
    import src.rules as rules
    import inspect
    source = inspect.getsource(rules)
    for banned in ("src.ml", "from .ml", "lightgbm", "sklearn", "shap"):
        assert banned not in source


def test_experiment_writes_only_ml_tables(tmp_path, monkeypatch):
    """Running the experiment must not add rows to indicator_evaluation."""
    import shutil, sqlite3
    from src import db as dbmod
    dst = tmp_path / "dashboard.db"
    shutil.copy("data/dashboard.db", dst)
    monkeypatch.setattr(dbmod, "DB_PATH", dst)
    dbmod._ML_DDL_DONE = False
    conn = sqlite3.connect(dst)
    conn.row_factory = sqlite3.Row
    before = conn.execute("SELECT COUNT(*) FROM indicator_evaluation").fetchone()[0]

    from src.ml.service import run_experiment
    res = run_experiment(conn)

    after = conn.execute("SELECT COUNT(*) FROM indicator_evaluation").fetchone()[0]
    assert after == before, "ML experiment leaked into indicator_evaluation"
    assert conn.execute("SELECT COUNT(*) FROM ml_run").fetchone()[0] >= 1
    assert conn.execute("SELECT COUNT(*) FROM ml_prediction WHERE run_id=?",
                        (res["run_id"],)).fetchone()[0] == res["n_test"]
    dbmod._ML_DDL_DONE = False


# ---------------- Features: protected attributes stay out ----------------
def test_protected_attributes_never_features():
    import sqlite3
    conn = sqlite3.connect("data/dashboard.db")
    df = load_dataset(conn)
    X, y, cols, _ = build_matrix(df)
    assert not PROTECTED_ATTRIBUTES.intersection(cols)
    assert "gender" not in " ".join(cols).lower()
    assert len(X) == len(y) == len(df)


# ---------------- Calibration math ----------------
def test_brier_known_values():
    assert cal.brier([1, 0], [1.0, 0.0]) == 0.0
    assert cal.brier([1, 0], [0.0, 1.0]) == 1.0
    assert cal.brier([1], [0.5]) == pytest.approx(0.25)


def test_ece_perfectly_calibrated_bins():
    """In each bin the observed rate equals the mean prediction -> ECE == 0."""
    p = np.array([0.25] * 4 + [0.75] * 4)
    y = np.array([0, 0, 0, 1, 1, 1, 1, 0])   # 25% and 75% observed
    assert cal.ece(y, p) == pytest.approx(0.0, abs=1e-9)


def test_ece_maximally_miscalibrated():
    y = np.array([0, 0, 0, 0])
    p = np.array([0.95, 0.95, 0.95, 0.95])   # confident and always wrong
    assert cal.ece(y, p) == pytest.approx(0.95)


def test_climatological_baseline():
    assert cal.climatological_brier([1, 0, 0, 0]) == pytest.approx(0.1875)
