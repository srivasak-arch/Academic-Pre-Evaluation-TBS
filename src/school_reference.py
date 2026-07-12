"""Reference data for school/college verification.

Maps each affiliating / collegiate / federal / umbrella university to its known
constituent colleges, affiliated colleges, member institutions, or internal
schools -- plus the surface variants (abbreviations, spellings) that appear on
real transcripts.

Why this exists: detection only ever *selects from this list*, so a noisy scan
or fuzzy mismatch can never surface a school that does not belong to the
declared university. Extend it over time; start with your highest-volume
universities.

The four structures this handles (they all behave the same way here):
  - collegiate       : constituent colleges (Delhi, Calcutta, Anna)
  - affiliating      : autonomous colleges under a parent (Mumbai, Pune)
  - federal          : member institutions (University of London, NUI)
  - internal_school  : faculties within one university (Peking, Ghana)
"""
from __future__ import annotations

# ---- university aliases: how applicants / documents write the parent ----
UNIVERSITY_ALIASES = {
    "university of delhi": "University of Delhi",
    "delhi university": "University of Delhi",
    "du": "University of Delhi",

    "savitribai phule pune university": "Savitribai Phule Pune University",
    "university of pune": "Savitribai Phule Pune University",
    "pune university": "Savitribai Phule Pune University",
    "sppu": "Savitribai Phule Pune University",

    "university of mumbai": "University of Mumbai",
    "mumbai university": "University of Mumbai",

    "anna university": "Anna University",

    "university of calcutta": "University of Calcutta",
    "calcutta university": "University of Calcutta",

    "university of london": "University of London",

    "national university of ireland": "National University of Ireland",
    "nui": "National University of Ireland",

    "peking university": "Peking University",
    "pku": "Peking University",

    "university of ghana": "University of Ghana",
}

# ---- canonical school lists: {university: {school: [variants]}} ----
UNIVERSITIES: dict[str, dict[str, list[str]]] = {
    "University of Delhi": {
        "Shri Ram College of Commerce": ["Shri Ram College of Commerce",
                                         "Sri Ram College of Commerce", "SRCC"],
        "Hindu College": ["Hindu College"],
        "Miranda House": ["Miranda House"],
        "St. Stephen's College": ["St. Stephen's College", "St Stephens College"],
        "Hansraj College": ["Hansraj College", "Hans Raj College"],
        "Lady Shri Ram College for Women": ["Lady Shri Ram College", "LSR"],
        "Ramjas College": ["Ramjas College"],
        "Kirori Mal College": ["Kirori Mal College", "KMC"],
        "Gargi College": ["Gargi College"],
        "Sri Venkateswara College": ["Sri Venkateswara College"],
        "Zakir Husain Delhi College": ["Zakir Husain Delhi College", "Zakir Husain College"],
        "Jesus and Mary College": ["Jesus and Mary College", "JMC"],
    },
    "Savitribai Phule Pune University": {
        "Fergusson College": ["Fergusson College"],
        "Sir Parashurambhau College": ["Sir Parashurambhau College", "SP College"],
        "Nowrosjee Wadia College": ["Nowrosjee Wadia College", "Wadia College"],
        "Brihan Maharashtra College of Commerce": ["Brihan Maharashtra College of Commerce", "BMCC"],
        "Modern College of Arts, Science and Commerce": ["Modern College"],
        "St. Mira's College for Girls": ["St. Mira's College"],
    },
    "University of Mumbai": {
        "St. Xavier's College, Mumbai": ["St. Xavier's College", "St Xaviers College"],
        "H.R. College of Commerce and Economics": ["H.R. College of Commerce", "HR College"],
        "Jai Hind College": ["Jai Hind College"],
        "Mithibai College": ["Mithibai College"],
        "K.C. College": ["K.C. College", "KC College"],
        "Sydenham College of Commerce and Economics": ["Sydenham College"],
        "Narsee Monjee College of Commerce and Economics": ["Narsee Monjee College", "NM College"],
        "Sophia College for Women": ["Sophia College"],
        "Ramnarain Ruia Autonomous College": ["Ruia College", "Ramnarain Ruia"],
    },
    "Anna University": {
        "College of Engineering, Guindy": ["College of Engineering, Guindy",
                                           "College of Engineering Guindy", "CEG"],
        "Madras Institute of Technology": ["Madras Institute of Technology", "MIT Chromepet"],
        "Alagappa College of Technology": ["Alagappa College of Technology", "ACT"],
        "School of Architecture and Planning": ["School of Architecture and Planning"],
    },
    "University of Calcutta": {
        "Scottish Church College": ["Scottish Church College"],
        "Bethune College": ["Bethune College"],
        "Lady Brabourne College": ["Lady Brabourne College"],
        "Maulana Azad College": ["Maulana Azad College"],
        "Asutosh College": ["Asutosh College"],
        "City College, Kolkata": ["City College"],
        "St. Paul's Cathedral Mission College": ["St. Paul's Cathedral Mission College"],
    },
    "University of London": {
        "London School of Economics and Political Science":
            ["London School of Economics and Political Science",
             "London School of Economics", "LSE"],
        "University College London": ["University College London", "UCL"],
        "King's College London": ["King's College London", "Kings College London", "KCL"],
        "Queen Mary University of London": ["Queen Mary University of London", "Queen Mary"],
        "Birkbeck, University of London": ["Birkbeck"],
        "SOAS University of London": ["SOAS"],
        "Goldsmiths, University of London": ["Goldsmiths"],
        "Royal Holloway, University of London": ["Royal Holloway"],
        "City, University of London": ["City, University of London"],
    },
    "National University of Ireland": {
        "University College Dublin": ["University College Dublin", "UCD"],
        "University College Cork": ["University College Cork", "UCC"],
        "University of Galway": ["University of Galway", "NUI Galway",
                                 "National University of Ireland, Galway"],
        "Maynooth University": ["Maynooth University", "NUI Maynooth"],
    },
    "Peking University": {
        "Guanghua School of Management": ["Guanghua School of Management", "Guanghua"],
        "School of Economics": ["School of Economics"],
        "National School of Development": ["National School of Development"],
        "Yuanpei College": ["Yuanpei College"],
        "School of International Studies": ["School of International Studies"],
    },
    "University of Ghana": {
        "University of Ghana Business School": ["University of Ghana Business School", "UGBS"],
        "College of Humanities": ["College of Humanities"],
        "School of Law": ["School of Law", "University of Ghana School of Law"],
        "College of Basic and Applied Sciences": ["College of Basic and Applied Sciences"],
    },
}


def resolve_university(name: str | None) -> str | None:
    """Free-text university name -> canonical key (alias-aware), or None."""
    if not name:
        return None
    key = " ".join(name.strip().lower().split())
    if key in UNIVERSITY_ALIASES:
        return UNIVERSITY_ALIASES[key]
    for canonical in UNIVERSITIES:
        if canonical.lower() == key:
            return canonical
    return None


def schools_for(university: str | None) -> dict[str, list[str]]:
    canonical = resolve_university(university)
    return UNIVERSITIES.get(canonical, {}) if canonical else {}


def school_names_for(university: str | None) -> list[str]:
    """Sorted canonical school names -- used for the correction dropdown."""
    return sorted(schools_for(university).keys())


def university_names() -> list[str]:
    return sorted(UNIVERSITIES.keys())
