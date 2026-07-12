# Deploying to Streamlit Community Cloud

## Before you push

Files that must be at the **repository root** (all now present):

| File | Purpose |
|---|---|
| `app.py` | Entrypoint Streamlit Cloud runs |
| `requirements.txt` | Python dependencies |
| `packages.txt` | **apt** system packages — `libgomp1` is required by LightGBM and the app will crash on import without it |
| `.streamlit/config.toml` | TBS theme + upload limit |
| `data/dashboard.db` | The seeded synthetic database — **must be committed**, or the deployed app boots empty |

Confirm the database really is tracked (a stray `*.db` rule in a global gitignore is the usual culprit):

```bash
git add -f data/dashboard.db
git check-ignore -v data/dashboard.db   # should print nothing
git status --short data/dashboard.db    # should show the file staged
```

## Deploy

1. Push the repo to GitHub (public, or private with Streamlit Cloud granted access).
2. Go to <https://share.streamlit.io> and sign in with GitHub.
3. **Create app** → select the repo, branch, and set **Main file path** to `app.py`.
4. Deploy. First build takes several minutes — scikit-learn, LightGBM, and SHAP are large wheels.

## Known constraints of the hosted instance

**The filesystem is ephemeral.** Streamlit Community Cloud rebuilds the container
from Git whenever the app reboots (redeploy, inactivity sleep, or platform restart).
Anything written at runtime — recorded decisions, threshold edits, audit entries,
school confirmations, new ML runs — is **lost on reboot**, and the app resets to
the committed `dashboard.db`.

This is acceptable for a demonstration deployment, and the app is seeded so that
examiners land on a fully populated system (426 applications, 4,260 indicator
evaluations, one completed pre-registered ML run). It is **not** suitable for a
UX study or any use where recorded decisions must survive.

For real persistence, swap SQLite for a hosted Postgres (Supabase / Neon free
tier). Because every SQL statement lives in `src/db.py`, only that module and the
connection helper change; pages, services, and engines are untouched.

**Resource limits.** The ML stack (scikit-learn + LightGBM + SHAP) is memory-heavy
for the free tier. Re-running the experiment from the Predictive analytics page on
the hosted instance may hit the memory ceiling and restart the app. The committed
run is already persisted and renders without retraining, so treat the *Run
experiment* button as a local-only affordance — or hide it when a
`DEMO_MODE` secret is set.

**OCR is off by default.** `pytesseract` is commented out of `requirements.txt`, so
scanned PDF pages yield no text (the app flags this in the UI). The synthetic corpus
is natively digital, so nothing is lost. To enable OCR: uncomment `pytesseract` and
`Pillow` in `requirements.txt`, and add `tesseract-ocr` to `packages.txt`.

## Optional: gate the demo behind a password

Streamlit Cloud apps are public by default. To restrict access, add a secret in the
app's **Settings → Secrets**:

```toml
app_password = "choose-something"
```

and check it at the top of `app.py` with `st.secrets["app_password"]` before rendering
the navigation.
