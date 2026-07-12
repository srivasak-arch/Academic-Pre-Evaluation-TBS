# Academic Pre-Evaluation Dashboard

A reviewer-facing **decision-support** dashboard for Trinity Business School MSc
admissions (Team A). It surfaces independent, explainable academic indicators so
an admissions reviewer can evaluate applicants faster, more consistently, and
more transparently — while the **human always makes the final decision**.

It supports two programmes — **MSc Business Analytics (BA)** and
**MSc International Management (IM)** — on synthetic data only, and is fully
independent of Team B.

> **This build has no login.** It opens straight into a single combined view with
> review, oversight, governance (thresholds), and data/admin all available.

## Run it as a single double-click app (no terminal, no Python)

You can package the whole dashboard into **one self-contained executable** that the
end user just double-clicks — no command prompt, no `pip`, no Python install, and
the database travels inside it.

Because an executable only runs on the operating system it was built on, build it
once on the machine you'll use:

```
python build.py
```

That installs the bundler if needed, builds the database, and produces a single
file in `dist/`:

- Windows → `dist\AcademicDashboard.exe`
- macOS → `dist/AcademicDashboard` (first launch: right-click → Open)
- Linux → `dist/AcademicDashboard`

After that, **double-click the file in `dist/`**. It starts the server quietly and
opens the dashboard in your browser. Its data (decisions, notes, threshold edits,
added applicants) is stored in a folder called `AcademicPreEvalDashboard` in your
home directory, so it persists between launches.

> A prebuilt **Linux** binary is included (`AcademicDashboard-linux.zip`) and was
> tested end-to-end. For Windows or macOS, run `python build.py` on that machine —
> it's a single step.

## Branding & look

The interface uses Trinity Business School's design language: TBS blue `#0E73B9`
for navigation, links, and primary actions on a cool `#F8F8F8`/white surface,
Source Sans typography, the TBS logo lockup in the sidebar, and the school banner
across the top of every page (assets in `assets/`). Brand blue is deliberately
reserved for interface chrome — the red/amber/green vocabulary remains exclusive
to evidence indicators, and neutral chips are true grey so context can never read
as "selected". Cohort analytics are cached with automatic invalidation (keyed on
data changes), so the insights pages stay fast as the pool grows.

## Design philosophy (enforced, not just stated)

- **Never** auto-admits or auto-rejects — there is no "decide" function.
- **Never** produces a composite score, and **never** ranks applicants. This is a
  *tested invariant* (`tests/test_rules.py::test_no_aggregation_function_exists`,
  `::test_evidence_confidence_ignores_colours`).
- Presents **evidence, not verdicts**: ten independent indicators, each with a
  plain-English reason, the inputs it used, and a confidence marker.
- **Institution Context** is neutral metadata (never red/amber/green) to avoid
  prestige/country bias.
- **Work Experience** is neutral for BA (supplementary) and a RAG signal for IM.
- The legacy "My Recommendation" label is kept only as provenance and is **hidden**
  from the operational view.
- Progressive disclosure keeps the surface calm; decisions require a written
  rationale; everything is append-only and audited.

## Or run it the classic way (Python developers)

```bash
pip install -r requirements.txt
python -m src.ingest        # builds data/dashboard.db (420 applicants, 4200 evaluations)
streamlit run app.py
```

Or with make: `make install && make run`. With Docker: `docker build -t tbs-dashboard . && docker run -p 8501:8501 tbs-dashboard`.

The app opens directly — no sign-in. Use the left sidebar to move between Review,
Oversight & governance, and Data & admin.

## Data insights (BI analytics)

A dedicated **Data insights** page (Oversight & governance) turns the applicant pool
into decision-support analytics. Every panel answers a business question and carries a
plain-English narrative, so the page is usable without reading the charts. Sections:
Executive summary (KPI cards), Applicant demographics, Academic insights, Experience &
readiness, Decision & recommendation overview, Data quality (missingness + consistency
checks), and Fairness & distribution monitoring. A filter bar (programme, country,
English, readiness, graduation window) scopes every panel. The fairness section suppresses
small groups and states plainly that observed differences do not imply bias. It adds no
composite score or ranking — only cohort-level distributions of the existing indicators.

