"""
Team A — Academic Pre-Evaluation Dashboard
Synthetic applicant database generator.

Self-contained. No Team B schema/dependency. No composite fit score.
'My Recommendation' is a transparent, rule-based reviewer-facing LABEL.

Reproducible: fixed seed.
Output: applicants.csv (+ a populated SQLite db built in build_db.py)
"""

import numpy as np
import pandas as pd

SEED = 20260628
rng = np.random.default_rng(SEED)
CURRENT_YEAR = 2026
N = 420  # within the 300-500 requested band

# ----------------------------------------------------------------------------
# 1. COUNTRY STRATA  (10 strata, varied distributions)
# ----------------------------------------------------------------------------
# Each stratum carries:
#   weight              : share of the applicant pool
#   english             : prob over [High, Moderate, Low]  (native EN -> mostly High)
#   grade_mean/grade_sd : Irish-equivalent percentage (0-100) sampling params
#   inst_tier           : prob over institution tiers [Tier1, Tier2, Tier3]
#   subj_quant_bias     : nudges subject mix toward quantitative disciplines
#   workexp_bias        : nudges toward more prior work experience
#   forenames / surnames: culturally-plausible SYNTHETIC name pools
COUNTRIES = {
    "Ireland": dict(
        weight=0.10, english=[0.97, 0.03, 0.00], grade_mean=63, grade_sd=8,
        inst_tier=[0.45, 0.40, 0.15], subj_quant_bias=0.05, workexp_bias=0.10,
        nationality_same=0.97,
        forenames=["Aoife","Cian","Niamh","Sean","Saoirse","Conor","Aisling","Eoin","Roisin","Darragh"],
        surnames=["Murphy","Kelly","Byrne","Ryan","Walsh","O'Brien","McCarthy","Gallagher","Doyle","Brennan"],
    ),
    "United Kingdom": dict(
        weight=0.09, english=[0.95, 0.05, 0.00], grade_mean=62, grade_sd=8,
        inst_tier=[0.40, 0.42, 0.18], subj_quant_bias=0.05, workexp_bias=0.10,
        nationality_same=0.90,
        forenames=["Oliver","Amelia","Harry","Isla","George","Ava","Jack","Mia","Charlie","Sophie"],
        surnames=["Smith","Jones","Taylor","Brown","Wilson","Evans","Thomas","Roberts","Clarke","Wright"],
    ),
    "United States": dict(
        weight=0.08, english=[0.93, 0.07, 0.00], grade_mean=64, grade_sd=9,
        inst_tier=[0.42, 0.40, 0.18], subj_quant_bias=0.08, workexp_bias=0.15,
        nationality_same=0.88,
        forenames=["Emily","Michael","Jessica","David","Ashley","James","Sarah","Daniel","Olivia","Ethan"],
        surnames=["Johnson","Williams","Miller","Davis","Garcia","Martinez","Anderson","Thompson","Moore","Jackson"],
    ),
    "India": dict(
        weight=0.16, english=[0.55, 0.40, 0.05], grade_mean=66, grade_sd=9,
        inst_tier=[0.30, 0.45, 0.25], subj_quant_bias=0.20, workexp_bias=0.20,
        nationality_same=0.99,
        forenames=["Aarav","Priya","Rohan","Ananya","Vikram","Sneha","Arjun","Kavya","Aditya","Diya"],
        surnames=["Sharma","Patel","Reddy","Iyer","Nair","Gupta","Mehta","Rao","Desai","Krishnan"],
    ),
    "China": dict(
        weight=0.14, english=[0.35, 0.50, 0.15], grade_mean=68, grade_sd=8,
        inst_tier=[0.35, 0.45, 0.20], subj_quant_bias=0.22, workexp_bias=0.08,
        nationality_same=0.99,
        forenames=["Wei","Li","Yan","Hao","Jing","Chen","Mei","Feng","Xin","Lei"],
        surnames=["Wang","Zhang","Liu","Chen","Yang","Huang","Zhao","Wu","Zhou","Xu"],
    ),
    "Nigeria": dict(
        weight=0.08, english=[0.80, 0.18, 0.02], grade_mean=60, grade_sd=9,
        inst_tier=[0.22, 0.45, 0.33], subj_quant_bias=0.10, workexp_bias=0.18,
        nationality_same=0.99,
        forenames=["Chinedu","Ngozi","Emeka","Adaeze","Tunde","Funmi","Ifeoma","Obinna","Yetunde","Kelechi"],
        surnames=["Okafor","Adeyemi","Okonkwo","Balogun","Eze","Afolabi","Nwosu","Oluwole","Chukwu","Adebayo"],
    ),
    "Germany": dict(
        weight=0.07, english=[0.78, 0.22, 0.00], grade_mean=64, grade_sd=7,
        inst_tier=[0.48, 0.40, 0.12], subj_quant_bias=0.18, workexp_bias=0.22,
        nationality_same=0.92,
        forenames=["Lukas","Anna","Felix","Lena","Jonas","Marie","Paul","Laura","Maximilian","Sophie"],
        surnames=["Muller","Schmidt","Schneider","Fischer","Weber","Wagner","Becker","Hoffmann","Koch","Bauer"],
    ),
    "Brazil": dict(
        weight=0.07, english=[0.45, 0.45, 0.10], grade_mean=61, grade_sd=8,
        inst_tier=[0.30, 0.45, 0.25], subj_quant_bias=0.08, workexp_bias=0.16,
        nationality_same=0.97,
        forenames=["Lucas","Mariana","Gabriel","Beatriz","Rafael","Camila","Felipe","Larissa","Bruno","Juliana"],
        surnames=["Silva","Santos","Oliveira","Souza","Costa","Pereira","Almeida","Ferreira","Rodrigues","Lima"],
    ),
    "Pakistan": dict(
        weight=0.08, english=[0.50, 0.42, 0.08], grade_mean=63, grade_sd=9,
        inst_tier=[0.25, 0.45, 0.30], subj_quant_bias=0.15, workexp_bias=0.16,
        nationality_same=0.99,
        forenames=["Ali","Ayesha","Hassan","Fatima","Bilal","Zara","Usman","Hira","Ahmed","Sana"],
        surnames=["Khan","Ahmed","Malik","Hussain","Raza","Iqbal","Shaikh","Butt","Qureshi","Farooq"],
    ),
    "France": dict(
        weight=0.06, english=[0.62, 0.35, 0.03], grade_mean=62, grade_sd=7,
        inst_tier=[0.45, 0.42, 0.13], subj_quant_bias=0.12, workexp_bias=0.18,
        nationality_same=0.90,
        forenames=["Louis","Emma","Hugo","Chloe","Jules","Lea","Nathan","Manon","Tom","Camille"],
        surnames=["Martin","Bernard","Dubois","Moreau","Laurent","Lefebvre","Girard","Rousseau","Fontaine","Mercier"],
    ),
}
_wsum = sum(c["weight"] for c in COUNTRIES.values())
for _c in COUNTRIES.values():
    _c["weight"] = _c["weight"] / _wsum  # normalise to a proper distribution

