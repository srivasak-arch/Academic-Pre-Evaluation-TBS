"""UI components — CSS and the indicator chip rendering.

The chip is the product's signature element: equal-weight chips, colour + icon +
word, with FILL STYLE encoding confidence (solid = high, outlined = lower) so a
low-evidence green can never be mistaken for a high-evidence one.
"""
import html
import streamlit as st
from .config import PALETTE, CONFIDENCE_LABEL

GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:ital,wght@0,400;0,600;0,700;1,400&display=swap');

:root {
  --brand:#0E73B9; --brand-dark:#0B5C94; --brand-tint:#E7F1F9;
  --ink:#1A2330; --muted:#5B6470; --line:#E6E8EB; --surface:#FFFFFF;
  --radius:12px; --shadow:0 1px 2px rgba(16,24,40,0.05);
}

/* ---- Typography: Source Sans everywhere, tabular figures for numbers ---- */
html, body, [class*="css"], .stMarkdown, .stDataFrame, button, input, textarea, select {
  font-family: 'Source Sans 3', 'Source Sans Pro', -apple-system, 'Segoe UI', sans-serif !important;
}
h1, h2, h3 { color: var(--ink); font-weight: 700; letter-spacing: -0.01em; }
[data-testid="stMetricValue"], .k-value, td { font-variant-numeric: tabular-nums; }

/* ---- Layout: constrained content, tighter default airiness ---- */
.block-container { max-width: 1180px; padding-top: 1.1rem; padding-bottom: 3rem; }
section.main > div { padding-top: 0.4rem; }

/* ---- Sidebar: TBS blue with white nav text ---- */
[data-testid="stSidebar"] { background: var(--brand) !important; border-right: none; }
[data-testid="stSidebar"] * { color: #FFFFFF; }
[data-testid="stSidebar"] svg { fill: currentColor; }
[data-testid="stSidebar"] img { border-radius: 8px; background: #FFFFFF; padding: 8px 10px; }
/* app title above the menu items */
[data-testid="stSidebarNav"]::before {
  content: "Academic Pre-Evaluation";
  display: block; color: #FFFFFF; font-weight: 700; font-size: 1.02rem;
  letter-spacing: -0.01em; padding: 12px 12px 8px;
  border-bottom: 1px solid rgba(255,255,255,0.22); margin-bottom: 6px;
}
[data-testid="stSidebarNav"] a { border-radius: 8px; }
[data-testid="stSidebarNav"] a:hover { background: rgba(255,255,255,0.12); }
[data-testid="stSidebarNav"] a[aria-current="page"] { background: rgba(255,255,255,0.22) !important; }
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: #FFFFFF !important; font-weight: 700; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: rgba(255,255,255,0.85) !important; }
.sb-brand { padding: 0.2rem 0 0.5rem 0; }
.sb-brand img { width: 100%; max-width: 200px; border-radius: 8px; }
.sb-app { font-weight: 700; color: #FFFFFF; font-size: 0.95rem; margin-top: 6px; }
.sb-sub { color: rgba(255,255,255,0.85); font-size: 0.74rem; line-height: 1.35; }

/* ---- Brand header banner ---- */
.tbs-footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--line); }
.tbs-banner { border-radius: var(--radius); overflow: hidden; border: 1px solid var(--line);
  box-shadow: var(--shadow); margin: 0; }
.tbs-banner img { width: 100%; display: block; max-height: 96px; object-fit: cover; }

/* ---- Cards / containers ---- */
[data-testid="stVerticalBlockBorderWrapper"] > div {
  border-radius: var(--radius) !important;
}
div[data-testid="stExpander"] details {
  border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface);
}
.stButton > button[kind="primary"] { background: var(--brand); border: 1px solid var(--brand); }
.stButton > button[kind="primary"]:hover { background: var(--brand-dark); border-color: var(--brand-dark); }
.stButton > button:focus { box-shadow: 0 0 0 3px rgba(14,115,185,0.35); }
a, a:visited { color: var(--brand); }

/* ---- Identity band ---- */
.idband { color: var(--muted); font-size: 0.86rem; line-height: 1.5; }
.idband b { color: var(--ink); }

