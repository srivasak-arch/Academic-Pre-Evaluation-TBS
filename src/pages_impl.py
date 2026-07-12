"""Streamlit page render functions. Registered by app.py via st.navigation.
Pages never touch SQL directly — they go through services/db and the rules engine."""
from __future__ import annotations
import json
import pandas as pd
import streamlit as st

from . import db, services, insights
from .config import PROGRAMMES, DECISION_OPTIONS, PALETTE
from .ui import (inject_css, chip_row, legend, chip_html, inject_insights_css,
                 section_header, kpi_row, narrative, recommendation, limitations)
import altair as alt


@st.cache_resource
def get_conn():
    return db.get_connection()


def _data_version(conn):
    """A cheap fingerprint of everything the analytics depend on. Cached results
    are keyed on it, so they refresh automatically after adds/recomputes/decisions."""
    return tuple(conn.execute(
        "SELECT (SELECT COUNT(*) FROM applicant),"
        " (SELECT COALESCE(MAX(evaluation_id),0) FROM indicator_evaluation),"
        " (SELECT COALESCE(MAX(threshold_id),0) FROM threshold_config),"
        " (SELECT COALESCE(MAX(decision_id),0) FROM decision)").fetchone())


@st.cache_data(show_spinner=False, ttl=600, max_entries=32)
def _cached_insights(version, **filters):
    """Filter-keyed, version-keyed insight load. Opens its own connection so the
    cache key stays hashable; hit rate makes the BI pages feel instant."""
    conn = db.get_connection()
    try:
        return insights.load_insight_data(conn, **filters)
    finally:
        conn.close()


def load_insights_cached(conn, **filters):
    return _cached_insights(_data_version(conn), **filters)


def _user():
    return st.session_state.get("user")


def _audit(action, **kw):
    u = _user()
    db.audit(get_conn(), u["user_id"] if u else None, action, **kw)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
def login_page():
    inject_css()
    st.title("Academic Pre-Evaluation Dashboard")
    st.caption("Trinity Business School — Admissions · decision-support, not decision-making")
    st.markdown("Sign in to review applicants. The dashboard surfaces evidence; "
                "the reviewer always makes the final decision.")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        conn = get_conn()
        user = services.authenticate(conn, username, password)
        if user:
            st.session_state["user"] = dict(user)
            db.audit(conn, user["user_id"], "login")
            st.rerun()
        else:
            st.error("Username or password not recognised. Check your details and try again.")
    with st.expander("Demo accounts (synthetic POC)"):
        st.markdown(
            "- `rkelly` / `reviewer123` — Reviewer\n"
            "- `mmanager` / `manager123` — Admissions Manager\n"
            "- `qgov` / `gov123` — Governance\n"
            "- `admin` / `admin123` — Administrator")


# ---------------------------------------------------------------------------
# Work queue
# ---------------------------------------------------------------------------
def queue_page():
    inject_css()
    conn = get_conn()
    st.markdown("### Work queue")
    st.caption("Applications to review, in neutral order (oldest first). "
               "This list is deliberately **not** ranked by quality.")

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        prog = c1.selectbox("Programme", ["All"] + list(PROGRAMMES.values()))
        prog_code = next((k for k, v in PROGRAMMES.items() if v == prog), None)
        countries = ["All"] + db.distinct_countries(conn)
        country = c2.selectbox("Country", countries)
        completeness = c3.selectbox("Readiness", ["All", "Ready to review", "Awaiting evidence"])
        status = c4.selectbox("Decision status", ["All", "Undecided", "Decided"])
        c5, c6, c7 = st.columns(3)
        english = c5.selectbox("English", ["All", "High", "Moderate", "Low", "Pending"])
        gy_min = c6.number_input("Graduated from", 2014, 2026, 2014)
        search_id = c7.text_input("Search applicant ID")

    rows = services.queue(
        conn,
        programme_code=prog_code,
        country=None if country == "All" else country,
        english=None if english == "All" else english,
        grad_year_min=int(gy_min) if gy_min > 2014 else None,
        completeness=None if completeness == "All" else completeness,
        decision_status=None if status == "All" else status,
        search_id=search_id or None,
    )
    _audit("queue_view", detail={"n": len(rows), "programme": prog_code})

    decided = db.decided_application_ids(conn)
    st.write(f"**{len(rows)}** applications")
    if not rows:
        st.info("No applications match these filters. Try widening them.")
        return

    df = pd.DataFrame([{
        "Applicant": r["applicant_id"],
        "Programme": r["programme_code"],
        "Country": r["country_name"],
        "Graduated": int(r["graduation_year"]),
        "Readiness": "Awaiting evidence" if (r["grade_irish_eq"] is None or r["english_level"] is None)
                     else "Ready to review",
        "Decision": "Decided" if r["application_id"] in decided else "Undecided",
        "_id": r["application_id"],
    } for r in rows])

    st.caption("Click a column header to sort · select a row to open the applicant. "
               "Sorting is a view aid only — the queue is not ranked by quality.")
    event = st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        height=min(560, 44 + 35 * min(len(df), 15)),
        on_select="rerun",
        selection_mode="single-row",
        column_order=["Applicant", "Programme", "Country", "Graduated", "Readiness", "Decision"],
        column_config={
            "Applicant": st.column_config.TextColumn("Applicant", pinned=True,
                help="Applicant reference"),
            "Programme": st.column_config.TextColumn("Programme", width="small"),
            "Country": st.column_config.TextColumn("Country"),
            "Graduated": st.column_config.NumberColumn("Graduated", format="%d", width="small"),
            "Readiness": st.column_config.TextColumn("Readiness"),
            "Decision": st.column_config.TextColumn("Decision", width="small"),
        },
    )
    picked = event.selection.rows if event and event.selection else []
    if not picked:
        # nothing selected (e.g. returning from a profile) — clear the open-guard
        st.session_state.pop("_last_queue_pick", None)
    else:
        app_id = int(df.iloc[picked[0]]["_id"])
        if st.session_state.get("_last_queue_pick") != app_id:
            st.session_state["_last_queue_pick"] = app_id
            st.session_state["goto_application"] = app_id
            st.switch_page(st.session_state["_pages"]["profile"])
    with st.expander("Legend — how to read the indicators"):
        legend()