# ----------------------------------------------------------------------------
# 2. INSTITUTION POOLS  (synthetic placeholder names, tagged by type/tier)
# ----------------------------------------------------------------------------
# Tier1 = Research-intensive flagship | Tier2 = Established public/regional
# Tier3 = Teaching-focused / private college. Names are fictional templates.
INST_TYPE = {
    "Tier1": "Research-intensive flagship university",
    "Tier2": "Established public / regional university",
    "Tier3": "Teaching-focused or private college",
}

def make_institutions(country):
    adj = {
        "Ireland": ["National","Atlantic","Capital","Eastern","Midland"],
        "United Kingdom": ["Northern","Royal","Central","Metropolitan","Coastal"],
        "United States": ["State","Pacific","Lakeside","Summit","Heritage"],
        "India": ["National","Eastern","Deccan","Northern","Coastal"],
        "China": ["Eastern","Riverside","Central","Coastal","Northern"],
        "Nigeria": ["Federal","Western","Coastal","Highland","Unity"],
        "Germany": ["Federal","Rhine","Central","Alpine","Northern"],
        "Brazil": ["Federal","Atlantic","Central","Southern","Coastal"],
        "Pakistan": ["National","Northern","Indus","Capital","Highland"],
        "France": ["National","Central","Riviera","Northern","Loire"],
    }[country]
    pools = {"Tier1": [], "Tier2": [], "Tier3": []}
    for a in adj:
        pools["Tier1"].append(f"{a} University of Science & Technology")
        pools["Tier1"].append(f"{a} Research University")
        pools["Tier2"].append(f"{a} University")
        pools["Tier2"].append(f"{a} Institute of Technology")
        pools["Tier3"].append(f"{a} College of Business")
        pools["Tier3"].append(f"{a} University College")
    return pools

