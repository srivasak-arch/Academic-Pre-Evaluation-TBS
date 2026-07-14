"""Per-facet calibration + extended fairness (prestige/country/gender) for Chapter 5."""
import json, numpy as np, pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from lightgbm import LGBMClassifier
from src import db
from src.ml import calibration as cal
from src.ml.features import load_dataset, build_matrix, align_columns
from src.ml.service import SEED, TEST_SIZE, MODEL_PARAMS

conn = db.get_connection()
df = load_dataset(conn)
tr, te = train_test_split(df, test_size=TEST_SIZE, random_state=SEED, stratify=df["y"])
Xtr, ytr, cols, med = build_matrix(tr)
Xte, yte, _, _ = build_matrix(te, medians=med)
Xte = align_columns(Xte, cols)
base = cal.climatological_brier(yte)
print(f"N train={len(tr)} test={len(te)}  test base rate={yte.mean():.3f}  climatological Brier={base:.4f}\n")

# ---------- per-facet single-facet models ----------
FACETS = {
 "Academic performance": ["grade_irish_eq","grade_missing"],
 "English proficiency":  ["english_ord","english_missing"],
 "Quantitative preparation": ["subject_quant_level"],
 "Institutional context": ["tier_ord"],
 "Recency of study":     ["years_since_grad"],
 "Work experience":      ["years_experience"],
 "Subject alignment":    [c for c in cols if c.startswith("subj_")],
}
print("PER-FACET CALIBRATION (single-facet calibrated LightGBM)")
print(f"{'Facet':<26}{'Brier':>8}{'ECE':>8}{'AUC':>8}  {'vs baseline':>12}")
rows=[]
for name, feats in FACETS.items():
    f = [c for c in feats if c in cols]
    m = CalibratedClassifierCV(LGBMClassifier(**MODEL_PARAMS["lightgbm"]), method="sigmoid", cv=5)
    m.fit(Xtr[f], ytr)
    p = m.predict_proba(Xte[f])[:,1]
    b, e = cal.brier(yte,p), cal.ece(yte,p)
    try: a = roc_auc_score(yte,p)
    except: a = float("nan")
    rows.append((name,b,e,a))
    print(f"{name:<26}{b:>8.4f}{e:>8.4f}{a:>8.3f}  {'better' if b<base else 'WORSE':>12}")

# full model for reference
full = CalibratedClassifierCV(LGBMClassifier(**MODEL_PARAMS["lightgbm"]), method="sigmoid", cv=5).fit(Xtr, ytr)
pf = full.predict_proba(Xte)[:,1]
print(f"{'ALL FACETS (full model)':<26}{cal.brier(yte,pf):>8.4f}{cal.ece(yte,pf):>8.4f}{roc_auc_score(yte,pf):>8.3f}")

# ---------- fairness incl. prestige ----------
print("\nFAIRNESS AUDIT (full calibrated model)")
base_rate = ytr.mean()
thr = float(np.quantile(pf, 1-base_rate)); flag = pf >= thr
print(f"flag threshold={thr:.3f}  flagged={flag.mean():.1%}\n")
dims = {
 "Prestige (tier)": te["tier_code"].to_numpy(),
 "Gender": te["gender"].to_numpy(),
 "Nationality": np.where(np.isin(te["nationality_code"],["IN","CN","IE","GB"]), te["nationality_code"], "Other"),
}
for dim, vals in dims.items():
    print(f"--- {dim} ---")
    rates={}
    for g in sorted(set(vals)):
        m_ = vals==g; n=int(m_.sum())
        sr = float(flag[m_].mean())
        br = cal.brier(yte[m_], pf[m_]) if n>=30 else None
        rates[g]=(n,sr,br)
    audited = {g:v for g,v in rates.items() if v[0]>=30}
    ref = max((v[1] for v in audited.values()), default=0)
    for g,(n,sr,br) in rates.items():
        di = sr/ref if (n>=30 and ref>0) else None
        tag = ("PASS" if 0.80<=di<=1.25 else "FAIL") if di is not None else "descriptive (n<30)"
        print(f"  {g:<20} n={n:<4} sel_rate={sr:.1%}  DI={di:.2f} {tag}" if di is not None
              else f"  {g:<20} n={n:<4} sel_rate={sr:.1%}  {tag}")
        if br is not None: print(f"      group Brier={br:.4f}")