# ---------------------------------------------------------------------------
# Applicant profile  (the core review surface)
# ---------------------------------------------------------------------------
def profile_page():
    inject_css()
    conn = get_conn()
    app_id = st.session_state.get("goto_application")
    if not app_id:
        st.info("Open an applicant from the **Work queue** to start a review.")
        return
    row = db.get_application(conn, app_id)
    if not row:
        st.warning("That application could not be found.")
        return

    # (A) identity & context band — quiet, de-emphasised
    st.markdown(f"### {row['applicant_id']} · {row['programme_name']}")
    st.markdown(
        f'<div class="idband"><b>{row["forename"]} {row["surname"]}</b> · '
        f'{row["country_name"]} (nationality {row["nationality_name"]}) · age {row["age"]} · '
        f'{row["gender"]}<br>'
        f'{row["subject_name"]} · {row["institution_name"]} · graduated {row["graduation_year"]}'
        f'</div>', unsafe_allow_html=True)

    # School verification status (if a detection has been run for this applicant)
    sv = db.latest_school_verification(conn, row["applicant_id"])
    if sv:
        if sv["status"] in ("confirmed", "corrected") and sv["verified_school"]:
            st.markdown(
                f'<div class="idband">School verified: <b>{sv["verified_school"]}</b> '
                f'({sv["detected_university"] or sv["declared_university"]}) · '
                f'{sv["status"]} {sv["verified_at"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div class="idband">School verification <b>pending</b>: detected '
                f'“{sv["detected_school"] or "—"}” — confirm it on the '
                f'<b>School verification</b> page.</div>', unsafe_allow_html=True)
    st.markdown("<hr>", unsafe_allow_html=True)

    # (B) independent indicator row (loudest element)
    results = services.evaluate_for_display(row, conn)
    _audit("applicant_open", entity_type="application", entity_id=app_id)
    st.markdown('<div class="section-label">Academic indicators (independent · advisory)</div>',
                unsafe_allow_html=True)
    chip_row(results)
    legend()

    # (C) progressive-disclosure evidence
    groups = {
        "Academic & programme fit": ["academic_performance", "programme_prerequisites",
                                     "quantitative_readiness", "subject_alignment"],
        "English": ["english_requirement"],
        "Institution context": ["institution_context"],
        "Recency & experience": ["graduation_recency", "work_experience"],
        "Evidence quality": ["document_completeness", "evidence_confidence"],
    }
    by_key = {r.key: r for r in results}
    st.markdown('<div class="section-label">Evidence — why each indicator shows what it shows</div>',
                unsafe_allow_html=True)
    for title, keys in groups.items():
        with st.expander(title):
            for k in keys:
                r = by_key[k]
                st.markdown(chip_html(r), unsafe_allow_html=True)
                st.markdown(f'<div class="facet-reason">{r.reasoning}</div>', unsafe_allow_html=True)
                with st.popover("Inputs used"):
                    st.json(r.inputs)

    st.markdown("<hr>", unsafe_allow_html=True)

    # (E) notes
    st.markdown('<div class="section-label">Reviewer notes</div>', unsafe_allow_html=True)
    with st.form(f"note_{app_id}", clear_on_submit=True):
        note = st.text_area("Add a note", placeholder="Observation for the record…")
        if st.form_submit_button("Add note") and note.strip():
            db.add_note(conn, app_id, _user()["user_id"], note.strip())
            _audit("note_add", entity_type="application", entity_id=app_id)
            st.rerun()
    for nt in db.list_notes(conn, app_id):
        st.markdown(f"- _{nt['created_at']}_ · **{nt['display_name']}**: {nt['body']}")

    st.markdown("<hr>", unsafe_allow_html=True)

    # (F) decision — neutral, none pre-selected, rationale required
    st.markdown('<div class="section-label">Record a decision</div>', unsafe_allow_html=True)
    last = db.latest_decision(conn, app_id)
    if last:
        st.caption(f"Most recent decision on file: **{last['decision_value']}** "
                   f"({last['created_at']}). Recording a new one appends, never overwrites.")
    labels = [lbl for _, lbl in DECISION_OPTIONS]
    choice = st.radio("Decision", labels, index=None, horizontal=True, key=f"dec_choice_{app_id}",
                      help="No option is pre-selected. You decide.")
    rationale = st.text_area("Rationale (required)", key=f"dec_rationale_{app_id}",
                             placeholder="Briefly, why this decision given the evidence above…")
    if st.button("Record decision", type="primary", key=f"dec_submit_{app_id}"):
        if not choice:
            st.error("Select a decision before recording it.")
        elif not rationale.strip():
            st.error("A short rationale is required — it creates the audit trail.")
        else:
            value = next(v for v, lbl in DECISION_OPTIONS if lbl == choice)
            snapshot = [{"key": r.key, "value": r.value, "confidence": r.confidence} for r in results]
            db.add_decision(conn, app_id, _user()["user_id"], value, rationale.strip(), snapshot)
            _audit("decision_record", entity_type="application", entity_id=app_id,
                   detail={"decision": value})
            st.success("Decision recorded. It is logged with your name, the time, and the "
                       "evidence state you saw.")


# ---------------------------------------------------------------------------
# Decision history
# ---------------------------------------------------------------------------
def history_page():
    inject_css()
    conn = get_conn()
    u = _user()
    st.markdown("### Decision history")
    is_oversight = u["role"] in ("manager", "governance", "admin")
    if is_oversight:
        st.caption("Oversight view — all reviewers' decisions, append-only and auditable.")
        decs = db.list_decisions(conn)
    else:
        st.caption("Your recorded decisions.")
        decs = db.list_decisions(conn, user_id=u["user_id"])
    if not decs:
        st.info("No decisions recorded yet.")
        return
    df = pd.DataFrame([{
        "When": d["created_at"], "Applicant": d["applicant_id"], "Programme": d["programme_code"],
        "Decision": d["decision_value"], "Reviewer": d["display_name"], "Rationale": d["rationale"],
    } for d in decs])
    st.dataframe(df, width="stretch", hide_index=True)
    if is_oversight:
        missing = sum(1 for d in decs if not d["rationale"].strip())
        st.metric("Decisions with a rationale", f"{len(decs) - missing}/{len(decs)}")


