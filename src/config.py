"""Central configuration: paths, palette, programmes, and decision options."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Data dir is overridable so the packaged/frozen executable can keep the database
# in a writable location (the bundle itself is read-only).
_DATA_ENV = os.environ.get("DASHBOARD_DATA_DIR")
DATA_DIR = Path(_DATA_ENV) if _DATA_ENV else ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "dashboard.db"
CSV_PATH = DATA_DIR / "applicants.csv"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# ---- Colour-blind-safe semantic palette (paired ALWAYS with icon + word) ----
# Brand blue (#0E73B9) is reserved for interface chrome; these hues are for
# evidence only. Neutral/confidence scales are true greys so an informational
# chip can never read as "selected".
PALETTE = {
    "green":  {"bg": "#E4F2EB", "fg": "#14603C", "border": "#1E8E5A", "icon": "✓", "word": "Green"},
    "amber":  {"bg": "#FBF0DF", "fg": "#7A4F0F", "border": "#B9761A", "icon": "!", "word": "Amber"},
    "red":    {"bg": "#F9E7EA", "fg": "#8A2337", "border": "#C23B52", "icon": "✕", "word": "Red"},
    "pending":{"bg": "#EFF0F2", "fg": "#4A5058", "border": "#9AA0A6", "icon": "…", "word": "Pending"},
    "info":   {"bg": "#F1F2F4", "fg": "#3E4650", "border": "#8B939C", "icon": "ⓘ", "word": "Context"},
    # confidence (evidence-quality) scale — greys, never good/bad
    "strong": {"bg": "#EBEDEF", "fg": "#333B44", "border": "#6E7680", "icon": "▰▰▰", "word": "Strong evidence"},
    "partial":{"bg": "#F0F1F3", "fg": "#4A5058", "border": "#9AA0A6", "icon": "▰▰▱", "word": "Partial evidence"},
    "sparse": {"bg": "#F4F3F0", "fg": "#5A4A3A", "border": "#B0A48F", "icon": "▰▱▱", "word": "Sparse evidence"},
}

# Brand tokens (interface chrome)
BRAND = {
    "blue": "#0E73B9", "blue_dark": "#0B5C94", "blue_tint": "#E7F1F9",
    "bg": "#F8F8F8", "surface": "#FFFFFF", "line": "#E6E8EB",
    "ink": "#1A2330", "muted": "#5B6470",
}
ASSETS_DIR = ROOT / "assets"
LOGO_PATH = ASSETS_DIR / "tbs_logo.jpg"
HEADER_PATH = ASSETS_DIR / "tbs_header.jpg"

CONFIDENCE_LABEL = {"high": "High confidence", "moderate": "Moderate confidence", "low": "Low confidence"}

PROGRAMMES = {
    "BA": "MSc in Business Analytics",
    "IM": "MSc in International Management",
}

DECISION_OPTIONS = [
    ("offer",     "Recommend offer"),
    ("more_info", "Request more information"),
    ("defer",     "Defer"),
    ("reject",    "Recommend reject"),
]

# Indicator display order (defines the chip row order; equal visual weight)
INDICATOR_ORDER = [
    "academic_performance",
    "programme_prerequisites",
    "quantitative_readiness",
    "english_requirement",
    "institution_context",
    "subject_alignment",
    "work_experience",
    "graduation_recency",
    "document_completeness",
    "evidence_confidence",
]