INSTITUTIONS = {c: make_institutions(c) for c in COUNTRIES}

# ----------------------------------------------------------------------------
# 3. SUBJECT AREAS  (with quant level used for facet support)
# ----------------------------------------------------------------------------
# quant level: 2=high, 1=moderate, 0=low. Drives Quantitative Readiness &
# Prerequisites Coverage facets downstream.
SUBJECTS = {
    "Mathematics & Statistics": 2, "Computer Science": 2, "Data Science": 2,
    "Engineering": 2, "Physics": 2, "Economics": 2,
    "Finance": 1, "Accounting": 1, "Information Systems": 1, "Actuarial Science": 2,
    "Business Administration": 1, "Management": 1, "Commerce": 1,
    "Marketing": 0, "Psychology": 0, "International Relations": 0,
}
SUBJ_NAMES = list(SUBJECTS.keys())
# base popularity weights, then re-weighted per stratum by quant bias
SUBJ_BASE = np.array([
    0.06,0.10,0.07,0.09,0.03,0.08,   # quant=2 block (+econ)
    0.07,0.06,0.05,0.02,             # quant=1 finance-ish
    0.08,0.07,0.05,                  # quant=1 mgmt
    0.04,0.04,0.02,                  # quant=0
])
SUBJ_BASE = SUBJ_BASE / SUBJ_BASE.sum()
QUANT_LEVEL = np.array([SUBJECTS[s] for s in SUBJ_NAMES])

# ----------------------------------------------------------------------------
# 4. ROW GENERATION
# ----------------------------------------------------------------------------
ENGLISH_LEVELS = ["High", "Moderate", "Low"]
GENDERS = ["Female", "Male", "Non-binary", "Prefer not to say"]
GENDER_P = [0.47, 0.47, 0.03, 0.03]

def irish_band(pct):
    if pd.isna(pct): return None
    if pct >= 70: return "First Class Honours (1.1)"
    if pct >= 60: return "Upper Second (2.1)"
    if pct >= 50: return "Lower Second (2.2)"
    if pct >= 45: return "Third Class Honours"
    return "Pass / Below honours"

rows = []
country_names = list(COUNTRIES.keys())
country_weights = np.array([COUNTRIES[c]["weight"] for c in country_names])