/* ---- Indicator chips (evidence colours only — never brand blue) ---- */
.chiprow { display:flex; flex-wrap:wrap; gap:10px; margin:0.4rem 0 0.2rem 0; }
.chip {
  border-radius:10px; padding:9px 12px; min-width:150px; flex:1 1 150px;
  border:1.5px solid; font-size:0.82rem; line-height:1.25; background-color: var(--surface);
}
.chip .lab { font-weight:600; display:flex; align-items:center; gap:7px; }
.chip .val { font-size:0.74rem; opacity:0.92; margin-top:3px; }
.chip .conf { font-size:0.68rem; opacity:0.8; margin-top:5px; letter-spacing:0.02em; }
.chip.lowconf { background-image: repeating-linear-gradient(
   45deg, transparent, transparent 6px, rgba(0,0,0,0.045) 6px, rgba(0,0,0,0.045) 12px); }
.chip.outlined { background:transparent !important; }

.facet-reason { color:var(--muted); font-size:0.86rem; border-left:3px solid var(--line);
  padding-left:10px; margin:2px 0 10px 0; }
.section-label { text-transform:uppercase; letter-spacing:0.08em; font-size:0.72rem;
  color:var(--muted); font-weight:700; margin:0.8rem 0 0.2rem 0; }
.legend { font-size:0.74rem; color:var(--muted); }
hr { border:none; border-top:1px solid var(--line); margin:0.8rem 0; }