## Configure and extend in-app

- **Adjust thresholds** (Oversight & governance → *Thresholds*): edit the green/amber
  cut-points per programme for Academic Performance, Graduation Recency, Document
  Completeness, the Quantitative Readiness grade gate, and the Work Experience
  treatment (neutral vs RAG). Saving creates a **new version** (the previous one is
  closed, never overwritten), so past decisions stay replayable. The applicant view
  uses new thresholds immediately; click *Recompute all indicator evaluations* to
  refresh the fairness charts. Institution Context stays neutral and is not editable
  by design.
- **Add applicants** (Data & admin → *Applicant data*): add a single record via a
  form, or bulk-upload a CSV with the same columns as `data/applicants.csv`. New
  records appear in the work queue immediately, with indicators computed on save.

## Architecture (layered)

```
Streamlit pages (app.py, src/pages_impl.py, src/ui.py)   ← presentation, no logic
        │
services (src/services.py)                               ← orchestration
        │
rules engine (src/rules.py)  ← PURE functions, 1 per indicator, no aggregation
        │
repositories (src/db.py) over SQLite (src/schema.sql)    ← all SQL lives here
```

- The rules engine is pure and deterministic, so explanations *are* the
  computation (no black box) and the engine is fully unit-tested.
- All SQL is isolated in `src/db.py`; swapping SQLite → PostgreSQL for a pilot is
  a connection change, not a rewrite.
- Notes, decisions, indicator evaluations, and the audit log are **append-only**,
  with id-based tiebreakers so "latest" is always unambiguous.
- Thresholds live in a **versioned** `threshold_config` table (per indicator, per
  programme), so any past decision can be replayed against the rules in force at
  the time.

## The ten indicators

Academic Performance · Programme Prerequisites · Quantitative Readiness ·
English Requirement · Institution Context *(neutral)* · Subject Alignment ·
Work Experience *(neutral for BA)* · Graduation Recency · Document Completeness ·
Confidence in Available Evidence *(meta — about the data, not the applicant)*.

Each renders colour + icon + word, with fill style encoding confidence (solid =
high, hatched/outlined = lower), so a low-evidence green is visibly distinct from
a high-evidence one.

## Tests

```bash
python -m pytest tests/ -q     # 23 tests
```

- `test_rules.py` — indicator correctness + the non-aggregation / neutral-context /
  evidence-confidence invariants.
- `test_app_smoke.py` — headless AppTest: app opens without login, queue is default, Review opens the profile.
- `test_workflow.py` — append-only notes/decisions, frozen snapshot, audit, threshold-edit versioning, in-app applicant add,
  neutral queue ordering.

## What's intentionally out of scope (future)

Learnt sub-signals / ML, predictive analytics, applicant comparison, reviewer
calibration, SSO/full RBAC, a threshold-editor UI, document ingestion / Team B
integration, and a FastAPI layer for a production frontend. The architecture
leaves clean seams for each. See `design_document.md` for the full specification.

## Project layout

```
app.py                  Streamlit entrypoint (combined view, no login)
desktop_launcher.py     entry point that the single-file executable runs
build.py                one-step builder -> dist/AcademicDashboard(.exe)
AcademicDashboard.spec  PyInstaller bundle definition
src/
  config.py             paths, palette, programmes, indicator order
  schema.sql            operational + academic schema (append-only tables)
  db.py                 connection + repository functions (all SQL)
  rules.py              the rules engine (10 indicators, no aggregation)
  ingest.py             build DB, seed users/programmes/thresholds, pre-compute evals
  services.py           auth + evaluation orchestration
  ui.py                 CSS + indicator chip rendering
  pages_impl.py         page render functions
  generate_data.py      synthetic corpus generator (reproducible)
data/
  applicants.csv        synthetic corpus (420 applicants)
  dashboard.db          built by `python -m src.ingest`
tests/                  pytest suite
```