for i in range(N):
    country = rng.choice(country_names, p=country_weights)
    C = COUNTRIES[country]

    # --- Nationality (usually same as country of study) ---
    if rng.random() < C["nationality_same"]:
        nationality = country
    else:
        nationality = rng.choice([c for c in country_names if c != country])

    # --- Name (synthetic) ---
    forename = rng.choice(C["forenames"])
    surname = rng.choice(C["surnames"])

    # --- Institution tier + name ---
    tier = rng.choice(["Tier1", "Tier2", "Tier3"], p=C["inst_tier"])
    institution = rng.choice(INSTITUTIONS[country][tier])
    inst_info = INST_TYPE[tier]

    # --- Subject area (quant-biased per stratum) ---
    w = SUBJ_BASE * (1 + C["subj_quant_bias"] * QUANT_LEVEL)
    w = w / w.sum()
    subject = rng.choice(SUBJ_NAMES, p=w)
    subj_quant = SUBJECTS[subject]

    # --- Graduation year ---
    # weight recent years more heavily; range 2014..2026
    yrs = np.arange(2014, CURRENT_YEAR + 1)
    yw = np.linspace(0.4, 1.0, len(yrs)) ** 2
    yw = yw / yw.sum()
    grad_year = int(rng.choice(yrs, p=yw))
    years_since_grad = CURRENT_YEAR - grad_year

    # --- Age ---
    # typical UG completion age ~22 (+/-), plus years since graduation, plus jitter
    base_grad_age = float(np.clip(rng.normal(22.5, 1.4), 20.0, 29.0))
    age = int(round(base_grad_age + years_since_grad + rng.normal(0, 0.6)))
    # guard: nobody graduates younger than 19 or older than 30
    age = max(age, years_since_grad + 19)
    age = min(age, years_since_grad + 30)
    age = max(20, min(age, 45))

    # --- Grade (Irish equivalent percentage) ---
    # Tier1 institutions skew slightly higher; clip to plausible 38..82
    tier_adj = {"Tier1": 2.0, "Tier2": 0.0, "Tier3": -2.0}[tier]
    grade = rng.normal(C["grade_mean"] + tier_adj, C["grade_sd"])
    grade = float(np.clip(round(grade, 1), 38.0, 82.0))

    # --- English proficiency ---
    english = rng.choice(ENGLISH_LEVELS, p=C["english"])

    # --- Work experience (consistent with years_since_grad) ---
    # capacity = years available to work since graduation
    bias = C["workexp_bias"]
    p_none = max(0.05, 0.55 - 0.18 * years_since_grad - bias)
    p_intern = 0.20
    p_12 = 0.15 + 0.05 * years_since_grad
    p_3plus = 0.10 + 0.10 * years_since_grad + bias
    p = np.array([p_none, p_intern, p_12, p_3plus]); p = p / p.sum()
    workexp_cat = rng.choice(["No experience", "Internships", "1-2 years", "3+ years"], p=p)

    # downgrade category if graduation capacity cannot support it
    cap = max(0, years_since_grad)
    if workexp_cat == "3+ years" and cap < 3:
        workexp_cat = "1-2 years" if cap >= 1 else rng.choice(["No experience", "Internships"])
    if workexp_cat == "1-2 years" and cap < 1:
        workexp_cat = rng.choice(["No experience", "Internships"])

    # numeric years' experience consistent with category AND capacity
    if workexp_cat == "No experience":
        years_exp = 0
    elif workexp_cat == "Internships":
        years_exp = 0  # internships logged in category, not full years
    elif workexp_cat == "1-2 years":
        years_exp = int(min(rng.integers(1, 3), cap))
    else:  # 3+ years
        years_exp = int(min(rng.integers(3, cap + 1), cap))

    rows.append(dict(
        country=country, nationality=nationality, forename=forename, surname=surname,
        age=age, gender=rng.choice(GENDERS, p=GENDER_P),
        institution=institution, inst_info=inst_info, inst_tier=tier,
        subject=subject, subj_quant=subj_quant, grad_year=grad_year,
        years_since_grad=years_since_grad, grade=grade, english=english,
        workexp_cat=workexp_cat, years_exp=years_exp,
    ))

df = pd.DataFrame(rows)

