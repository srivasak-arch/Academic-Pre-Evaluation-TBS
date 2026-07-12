"""Calibration metrics, exactly as pre-registered: Brier score, Expected
Calibration Error with 10 equal-width bins, and reliability-diagram data."""
from __future__ import annotations
import numpy as np

N_BINS = 10


def brier(y_true, p) -> float:
    y, p = np.asarray(y_true, float), np.asarray(p, float)
    return float(np.mean((p - y) ** 2))


def climatological_brier(y_true) -> float:
    """Baseline: always predict the base rate. Brier = p(1-p)."""
    p = float(np.mean(y_true))
    return p * (1.0 - p)


def reliability_bins(y_true, p, n_bins: int = N_BINS):
    """Per-bin (mean predicted, observed frequency, count) over equal-width bins."""
    y, p = np.asarray(y_true, float), np.asarray(p, float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        mask = idx == b
        if mask.any():
            rows.append({"bin": b, "mean_predicted": float(p[mask].mean()),
                         "observed_rate": float(y[mask].mean()),
                         "count": int(mask.sum())})
    return rows


def ece(y_true, p, n_bins: int = N_BINS) -> float:
    """ECE = sum_b (n_b / N) * |observed_b - predicted_b|."""
    n = len(np.asarray(p))
    return float(sum(r["count"] / n * abs(r["observed_rate"] - r["mean_predicted"])
                     for r in reliability_bins(y_true, p, n_bins)))