/* ---- Queue table ---- */
.q-row { border-bottom: 1px solid var(--line); padding: 2px 0; }
</style>
"""

def inject_css():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def chip_html(result) -> str:
    p = PALETTE.get(result.value, PALETTE["info"])
    klass = "chip"
    if result.confidence == "low":
        klass += " lowconf outlined"
    elif result.confidence == "moderate":
        klass += " lowconf"
    conf_line = (f'<div class="conf">{CONFIDENCE_LABEL.get(result.confidence, "")}</div>'
                 if result.scale != "confidence" else "")
    # short value word per scale
    word = p["word"] if result.scale != "neutral" else "Context"
    return (
        f'<div class="{klass}" style="background:{p["bg"]};color:{p["fg"]};border-color:{p["border"]};">'
        f'<div class="lab"><span>{p["icon"]}</span><span>{html.escape(result.name)}</span></div>'
        f'<div class="val">{html.escape(word)}</div>'
        f'{conf_line}</div>'
    )


def chip_row(results):
    chips = "".join(chip_html(r) for r in results)
    st.markdown(f'<div class="chiprow">{chips}</div>', unsafe_allow_html=True)


def legend():
    st.markdown(
        '<div class="legend">'
        '✓ Green · ! Amber · ✕ Red · … Evidence pending · ⓘ Context (not scored) · '
        'hatched/outlined = lower-confidence evidence. '
        'Indicators are independent and advisory — there is no overall score or ranking.'
        '</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Business-intelligence components (used by the Data Insights page)
# ---------------------------------------------------------------------------
INSIGHTS_CSS = """
<style>
.kpi-grid { display:flex; flex-wrap:wrap; gap:12px; margin:0.2rem 0 0.4rem 0; }
.kpi { flex:1 1 200px; min-width:200px; border:1px solid var(--line,#E6E8EB); box-shadow:var(--shadow,0 1px 2px rgba(16,24,40,0.05));
  border-radius:12px; padding:14px 16px; background:#fff; position:relative; overflow:hidden; }
.kpi::before { content:""; position:absolute; left:0; top:0; bottom:0; width:4px; }
.kpi.good::before   { background:#1E8E5A; }
.kpi.watch::before  { background:#B9761A; }
.kpi.bad::before    { background:#C23B52; }
.kpi.neutral::before{ background:#0E73B9; }
.kpi .k-label { font-size:0.72rem; text-transform:uppercase; letter-spacing:0.06em;
  color:var(--muted,#5A6169); font-weight:700; }
.kpi .k-value { font-size:1.7rem; font-weight:700; color:var(--ink,#1B1F24); line-height:1.1; margin:4px 0; }
.kpi .k-sub   { font-size:0.8rem; color:var(--muted,#5A6169); line-height:1.3; }
.narr { border-left:3px solid #0E73B9; background:#F3F8FC; border-radius:0 8px 8px 0;
  padding:10px 14px; margin:8px 0 4px 0; font-size:0.88rem; color:#2A3440; line-height:1.45; }
.narr b { color:#1B1F24; }
.narr .takeaway { display:block; margin-top:4px; }
.reco { border-left:3px solid #B9761A; background:#FBF4E9; border-radius:0 8px 8px 0;
  padding:8px 14px; margin:6px 0; font-size:0.86rem; color:#5A4A2E; }
.limits { font-size:0.78rem; color:#6A7078; font-style:italic; margin:4px 0 2px 0; }
.sec-head { margin:1.3rem 0 0.2rem 0; }
.sec-head h3 { margin:0; }
.sec-head p { margin:2px 0 0 0; color:var(--muted,#5A6169); font-size:0.86rem; }
</style>
"""


def inject_insights_css():
    st.markdown(INSIGHTS_CSS, unsafe_allow_html=True)


def section_header(title: str, subtitle: str = ""):
    st.markdown(f'<div class="sec-head"><h3>{html.escape(title)}</h3>'
                + (f'<p>{html.escape(subtitle)}</p>' if subtitle else "")
                + '</div>', unsafe_allow_html=True)


def kpi_row(cards):
    """cards: list of dicts {label, value, sub, tone in good/watch/bad/neutral}."""
    items = "".join(
        f'<div class="kpi {c.get("tone","neutral")}">'
        f'<div class="k-label">{html.escape(str(c["label"]))}</div>'
        f'<div class="k-value">{html.escape(str(c["value"]))}</div>'
        f'<div class="k-sub">{html.escape(str(c.get("sub","")))}</div></div>'
        for c in cards)
    st.markdown(f'<div class="kpi-grid">{items}</div>', unsafe_allow_html=True)


def narrative(takeaway: str, why: str = "", unusual: str = ""):
    """Plain-English commentary shown beneath a chart/metric."""
    body = f'<b>Takeaway.</b> {html.escape(takeaway)}'
    if why:
        body += f'<span class="takeaway"><b>Why it matters.</b> {html.escape(why)}</span>'
    if unusual:
        body += f'<span class="takeaway"><b>Worth noting.</b> {html.escape(unusual)}</span>'
    st.markdown(f'<div class="narr">{body}</div>', unsafe_allow_html=True)


def recommendation(text: str):
    st.markdown(f'<div class="reco">💡 <b>Observation.</b> {html.escape(text)}</div>',
                unsafe_allow_html=True)


def limitations(text: str):
    st.markdown(f'<div class="limits">{html.escape(text)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Brand assets (embedded as base64 so they work in the frozen executable too)
# ---------------------------------------------------------------------------
import base64
from .config import LOGO_PATH, HEADER_PATH


@st.cache_data(show_spinner=False)
def _b64(path_str: str) -> str | None:
    import pathlib
    p = pathlib.Path(path_str)
    if not p.exists():
        return None
    return base64.b64encode(p.read_bytes()).decode()


def sidebar_brand():
    """TBS logo lockup at the top of the sidebar."""
    logo = _b64(str(LOGO_PATH))
    if logo:
        st.markdown(
            f'<div class="sb-brand"><img src="data:image/jpeg;base64,{logo}" alt="Trinity Business School"/>'
            f'<div class="sb-app">Academic Pre-Evaluation</div>'
            f'<div class="sb-sub">Admissions decision-support</div></div>',
            unsafe_allow_html=True)
    else:
        st.markdown('<div class="sb-brand"><div class="sb-app">Academic Pre-Evaluation</div>'
                    '<div class="sb-sub">Trinity Business School</div></div>',
                    unsafe_allow_html=True)


def brand_footer():
    """TBS banner as a footer across the bottom of the content area."""
    banner = _b64(str(HEADER_PATH))
    if banner:
        st.markdown(
            f'<div class="tbs-footer"><div class="tbs-banner"><img '
            f'src="data:image/jpeg;base64,{banner}" '
            f'alt="Trinity Business School — Transforming Business for Good"/></div></div>',
            unsafe_allow_html=True)