# ----------------------------------------------------------------------------
# 5. MISSINGNESS (realistic, restrained)
# ----------------------------------------------------------------------------
def inject_missing(series, frac, replace=np.nan):
    idx = rng.choice(series.index, size=int(round(frac * len(series))), replace=False)
    series = series.copy()
    series.loc[idx] = replace
    return series

# English pending test (~6%), grade transcript pending (~3%),
# institution extra info unparsed (~4%)
df["english"] = inject_missing(df["english"], 0.06)
df["grade"]   = inject_missing(df["grade"],   0.03)
df["inst_info"] = inject_missing(df["inst_info"], 0.04)

# ----------------------------------------------------------------------------
# 6. NOTES (short, structured reviewer flags — NOT free-text essays)
# ----------------------------------------------------------------------------
def make_note(r):
    flags = []
    if pd.isna(r["grade"]):
        flags.append("Transcript pending")
    if pd.isna(r["english"]):
        flags.append("English test pending")
    if r["years_since_grad"] >= 9:
        flags.append("Study not recent")
    if r["subj_quant"] == 2 and not pd.isna(r["grade"]) and r["grade"] >= 65:
        flags.append("Strong quantitative background")
    if r["subj_quant"] == 0:
        flags.append("Check prerequisites for analytics track")
    if r["inst_tier"] == "Tier1" and not pd.isna(r["grade"]) and r["grade"] >= 68:
        flags.append("Flagship institution, high grade")
    if r["workexp_cat"] == "3+ years":
        flags.append("Relevant work experience")
    return "; ".join(flags) if flags else np.nan

df["notes"] = df.apply(make_note, axis=1)
# ~25% of clean profiles carry no note -> blank is fine
df["notes"] = inject_missing(df["notes"], 0.05)

# ----------------------------------------------------------------------------
# 7. MY RECOMMENDATION (transparent rule-based reviewer LABEL — not a score)
# ----------------------------------------------------------------------------
# Rules (documented in the data dictionary):
#  Needs Review     : grade OR english missing (cannot assess fairly)
#  Not Recommended  : grade < 50 (below 2.2)  OR (grade < 55 AND english == Low)
#  Strong Fit       : grade >= 65 AND english == High AND years_since_grad <= 8
#                     AND subj_quant >= 1
#  Borderline       : everything else
def recommend(r):
    if pd.isna(r["grade"]) or pd.isna(r["english"]):
        return "Needs Review"
    g, e, rec, q = r["grade"], r["english"], r["years_since_grad"], r["subj_quant"]
    if g < 50 or (g < 55 and e == "Low"):
        return "Not Recommended"
    if g >= 65 and e == "High" and rec <= 8 and q >= 1:
        return "Strong Fit"
    return "Borderline"

df["recommendation"] = df.apply(recommend, axis=1)

# ----------------------------------------------------------------------------
# 8. ASSEMBLE FINAL TABLE in requested column order
# ----------------------------------------------------------------------------
df.insert(0, "applicant_id", [f"TBS-2026-{n:04d}" for n in range(1, len(df) + 1)])

final = pd.DataFrame({
    "ID": df["applicant_id"],
    "Surname": df["surname"],
    "Forename": df["forename"],
    "Country": df["country"],
    "Age": df["age"],
    "Gender": df["gender"],
    "Nationality": df["nationality"],
    "Institution": df["institution"],
    "Further info on institution": df["inst_info"],
    "Subject area": df["subject"],
    "Graduation Year": df["grad_year"],
    "Grade (Irish eq.)": df["grade"],
    "English": df["english"],
    "Work Experience": df["workexp_cat"],
    "Years' experience": df["years_exp"],
    "Notes": df["notes"],
    "My Recommendation": df["recommendation"],
})

final.to_csv("/home/claude/academic_dashboard/data/applicants.csv", index=False)
df.to_csv("/home/claude/academic_dashboard/data/_internal_full.csv", index=False)  # keep helper cols for validation
print("Generated", len(final), "rows -> applicants.csv")
print(final.head(3).to_string())