# ---------------------------------------------------------------------------
# Analytics / fairness  (non-ranking aggregates)
# ---------------------------------------------------------------------------
def analytics_page():
    inject_css(); inject_insights_css()
    conn = get_conn()
    st.markdown("### Indicators & fairness")
    st.caption("This page describes the **cohort and the indicators**, to detect disparities. "
               "It does not rank or compare individual applicants, and small groups are suppressed.")

    c1, c2 = st.columns(2)
    prog = c1.selectbox("Programme", ["All"] + list(PROGRAMMES.values()))
    prog_code = next((k for k, v in PROGRAMMES.items() if v == prog), None)
    country = c2.selectbox("Country", ["All"] + db.distinct_countries(conn))
    data = load_insights_cached(
        conn, programme_code=prog_code, country=None if country == "All" else country)
    if data.n == 0 or data.eval_wide.empty:
        st.info("No indicator evaluations for this selection yet.")
        return
    df, ew = data.df, data.eval_wide

    # ============================ FAIRNESS & DISTRIBUTION MONITORING ============================
    section_header("Fairness & distribution monitoring",
                   "Break an indicator down by group to spot patterns worth investigating.")
    st.markdown("This section is for **transparency**, not automated judgement. It surfaces "
                "distribution differences so a human can decide whether they warrant a closer look.")
    rag_indicators = {
        "Academic Performance": "academic_performance",
        "English Requirement": "english_requirement",
        "Quantitative Readiness": "quantitative_readiness",
        "Programme Prerequisites": "programme_prerequisites",
        "Graduation Recency": "graduation_recency",
        "Document Completeness": "document_completeness",
    }
    group_cols = {"Country": "country_name", "Institution type": "tier_label",
                  "Gender": "gender", "Subject area": "subject_name"}
    fc1, fc2 = st.columns(2)
    ind_label = fc1.selectbox("Indicator", list(rag_indicators), key="fair_ind")
    grp_label = fc2.selectbox("Break down by", list(group_cols), key="fair_grp")
    ind_key, grp_col = rag_indicators[ind_label], group_cols[grp_label]

    longdf, suppressed = insights.crosstab_rag(df, ew, grp_col, ind_key, min_n=12)
    if longdf.empty:
        st.info("Not enough data in any group (after small-group suppression) to break this down.")
    else:
        st.altair_chart(_stacked(longdf, grp_col), use_container_width=True)
        concern = (longdf[longdf["colour"].isin(["red", "amber"])]
                   .groupby(grp_col)["pct"].sum().sort_values(ascending=False))
        hi = concern.index[0] if len(concern) else None
        narrative(
            (f"For {ind_label}, '{hi}' shows the highest combined red/amber share "
             f"({round(concern.iloc[0], 1)}%) among groups large enough to show."
             if hi is not None else "Distribution shown by group."),
            why="Persistent skews in an indicator across a group can indicate a data issue, a "
                "recruitment-pipeline effect, or a threshold that lands unevenly — all worth a human look.",
            unusual="")
        limitations("Groups smaller than 12 are hidden to avoid noise and re-identification. "
                    "Shares are descriptive, not causal.")
        st.markdown('<div class="reco">⚠️ <b>Important.</b> Observed differences do <b>not</b> '
                    'imply bias or unfairness. Group sizes, subject mix, and evidence completeness '
                    'all differ; treat any pattern as a prompt to investigate, never as a conclusion.'
                    '</div>', unsafe_allow_html=True)
        if suppressed:
            limitations(f"Groups too small to show: {', '.join(map(str, suppressed[:8]))}"
                        + (" …" if len(suppressed) > 8 else ""))

    # institution-tier monitoring is a stated project concern — always surface it
    tier_long, tier_supp = insights.crosstab_rag(df, ew, "tier_label", "academic_performance", min_n=12)
    if not tier_long.empty:
        st.markdown("**Academic Performance by institution type** (prestige-bias watch)")
        st.altair_chart(_stacked(tier_long, "tier_label"), use_container_width=True)
        narrative(
            "Academic Performance colours split across institution categories.",
            why="Because institution prestige is deliberately excluded from scoring, this view lets "
                "governance check that outcomes aren't tracking institution type through a back door.",
            unusual="")
        st.markdown('<div class="reco">⚠️ <b>Important.</b> A difference here is expected to some '
                    'degree and does not imply bias — it is a monitoring signal, not a verdict.</div>',
                    unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Thresholds (editable, versioned)
# ---------------------------------------------------------------------------
WE_MODE_LABELS = {"neutral": "Neutral (context only)", "rag": "Red/Amber/Green"}


def thresholds_page():
    inject_css()
    conn = get_conn()
    st.markdown("### Threshold configuration")
    st.caption("Adjust the rules behind each indicator, per programme. Saving creates a "
               "**new version** (the old one is closed, never overwritten), so any past "
               "decision can still be replayed against the rules in force at the time. "
               "Institution Context stays neutral and is not configurable by design.")

    tabs = st.tabs([f"{name}  ·  {code}" for code, name in PROGRAMMES.items()])
    for tab, code in zip(tabs, PROGRAMMES.keys()):
        with tab:
            _threshold_editor(conn, code)

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("**Apply changes to the cohort analytics**")
    st.caption("The applicant view always uses the latest thresholds. The Indicators & "
               "fairness charts use a cached evaluation of the whole cohort — recompute it "
               "after changing thresholds so the charts reflect the new rules.")
    if st.button("Recompute all indicator evaluations", key="recompute_thresholds"):
        with st.spinner("Re-evaluating the cohort with current thresholds…"):
            n = services.recompute_all_evaluations(conn)
        _audit("recompute_evaluations", detail={"applications": n})
        st.success(f"Recomputed evaluations for {n} applications.")

    with st.expander("Version history"):
        rows = db.threshold_history(conn)
        st.dataframe(pd.DataFrame([{
            "Programme": r["programme_code"], "Indicator": r["name"], "Rule": r["rule_json"],
            "Version": r["version"], "From": r["effective_from"],
            "To": r["effective_to"] or "current"} for r in rows]),
            width="stretch", hide_index=True)


def _threshold_editor(conn, code):
    cur = db.current_thresholds(conn, code)
    ap = cur.get("academic_performance", {}).get("rule", {"green_min": 65, "amber_min": 55})
    gr = cur.get("graduation_recency", {}).get("rule", {"green_max": 3, "amber_max": 8})
    dc = cur.get("document_completeness", {}).get("rule", {"amber_missing": 1, "red_missing": 2})
    qr = cur.get("quantitative_readiness", {}).get("rule", {})
    we = cur.get("work_experience", {}).get("rule", {})
    we_mode = we.get("work_experience_mode", "neutral" if code == "BA" else "rag")

    with st.form(f"thr_{code}"):
        st.markdown("**Academic Performance** (Irish-equivalent %)")
        c1, c2 = st.columns(2)
        ap_green = c1.number_input("Green at or above", 0, 100, int(ap["green_min"]), key=f"apg_{code}")
        ap_amber = c2.number_input("Amber at or above", 0, 100, int(ap["amber_min"]), key=f"apa_{code}")

        st.markdown("**Graduation Recency** (years since graduation)")
        c3, c4 = st.columns(2)
        gr_green = c3.number_input("Green at or below", 0, 30, int(gr["green_max"]), key=f"grg_{code}")
        gr_amber = c4.number_input("Amber at or below", 0, 30, int(gr["amber_max"]), key=f"gra_{code}")

        st.markdown("**Document Completeness** (number of key fields missing)")
        c5, c6 = st.columns(2)
        dc_amber = c5.number_input("Amber when missing", 0, 3, int(dc["amber_missing"]), key=f"dca_{code}")
        dc_red = c6.number_input("Red when missing at least", 1, 3, int(dc["red_missing"]), key=f"dcr_{code}")

        qgrade = None
        if "quant_green_grade_min" in qr or code == "BA":
            st.markdown("**Quantitative Readiness** (grade needed for green on a high-quant subject)")
            qgrade = st.number_input("Green grade minimum", 0, 100,
                                     int(qr.get("quant_green_grade_min", 60)), key=f"qg_{code}")

        st.markdown("**Work Experience** treatment for this programme")
        we_choice = st.radio("How should work experience be shown?",
                             list(WE_MODE_LABELS.keys()),
                             format_func=lambda k: WE_MODE_LABELS[k],
                             index=list(WE_MODE_LABELS).index(we_mode), horizontal=True,
                             key=f"we_{code}")

        saved = st.form_submit_button(f"Save {code} thresholds (new version)")

    if saved:
        if ap_amber > ap_green:
            st.error("Academic amber threshold can't be higher than green."); return
        if gr_amber < gr_green:
            st.error("Recency amber (years) can't be lower than green."); return
        if dc_red < dc_amber:
            st.error("Document-completeness red count can't be lower than amber."); return
        changes = {}
        if {"green_min": ap_green, "amber_min": ap_amber} != ap:
            changes["academic_performance"] = {"green_min": ap_green, "amber_min": ap_amber}
        if {"green_max": gr_green, "amber_max": gr_amber} != gr:
            changes["graduation_recency"] = {"green_max": gr_green, "amber_max": gr_amber}
        if {"amber_missing": dc_amber, "red_missing": dc_red} != dc:
            changes["document_completeness"] = {"amber_missing": dc_amber, "red_missing": dc_red}
        if qgrade is not None and qr.get("quant_green_grade_min") != qgrade:
            changes["quantitative_readiness"] = {"quant_green_grade_min": qgrade}
        if we_mode != we_choice:
            changes["work_experience"] = {"work_experience_mode": we_choice}
        if not changes:
            st.info("No changes to save.")
        else:
            n = services.update_thresholds(conn, code, changes, _user()["user_id"])
            st.success(f"Saved {n} new threshold version(s) for {code}. The applicant view "
                       f"uses them immediately; recompute below to update the fairness charts.")


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------
def admin_page():
    inject_css()
    conn = get_conn()
    st.markdown("### Administration")
    st.markdown("**Users & roles**")
    users = db.list_users(conn)
    st.dataframe(pd.DataFrame([{
        "Username": u["username"], "Name": u["display_name"], "Role": u["role"],
        "Active": bool(u["is_active"])} for u in users]),
        width="stretch", hide_index=True)
    st.markdown("**Recent activity (audit log)**")
    audit = db.list_audit(conn, limit=200)
    st.dataframe(pd.DataFrame([{
        "When": a["created_at"], "User": a["display_name"], "Action": a["action"],
        "Entity": a["entity_type"], "Id": a["entity_id"]} for a in audit]),
        width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Applicant data — add records within the dashboard
# ---------------------------------------------------------------------------
GENDERS = ["Female", "Male", "Non-binary"]
WORK_OPTIONS = ["No experience", "Internships", "1-2 years", "3+ years"]
ENGLISH_OPTIONS = ["High", "Moderate", "Low", "Not on file yet"]


def data_page():
    inject_css()
    conn = get_conn()
    st.markdown("### Applicant data")
    st.caption(f"Cohort size: **{db.cohort_size(conn)}** applicants. "
               "Add records here and they appear in the work queue immediately, "
               "with indicators computed on save.")

    tab_one, tab_bulk = st.tabs(["Add one applicant", "Upload a CSV"])

    # ---- single applicant ----
    with tab_one:
        from .countries import COUNTRY_NAMES
        tiers = db.list_tiers(conn)                   # [(code, label)]
        subjects = db.list_subjects(conn)
        default_country = COUNTRY_NAMES.index("Ireland") if "Ireland" in COUNTRY_NAMES else 0
        with st.form("add_applicant", clear_on_submit=True):
            c1, c2 = st.columns(2)
            forename = c1.text_input("Forename")
            surname = c2.text_input("Surname")
            c3, c4, c5 = st.columns(3)
            country = c3.selectbox("Country", COUNTRY_NAMES, index=default_country)
            nationality = c4.selectbox("Nationality", COUNTRY_NAMES, index=default_country)
            gender = c5.selectbox("Gender", GENDERS)
            c6, c7 = st.columns(2)
            age = c6.number_input("Age", 20, 45, 24)
            programme = c7.selectbox("Target programme", list(PROGRAMMES.keys()),
                                     format_func=lambda k: f"{PROGRAMMES[k]} ({k})")
            c8, c9 = st.columns([2, 1])
            institution = c8.text_input("Institution name")
            tier = c9.selectbox("Institution type", [t for t, _ in tiers],
                                format_func=lambda t: dict(tiers)[t])
            c10, c11 = st.columns(2)
            subject = c10.selectbox("Subject area", subjects)
            grad_year = c11.number_input("Graduation year", 2014, 2026, 2025)
            c12, c13 = st.columns(2)
            has_grade = c12.checkbox("Grade on file", value=True)
            grade = c12.number_input("Grade (Irish eq. %)", 0.0, 100.0, 62.0, disabled=not has_grade)
            english = c13.selectbox("English level", ENGLISH_OPTIONS)
            c14, c15 = st.columns(2)
            work = c14.selectbox("Work experience", WORK_OPTIONS)
            yrs = c15.number_input("Years' experience", 0, 30, 0)
            submitted = st.form_submit_button("Add applicant", type="primary")

        if submitted:
            if not forename.strip() or not surname.strip() or not institution.strip():
                st.error("Forename, surname, and institution are required.")
            else:
                data = dict(
                    applicant_id=db.next_applicant_id(conn),
                    surname=surname.strip(), forename=forename.strip(),
                    country_name=country, nationality_name=nationality, age=int(age),
                    gender=gender, institution_name=institution.strip(), tier_code=tier,
                    subject_name=subject, graduation_year=int(grad_year),
                    grade_irish_eq=float(grade) if has_grade else None,
                    english_level=None if english == "Not on file yet" else english,
                    work_experience=work, years_experience=int(yrs),
                    programme_code=programme)
                app_id = services.add_student(conn, data, _user()["user_id"])
                st.success(f"Added **{data['applicant_id']}** to {programme}. "
                           f"It's now in the work queue (application #{app_id}).")

    # ---- bulk CSV ----
    with tab_bulk:
        st.markdown("Upload a CSV with the same columns as the synthetic corpus "
                    "(`applicants.csv`). Each row becomes an applicant + application.")
        st.caption("Required columns: Surname, Forename, Country, Age, Gender, Nationality, "
                   "Institution, Further info on institution, Subject area, Graduation Year, "
                   "Grade (Irish eq.), English, Work Experience, Years' experience. "
                   "Country and Subject area must match existing values.")
        assign = st.radio("Assign uploaded applicants to", ["alternate", "BA", "IM"],
                          format_func=lambda x: {"alternate": "Alternate BA / IM",
                                                 "BA": "All to BA", "IM": "All to IM"}[x],
                          horizontal=True)
        up = st.file_uploader("CSV file", type="csv")
        if up is not None and st.button("Append from CSV", type="primary"):
            added, errors = services.bulk_add_from_csv(conn, up.getvalue(), assign,
                                                       _user()["user_id"])
            if added:
                st.success(f"Added {added} applicant(s).")
            if errors:
                st.warning(f"{len(errors)} row(s) skipped:")
                st.code("\n".join(errors[:50]))
            if not added and not errors:
                st.info("No rows found in the file.")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def settings_page():
    inject_css()
    st.markdown("### Settings")
    st.caption("Personal display preferences for this session.")
    st.toggle("High-contrast / mono indicator palette", key="high_contrast",
              help="Indicators always pair colour with an icon and word, so they remain "
                   "legible without colour. This toggle is a scaffold for the accessibility option.")
    st.markdown("---")
    u = _user()
    st.write(f"Acting as **{u['display_name']}** — combined review, oversight, "
             f"governance, and admin (no login in this build).")


# ---------------------------------------------------------------------------
# Data Insights — a business-intelligence view of the applicant pool.
# Every panel answers a business question and carries a plain-English narrative.
# All panels respond to the filter bar. No composite scoring or ranking is added.
# ---------------------------------------------------------------------------
def _hbar(d, cat, order=None, xtitle="Share of applicants (%)", color="#0E73B9"):
    return (alt.Chart(d).mark_bar(cornerRadius=3, color=color)
            .encode(x=alt.X("pct:Q", title=xtitle),
                    y=alt.Y(f"{cat}:N", title=None, sort=order or "-x"),
                    tooltip=[alt.Tooltip(f"{cat}:N", title=cat.replace('_', ' ').title()),
                             alt.Tooltip("n:Q", title="Count"),
                             alt.Tooltip("pct:Q", title="%")])
            .properties(width="container", height=max(120, 30 * len(d) + 20)))


def _rag_bar(dist, xtitle="Share (%)"):
    return (alt.Chart(dist).mark_bar(cornerRadius=3)
            .encode(x=alt.X("pct:Q", title=xtitle),
                    y=alt.Y("colour:N", sort=insights.RAG_ORDER, title=None),
                    color=alt.Color("colour:N", legend=None,
                        scale=alt.Scale(domain=list(insights.RAG_COLORS),
                                        range=list(insights.RAG_COLORS.values()))),
                    tooltip=["colour", "n", "pct"])
            .properties(width="container", height=max(110, 30 * len(dist) + 20)))


def _stacked(longdf, group):
    return (alt.Chart(longdf).mark_bar()
            .encode(x=alt.X("n:Q", stack="normalize", title="Share within group",
                            axis=alt.Axis(format="%")),
                    y=alt.Y(f"{group}:N", title=None, sort="-x"),
                    color=alt.Color("colour:N",
                        scale=alt.Scale(domain=list(insights.RAG_COLORS),
                                        range=list(insights.RAG_COLORS.values())),
                        legend=alt.Legend(title="Indicator", orient="bottom")),
                    order=alt.Order("colour:N"),
                    tooltip=[alt.Tooltip(f"{group}:N", title=group.replace('_', ' ').title()),
                             "colour", "n", "pct"])
            .properties(width="container", height=max(140, 34 * longdf[group].nunique() + 40)))


def data_insights_page():
    inject_css(); inject_insights_css()
    conn = get_conn()
    st.markdown("## Data insights")
    st.caption("Applicant-pool analytics for admissions managers and reviewers. Every panel "
               "answers a business question and includes a plain-English read-out, so the page "
               "is usable without interpreting the charts. These are cohort patterns — not "
               "scores or rankings of individuals.")

    # ---------------- Filters (all panels respond) ----------------
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        prog = c1.selectbox("Programme", ["All"] + list(PROGRAMMES.values()), key="ins_prog")
        prog_code = next((k for k, v in PROGRAMMES.items() if v == prog), None)
        country = c2.selectbox("Country", ["All"] + db.distinct_countries(conn), key="ins_country")
        english = c3.selectbox("English", ["All", "High", "Moderate", "Low", "Pending"], key="ins_eng")
        readiness = c4.selectbox("Readiness", ["All", "Ready to review", "Awaiting evidence"], key="ins_ready")
        c5, c6, _ = st.columns(3)
        gy_min = c5.number_input("Graduated from", 2014, 2026, 2014, key="ins_gymin")
        gy_max = c6.number_input("Graduated to", 2014, 2026, 2026, key="ins_gymax")

    data = load_insights_cached(
        conn, programme_code=prog_code,
        country=None if country == "All" else country,
        english=None if english == "All" else english,
        completeness=None if readiness == "All" else readiness,
        grad_year_min=int(gy_min) if gy_min > 2014 else None,
        grad_year_max=int(gy_max) if gy_max < 2026 else None)
    _audit("insights_view", detail={"n": data.n})

    if data.n == 0:
        st.info("No applicants match these filters. Try widening them.")
        return
    df, ew = data.df, data.eval_wide
    n = data.n
    recos = []   # evidence-based observations, surfaced together at the end

    # ============================ EXECUTIVE SUMMARY ============================
    section_header("Executive summary", "The pool at a glance, with a business read on each metric.")
    ready = int((df["readiness"] == "Ready to review").sum())
    awaiting = n - ready
    ready_pct = insights.pct(ready, n)
    decided = int(df["is_decided"].sum())
    complete = int((df["n_missing"] == 0).sum())
    complete_pct = insights.pct(complete, n)
    n_countries = int(df["country_name"].nunique())
    acad_green = insights.green_share(ew, "academic_performance")
    eng_green = insights.colour_share(ew, "english_requirement", "green")

    kpi_row([
        {"label": "Applicant pool", "value": f"{n:,}", "tone": "neutral",
         "sub": "applications in the current view"},
        {"label": "Ready to review", "value": f"{ready_pct}%",
         "tone": "good" if ready_pct >= 70 else ("watch" if ready_pct >= 40 else "bad"),
         "sub": f"{ready} ready · {awaiting} awaiting evidence"},
        {"label": "Decisions recorded", "value": f"{insights.pct(decided, n)}%",
         "tone": "neutral", "sub": f"{decided} of {n} applications decided"},
        {"label": "Complete evidence", "value": f"{complete_pct}%",
         "tone": "good" if complete_pct >= 80 else ("watch" if complete_pct >= 60 else "bad"),
         "sub": "all three key fields present"},
        {"label": "Countries represented", "value": f"{n_countries}", "tone": "neutral",
         "sub": "distinct applicant origins"},
        {"label": "Strong academic (2.1+)", "value": f"{acad_green if acad_green is not None else '—'}%",
         "tone": "neutral", "sub": "green on Academic Performance"},
    ])
    narrative(
        f"Of {n:,} applications in view, {ready_pct}% are ready to review and {complete_pct}% have "
        f"complete evidence. {insights.pct(decided, n)}% have a recorded decision.",
        why="These four numbers tell a manager whether the pool is workable now or blocked on "
            "missing documents, and how much review capacity remains.",
        unusual=(f"{awaiting} applications are awaiting evidence — chasing these early prevents a "
                 f"backlog." if awaiting else ""))
    if awaiting:
        recos.append(f"{awaiting} application(s) are awaiting evidence; request the missing "
                     f"documents before they stall the queue.")

    # ============================ DEMOGRAPHICS ============================
    section_header("Applicant demographics", "Where applicants come from and who they are.")
    colA, colB = st.columns(2)
    with colA:
        ct = insights.share_table(df, "country_name").head(12)
        st.markdown("**Country of origin** (top 12)")
        st.altair_chart(_hbar(ct, "country_name"), use_container_width=True)
        top_country = ct.iloc[0]
        top3 = round(ct.head(3)["pct"].sum(), 1)
        narrative(
            f"The largest origin is {top_country['country_name']} at {top_country['pct']}%; "
            f"the top three make up {top3}% of the pool.",
            why="Origin mix shapes credential-evaluation workload and informs recruitment reach.",
            unusual=("Concentration is high — a few countries dominate."
                     if top3 >= 60 else ""))
        if top_country["pct"] >= 40:
            recos.append(f"{top_country['country_name']} alone is {top_country['pct']}% of the pool; "
                         f"a shift in that single market would swing overall numbers.")
    with colB:
        gt = insights.share_table(df, "gender")
        st.markdown("**Gender**")
        st.altair_chart(_hbar(gt, "gender"), use_container_width=True)
        gtop = gt.iloc[0]
        narrative(
            f"The most common recorded gender is {gtop['gender']} ({gtop['pct']}%).",
            why="Distribution monitoring supports equal-opportunity reporting.",
            unusual="")

    colC, colD = st.columns(2)
    with colC:
        st.markdown("**Age distribution**")
        age_ch = (alt.Chart(df).mark_bar(cornerRadius=2, color="#0E73B9")
                  .encode(x=alt.X("age:Q", bin=alt.Bin(step=2), title="Age"),
                          y=alt.Y("count():Q", title="Applicants"),
                          tooltip=[alt.Tooltip("count():Q", title="Applicants")])
                  .properties(width="container", height=200))
        st.altair_chart(age_ch, use_container_width=True)
        narrative(
            f"Ages run from {int(df['age'].min())} to {int(df['age'].max())}, median "
            f"{int(df['age'].median())}.",
            why="Age hints at how recent and how work-seasoned the cohort is, feeding the "
                "recency and experience indicators.")
    with colD:
        pt = insights.share_table(df, "programme_name")
        st.markdown("**Target programme**")
        st.altair_chart(_hbar(pt, "programme_name"), use_container_width=True)
        narrative(
            "Split of applications across the two MSc programmes in view.",
            why="Programme mix matters because prerequisites, quantitative expectations and the "
                "work-experience treatment all differ by programme.")

    # ============================ ACADEMIC INSIGHTS ============================
    section_header("Academic insights", "Quality and diversity of academic background.")
    colE, colF = st.columns(2)
    with colE:
        gb = insights.share_table(df, "grade_band", order=insights.GRADE_BANDS)
        st.markdown("**Grade band** (Irish equivalent)")
        st.altair_chart(_hbar(gb, "grade_band", order=insights.GRADE_BANDS), use_container_width=True)
        first_21 = round(gb[gb["grade_band"].isin(["First (1.1)", "Upper Second (2.1)"])]["pct"].sum(), 1)
        not_on_file = float(gb[gb["grade_band"] == "Not on file"]["pct"].sum()) if \
            "Not on file" in gb["grade_band"].values else 0.0
        narrative(
            f"{first_21}% sit at 2.1 or above; {not_on_file}% have no grade on file.",
            why="The 2.1 line is the usual academic bar, so this is a quick quality read of the pool.",
            unusual=(f"{not_on_file}% missing a grade will read as lower-confidence across academic "
                     f"indicators." if not_on_file >= 5 else ""))
        if not_on_file >= 8:
            recos.append(f"{not_on_file}% of applicants have no grade recorded — these show as "
                         f"'evidence pending', not weak; collecting grades sharpens the picture.")
    with colF:
        it = insights.share_table(df, "tier_label")
        st.markdown("**Institution context** (neutral — not scored)")
        st.altair_chart(_hbar(it, "tier_label", color="#8B939C"), use_container_width=True)
        narrative(
            "Distribution of awarding-institution categories across the pool.",
            why="Shown for context only. Institution type is deliberately excluded from any "
                "pass/fail logic to avoid prestige and country-of-origin bias.")
        limitations("Institution category is descriptive context, never a quality score.")

    colG, colH = st.columns(2)
    with colG:
        sub = insights.share_table(df, "subject_name").head(12)
        st.markdown("**Subject area** (top 12)")
        st.altair_chart(_hbar(sub, "subject_name"), use_container_width=True)
        qmix = insights.share_table(df, "quant_label")
        high_q = float(qmix[qmix["quant_label"] == "High quant"]["pct"].sum()) if \
            "High quant" in qmix["quant_label"].values else 0.0
        narrative(
            f"Roughly {high_q}% come from highly quantitative fields.",
            why="Quantitative background is central for Business Analytics prerequisites and "
                "readiness; a low share flags a coaching or screening need for that programme.")
    with colH:
        qr = insights.rag_distribution(ew, "quantitative_readiness")
        st.markdown("**Quantitative readiness** (indicator)")
        if not qr.empty:
            st.altair_chart(_rag_bar(qr), use_container_width=True)
            g = insights.green_share(ew, "quantitative_readiness")
            narrative(
                f"{g}% of applications are green on quantitative readiness.",
                why="This is the depth-of-maths signal the reviewer sees; the pool-level share "
                    "tells managers how quantitatively prepared the intake is.")
        else:
            st.caption("No indicator evaluations available for this set.")

    # ============================ EXPERIENCE & READINESS ============================
    section_header("Experience & readiness", "How prepared the pool is beyond grades.")
    colI, colJ = st.columns(2)
    with colI:
        we_order = ["No experience", "Internships", "1-2 years", "3+ years"]
        wt = insights.share_table(df, "work_experience", order=we_order)
        st.markdown("**Work experience**")
        st.altair_chart(_hbar(wt, "work_experience", order=we_order), use_container_width=True)
        exp_any = round(wt[wt["work_experience"] != "No experience"]["pct"].sum(), 1)
        narrative(
            f"{exp_any}% report at least some experience (internships or more).",
            why="Experience is weighted for International Management but supplementary for Business "
                "Analytics, so read this per programme.")
    with colJ:
        df_rec = df.copy()
        df_rec["recency"] = pd.cut(df_rec["years_since_grad"], [-1, 3, 8, 100],
                                   labels=["Recent (≤3y)", "Moderately recent (4–8y)", "Dated (>8y)"])
        rt = insights.share_table(df_rec, "recency",
                                  order=["Recent (≤3y)", "Moderately recent (4–8y)", "Dated (>8y)"])
        st.markdown("**Graduation recency**")
        st.altair_chart(_hbar(rt, "recency",
                        order=["Recent (≤3y)", "Moderately recent (4–8y)", "Dated (>8y)"]),
                        use_container_width=True)
        dated = float(rt[rt["recency"] == "Dated (>8y)"]["pct"].sum()) if \
            "Dated (>8y)" in rt["recency"].astype(str).values else 0.0
        narrative(
            f"{round(100 - dated, 1)}% graduated within eight years.",
            why="Recency proxies currency of knowledge; a large dated share may warrant closer "
                "review of up-to-date competence.",
            unusual=(f"{dated}% graduated more than eight years ago." if dated >= 15 else ""))
    colK, colL = st.columns(2)
    with colK:
        et = insights.share_table(df, "english_level", order=["High", "Moderate", "Low"])
        st.markdown("**English proficiency**")
        st.altair_chart(_hbar(et, "english_level", order=["High", "Moderate", "Low", "Not recorded"]),
                        use_container_width=True)
        pending_eng = float(et[et["english_level"] == "Not recorded"]["pct"].sum()) if \
            "Not recorded" in et["english_level"].values else 0.0
        narrative(
            f"{pending_eng}% have no English level on file yet.",
            why="English is a hard gate for teaching and assessment; pending cases should be "
                "resolved before a final decision.")
        if pending_eng >= 8:
            recos.append(f"{pending_eng}% lack English evidence — request it early to unblock reviews.")
    with colL:
        ec = insights.rag_distribution(ew, "evidence_confidence")
        st.markdown("**Evidence confidence** (meta-signal)")
        if not ec.empty:
            st.altair_chart(_rag_bar(ec), use_container_width=True)
            narrative(
                "How much of the pool rests on strong vs sparse evidence.",
                why="This is about data quality, not applicant quality — it tells reviewers how "
                    "much to trust the other indicators for each case.")
        else:
            st.caption("No indicator evaluations available for this set.")

    # ============================ DECISION / RECOMMENDATION OVERVIEW ============================
    section_header("Decision & recommendation overview",
                   "Human decisions recorded in the tool, and how the pool looks pre-decision.")
    if not data.df_dec.empty:
        dd = data.df_dec["decision_value"].map(
            {"offer": "Recommend offer", "reject": "Recommend reject",
             "more_info": "Request more info", "defer": "Defer"}).fillna(data.df_dec["decision_value"])
        dt = dd.value_counts().rename_axis("decision").reset_index(name="n")
        dt["pct"] = dt["n"].apply(lambda x: insights.pct(x, dt["n"].sum()))
        st.markdown("**Recorded reviewer decisions**")
        st.altair_chart(_hbar(dt, "decision"), use_container_width=True)
        top_dec = dt.iloc[0]
        narrative(
            f"Among recorded decisions, the most common is '{top_dec['decision']}' ({top_dec['pct']}%).",
            why="These are real human decisions logged in the tool — the closest thing to an "
                "outcome distribution, and the basis for any calibration work.",
            unusual="Decision counts are still small; treat proportions as indicative." )
    else:
        st.info("No reviewer decisions have been recorded for this set yet. As reviewers record "
                "decisions, their distribution and relationship to the indicators will appear here.")
        st.markdown("**Pre-decision readiness signal** — Academic Performance vs Document Completeness")
        ap = insights.rag_distribution(ew, "academic_performance")
        dc = insights.rag_distribution(ew, "document_completeness")
        cc1, cc2 = st.columns(2)
        if not ap.empty:
            cc1.altair_chart(_rag_bar(ap, "Academic Performance"), use_container_width=True)
        if not dc.empty:
            cc2.altair_chart(_rag_bar(dc, "Document Completeness"), use_container_width=True)
        narrative(
            "Until decisions accumulate, these two indicators best describe how the pool looks "
            "going into review: academic strength and whether the evidence base is complete.",
            why="Managers can gauge likely workload — a pool that is strong academically but "
                "incomplete on documents means chase-ups, not rejections.")

    with st.expander("Legacy heuristic label (not shown to reviewers · not used in decisions)"):
        st.caption("A rule-of-thumb label carried in the source data. It is deliberately hidden "
                   "from the reviewer workflow to avoid anchoring, and is shown here only to "
                   "monitor the pool and sanity-check the indicators. It is never a decision.")
        if "baseline_label" in df.columns and df["baseline_label"].notna().any():
            bl = insights.share_table(df, "baseline_label")
            st.altair_chart(_hbar(bl, "baseline_label", color="#8B939C"), use_container_width=True)
            # relationship to academic band (the task's example narrative)
            tmp = df.dropna(subset=["baseline_label"]).copy()
            cross = (tmp.groupby(["grade_band", "baseline_label"]).size().reset_index(name="n"))
            heat = (alt.Chart(cross).mark_rect().encode(
                x=alt.X("baseline_label:N", title="Legacy label"),
                y=alt.Y("grade_band:N", title="Grade band", sort=insights.GRADE_BANDS),
                color=alt.Color("n:Q", title="Applicants", scale=alt.Scale(scheme="blues")),
                tooltip=["grade_band", "baseline_label", "n"]).properties(width="container", height=220))
            st.altair_chart(heat, use_container_width=True)
            narrative(
                "Stronger grade bands concentrate in the more positive legacy labels, but some "
                "high-grade applicants still sit in the cautious labels.",
                why="This is exactly why the tool decomposes evidence into independent indicators "
                    "rather than a single label — non-academic factors move cases the headline label "
                    "would miss.",
                unusual="Any high-grade applicant in a cautious legacy label is worth a closer, "
                        "evidence-led look.")
        else:
            st.caption("No legacy labels are present in this set.")

    # ============================ DATA QUALITY ============================
    section_header("Data quality", "Completeness and consistency of the underlying records.")
    miss = pd.DataFrame({
        "field": ["Grade", "English evidence", "Institution detail"],
        "n": [int(df["grade_irish_eq"].isna().sum()),
              int(df["english_level"].isna().sum() + (df["english_level"] == "").sum()),
              int(df["institution_tier"].isna().sum() + (df["institution_tier"] == "").sum())],
    })
    miss["pct"] = miss["n"].apply(lambda x: insights.pct(x, n))
    colM, colN = st.columns(2)
    with colM:
        st.markdown("**Missing key fields**")
        st.altair_chart(_hbar(miss, "field", color="#C44B5B"), use_container_width=True)
        worst = miss.sort_values("n", ascending=False).iloc[0]
        narrative(
            f"The most-missing field is {worst['field']} ({worst['pct']}%).",
            why="Missing fields don't count against applicants — indicators show 'evidence "
                "pending' — but they cap confidence and slow decisions, so they matter operationally.",
            unusual="")
    with colN:
        comp = df["n_missing"].value_counts().rename_axis("n_missing").reset_index(name="n").sort_values("n_missing")
        comp["label"] = comp["n_missing"].map({0: "Complete", 1: "1 field missing", 2: "2 missing", 3: "3 missing"})
        comp["pct"] = comp["n"].apply(lambda x: insights.pct(x, n))
        st.markdown("**Record completeness**")
        st.altair_chart(_hbar(comp, "label"), use_container_width=True)
        narrative(
            f"{complete_pct}% of records are fully complete.",
            why="Completeness is the routing signal: complete records can be decided now; "
                "incomplete ones need evidence first.")

    # consistency checks
    exp_years = {"No experience": (0, 0), "Internships": (0, 1), "1-2 years": (1, 2), "3+ years": (3, 99)}
    def _exp_ok(r):
        lo, hi = exp_years.get(r["work_experience"], (0, 99))
        return lo <= (r["years_experience"] or 0) <= hi
    exp_flags = int((~df.apply(_exp_ok, axis=1)).sum())
    grade_flags = int(((df["grade_irish_eq"] < 0) | (df["grade_irish_eq"] > 100)).sum())
    age_flags = int((df["years_experience"] > (df["age"] - 16)).sum())
    checks = pd.DataFrame({
        "Consistency check": ["Grade within 0–100",
                              "Experience category matches logged years",
                              "Logged experience plausible for age"],
        "Flagged records": [grade_flags, exp_flags, age_flags],
        "Status": ["OK" if grade_flags == 0 else "Review",
                   "OK" if exp_flags == 0 else "Review",
                   "OK" if age_flags == 0 else "Review"]})
    st.markdown("**Consistency checks**")
    st.dataframe(checks, width="stretch", hide_index=True)
    total_flags = grade_flags + exp_flags + age_flags
    narrative(
        ("All consistency checks pass." if total_flags == 0
         else f"{total_flags} record(s) flagged for a closer look."),
        why="Automated sanity checks catch data-entry issues before they mislead a reviewer.")
    if exp_flags:
        recos.append(f"{exp_flags} record(s) have a work-experience category that disagrees with the "
                     f"logged years — verify the source data.")
    if age_flags:
        recos.append(f"{age_flags} record(s) log more experience than is plausible for the applicant's "
                     f"age — check for entry errors.")

    st.caption("Distribution-fairness monitoring for the indicators lives on the "
               "**Indicators & fairness** page (Oversight & governance).")

    # ============================ RECOMMENDATIONS ============================
    section_header("Observations & recommendations",
                   "Evidence-based prompts — separate from the factual insights above.")
    if recos:
        for r in recos:
            recommendation(r)
    else:
        st.success("No data-quality or readiness concerns stood out for the current selection.")
    st.caption("Recommendations are operational prompts derived from the current view. They are "
               "advisory and never substitute for reviewer judgement.")


# ---------------------------------------------------------------------------
# School verification — which college/school under the declared university
# ---------------------------------------------------------------------------
def _sv_badge(confidence, corroborated):
    """Confidence badge using the evidence-quality (grey) scale — advisory, not RAG."""
    if confidence >= 90 and corroborated:
        key, label = "strong", f"Strong evidence · {confidence:.0f}% · corroborated"
    elif confidence >= 80:
        key, label = "partial", f"Partial evidence · {confidence:.0f}%"
    else:
        key, label = "sparse", f"Sparse evidence · {confidence:.0f}%"
    p = PALETTE[key]
    return (f'<span style="background:{p["bg"]};color:{p["fg"]};'
            f'border:1px solid {p["border"]};border-radius:12px;'
            f'padding:2px 10px;font-size:0.85rem;">{p["icon"]} {label}</span>')


def school_verification_page():
    from .school_reference import school_names_for, university_names
    from . import school_service as SV
    inject_css()
    conn = get_conn()
    db.ensure_school_schema(conn)

    st.markdown("### School verification")
    st.caption("Applicants often declare only the parent university (e.g. “University of "
               "Delhi”). This tool reads the **transcript** to propose the specific "
               "college/school, shows the exact evidence, and records your confirmation. "
               "The suggestion is advisory — you make the call.")

    tab_run, tab_queue = st.tabs(["Run detection", "Verification queue"])

    # ---------------- Run detection ----------------
    with tab_run:
        st.markdown('<div class="section-label">Upload applicant documents</div>',
                    unsafe_allow_html=True)
        st.caption("Upload one applicant's PDFs — or a whole batch: files are grouped "
                   "by the applicant prefix in the filename (e.g. `APP-001_…`). The "
                   "transcript is the authoritative source; the academic reference only "
                   "corroborates. The CV is never used to determine the school.")
        uploads = st.file_uploader("PDF documents", type=["pdf"], accept_multiple_files=True)
        declared = st.text_input(
            "Declared university (optional — leave blank to auto-detect from the transcript)",
            placeholder="e.g. University of Delhi")

        if uploads and st.button("Run detection", type="primary"):
            grouped = SV.group_uploads([(u.name, u.getvalue()) for u in uploads])
            for app_key, docs in sorted(grouped.items()):
                ver_id, det = SV.run_verification(
                    conn, app_key, docs, declared or None, _user()["user_id"])
                st.session_state.setdefault("sv_last_run", []).append(ver_id)
            st.success(f"Detection run for {len(grouped)} applicant(s). "
                       "Review and confirm below.")
            st.rerun()

        pending = db.list_school_verifications(conn, status="pending")
        if pending:
            st.markdown('<div class="section-label">Pending confirmation</div>',
                        unsafe_allow_html=True)
        for row in pending:
            _sv_review_card(conn, row, school_names_for, university_names)

    # ---------------- Queue / history ----------------
    with tab_queue:
        rows = db.list_school_verifications(conn)
        if not rows:
            st.info("No verifications yet.")
            return
        df = pd.DataFrame([{
            "Applicant": r["applicant_id"],
            "University": r["detected_university"] or r["declared_university"] or "—",
            "Detected school": r["detected_school"] or "—",
            "Confidence": f'{(r["confidence"] or 0):.0f}%',
            "Source": {"transcript": "Transcript",
                       "reference_academic": "Academic reference"}.get(
                           r["source_document"], "—"),
            "Corroborated": "Yes" if r["corroborated"] else "—",
            "Verified as": r["verified_school"] or "—",
            "Status": r["status"],
            "By": r["verified_by_name"] or "—",
            "At": r["verified_at"] or "—",
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)


def _sv_review_card(conn, row, school_names_for, university_names):
    from . import school_service as SV
    ver_id = row["verification_id"]
    with st.container(border=True):
        head = f"**{row['applicant_id']}** · {row['detected_university'] or row['declared_university'] or 'university unknown'}"
        st.markdown(head)
        if row["detected_school"]:
            st.markdown(
                f"Detected school: **{row['detected_school']}** &nbsp; "
                + _sv_badge(row["confidence"] or 0, row["corroborated"]),
                unsafe_allow_html=True)
            src = {"transcript": "transcript",
                   "reference_academic": "academic reference"}.get(row["source_document"])
            if row["evidence_snippet"]:
                st.markdown(f"Evidence — {src}, page {row['source_page']}:")
                st.info(row["evidence_snippet"])
        else:
            st.warning("No school detected — confirm manually from the documents.")
        if row["university_mismatch"]:
            st.error("Declared university and the university on the transcript disagree "
                     "— check for a typo or a wrong document before confirming.")
        if row["notes"]:
            st.caption(row["notes"])

        uni = row["detected_university"] or row["declared_university"]
        options = school_names_for(uni)
        if not options:
            st.caption("This university is not in the reference catalogue yet — add its "
                       "schools in `src/school_reference.py`, then re-run detection.")
            return
        default = row["detected_school"] if row["detected_school"] in options else None
        idx = options.index(default) if default else None
        c1, c2 = st.columns([3, 1])
        chosen = c1.selectbox("Confirm or correct the school", options,
                              index=idx, key=f"sv_choice_{ver_id}",
                              placeholder="Select the school…")
        if c2.button("Record", type="primary", key=f"sv_btn_{ver_id}",
                     disabled=chosen is None):
            status = SV.confirm_school(conn, ver_id, row["detected_school"],
                                       chosen, _user()["user_id"])
            st.success(f"Recorded as **{status}** → {chosen}. Logged with your name and time.")
            st.rerun()


# ---------------------------------------------------------------------------
# Predictive analytics (research track) — NEVER operational
# ---------------------------------------------------------------------------
def predictive_analytics_page():
    inject_css()
    conn = get_conn()
    db.ensure_ml_schema(conn)

    st.markdown("### Predictive analytics (research)")
    st.warning("**Research track only.** These models exist for the dissertation's "
               "calibration and fairness evaluation (see `PREREGISTRATION_ML.md`). "
               "Predictions are never shown in the review workflow, never written to "
               "indicator evaluations, and never aggregated into the advisory chips — "
               "that separation is enforced by automated tests.")

    run = db.latest_ml_run(conn)
    if st.button("Run pre-registered experiment", type="primary"):
        from src.ml.service import run_experiment
        with st.spinner("Training, calibrating, explaining, auditing…"):
            run_experiment(conn, _user()["user_id"])
        st.rerun()
    if not run:
        st.info("No experiment run recorded yet.")
        return

    res = json.loads(run["results_json"])
    st.caption(f"Run #{run['run_id']} · {run['created_at']} · seed {run['seed']} · "
               f"data hash `{run['data_hash']}` · target: {run['target_def']} · "
               f"train n={run['n_train']}, test n={run['n_test']}")

    # ---- pre-registered metrics table ----
    st.markdown('<div class="section-label">Calibration metrics (held-out test set)</div>',
                unsafe_allow_html=True)
    st.caption(f"Climatological Brier baseline (always predict base rate): "
               f"**{res['climatological_brier']:.4f}**. "
               f"Selected model (lower calibrated Brier): **{run['selected_model']}**.")
    rows = []
    for name, m in res["models"].items():
        rows.append({"Model": name,
                     "Brier (uncal → cal)": f"{m['brier_uncal']:.4f} → {m['brier_cal']:.4f}",
                     "ECE (uncal → cal)": f"{m['ece_uncal']:.4f} → {m['ece_cal']:.4f}",
                     "AUC (uncal → cal)": f"{m['auc_uncal']:.3f} → {m['auc_cal']:.3f}",
                     "Beats baseline": "✓" if m["passes"]["brier_beats_climatology"] else "✕",
                     "ECE ≤ 0.08": "✓" if m["passes"]["ece_within_0.08"] else "✕",
                     "AUC preserved": "✓" if m["passes"]["auc_not_degraded"] else "✕"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    sel = res["models"][run["selected_model"]]

    # ---- reliability diagram ----
    st.markdown('<div class="section-label">Reliability diagram — selected model</div>',
                unsafe_allow_html=True)
    rel = pd.concat([pd.DataFrame(sel["reliability_uncal"]).assign(variant="Uncalibrated"),
                     pd.DataFrame(sel["reliability_cal"]).assign(variant="Calibrated (Platt)")])
    diag = pd.DataFrame({"x": [0, 1], "y": [0, 1]})
    chart = (alt.Chart(rel).mark_line(point=True).encode(
                x=alt.X("mean_predicted:Q", title="Mean predicted probability",
                        scale=alt.Scale(domain=[0, 1])),
                y=alt.Y("observed_rate:Q", title="Observed frequency",
                        scale=alt.Scale(domain=[0, 1])),
                color=alt.Color("variant:N", title=None),
                tooltip=["variant", "mean_predicted", "observed_rate", "count"])
             + alt.Chart(diag).mark_line(strokeDash=[4, 4], color="#9AA0A6")
                  .encode(x="x:Q", y="y:Q"))
    st.altair_chart(chart, use_container_width=True)
    st.caption("Dashed line = perfect calibration. Points below the line mean "
               "over-confidence; above means under-confidence. Bin counts in tooltip — "
               "small bins are noisy at this N.")

    # ---- SHAP ----
    st.markdown('<div class="section-label">Per-facet explanation — mean |SHAP| '
                '(selected model, test set)</div>', unsafe_allow_html=True)
    shap_df = pd.DataFrame(sel["shap"])
    st.altair_chart(alt.Chart(shap_df).mark_bar(color="#0E73B9").encode(
        x=alt.X("mean_abs_shap:Q", title="Mean |SHAP| contribution"),
        y=alt.Y("feature:N", sort="-x", title=None)), use_container_width=True)
    st.caption("Feature attributions corroborate the rule-based facets: grade and "
               "English dominate, mirroring the advisory indicators — evidence that the "
               "rules engine and the learnt model agree on what matters.")

    # ---- fairness audit ----
    st.markdown('<div class="section-label">Pre-registered fairness audit '
                '(selected calibrated model)</div>', unsafe_allow_html=True)
    fa = res["fairness"]
    st.caption(f"Audit flag rule: top-q of test predictions, q = train base rate → "
               f"threshold {fa['threshold']:.3f}, flagged share {fa['flag_share']:.1%}. "
               f"Disparate-impact criterion: ratio in [0.80, 1.25], groups with n ≥ 30.")
    fdf = pd.DataFrame([{
        "Dimension": g["dimension"], "Group": g["group"], "n (test)": g["n"],
        "Selection rate": f"{g['selection_rate']:.1%}",
        "DI ratio": f"{g['di_ratio']:.2f}" if g.get("di_ratio") is not None else "—",
        "Criterion": ("Pass" if g.get("di_pass") else "Fail") if g.get("audited")
                     and g.get("di_ratio") is not None else "Descriptive (n<30)",
        "Brier (group)": f"{g['brier']:.4f}" if g.get("brier") is not None else "—",
    } for g in fa["groups"]])
    st.dataframe(fdf, hide_index=True, use_container_width=True)
    st.caption("Small-N cells are reported descriptively, not audited — a stated "
               "limitation of the 420-record synthetic cohort.")
