# Pre-registration — Predictive Modelling & Calibration Evaluation (Stage 4)

**Committed BEFORE the experiment was executed.** Any deviation from this plan is
reported as a deviation in the dissertation.

Research track only: predictions from this experiment are NEVER surfaced in the
operational review workflow, never written to `indicator_evaluation`, and never
aggregated into the advisory indicator chips. This separation is enforced by
automated tests (`tests/test_ml_boundary.py`).

## Data
- Source: `data/dashboard.db`, `applicant` table (synthetic cohort, seed 20260628).
- Unit of analysis: applicant (N = 420; rows with NULL `baseline_label` excluded).
- Target (binary): `baseline_label == 'Strong Fit'` → 1, else 0.
  Rationale: cleanest calibration target; alternative classes are too small
  (Not Recommended n=14) for reliable binning.

## Features (fixed in advance)
grade_irish_eq (median-imputed + `grade_missing` flag), english ordinal
(Low=0, Moderate=1, High=2; median-imputed + `english_missing` flag),
subject_quant_level, institution tier ordinal (Tier3=0 … Tier1=2),
years_since_graduation (2026 − graduation_year), years_experience,
subject_name one-hot.
**Excluded on purpose:** gender, nationality, country of residence — protected
or proxy attributes; used only in the fairness audit, never as model inputs.

## Protocol
- Split: stratified 70/30 train/test, `random_state = 20260628`. Single split
  (N too small for nested CV); 5-fold CV inside the training set only.
- Models: (a) Logistic Regression (L2, C=1.0, max_iter=2000) — transparent
  baseline; (b) LightGBM (n_estimators=300, learning_rate=0.05, num_leaves=15,
  min_child_samples=20) — learnt model.
- Calibration: Platt scaling (sigmoid) via `CalibratedClassifierCV(cv=5)` fitted
  on the training set only. Isotonic is NOT used (N < 1000 guidance).
- Explanation: SHAP values on the test set (TreeExplainer for LightGBM;
  coefficient-based for logistic regression).

## Metrics (held-out test set only)
- Brier score, uncalibrated vs calibrated.
- Expected Calibration Error (ECE), 10 equal-width bins, uncalibrated vs calibrated.
- Reliability diagram (same 10 bins).
- ROC-AUC (secondary, discrimination only).

## Pre-registered pass criteria
1. Calibrated Brier < climatological baseline p(1−p) computed on the test set.
2. Calibrated ECE ≤ 0.08 for the selected model.
3. Calibration must not degrade AUC by more than 0.02.

## Fairness audit (Stage 5, on the calibrated selected model)
- Flag rule for audit purposes only: an applicant is "flagged" if predicted
  probability is in the top q of the test set, q = training base rate.
- Groups: gender (audit groups with n ≥ 30 in test: Female, Male; smaller groups
  reported descriptively, no criteria applied); nationality bucketed to
  {IN, CN, IE, GB, Other} (audit buckets with n ≥ 30).
- Metrics: selection rate per group; disparate-impact ratio vs the highest-rate
  audited group; per-group Brier where n ≥ 30.
- Pre-registered criterion: disparate-impact ratio within [0.80, 1.25] for all
  audited groups. Outside → reported as a fairness finding, not silently tuned away.

## Model selection rule
The reported "selected model" is the one with the lower calibrated Brier score
on the test set. Both models are reported regardless.
