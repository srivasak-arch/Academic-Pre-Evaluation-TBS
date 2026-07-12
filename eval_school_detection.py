"""Score the school-detection pipeline against GROUND_TRUTH_answer_key.csv.

Two passes per applicant:
  A) with the declared university (as it comes from the application form / CV)
  B) with NO declaration (parent must be detected from the transcript itself)
"""
import csv, sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from src.school_service import group_uploads, applicant_key_from_filename  # noqa
from src.school_detect import verify_schooling  # noqa

APPS = pathlib.Path("/home/claude/work/synthetic_applications")


def load_docs():
    files = []
    for folder in sorted(APPS.iterdir()):
        if folder.is_dir():
            for pdf in folder.glob("*.pdf"):
                files.append((pdf.name, pdf.read_bytes()))
    return group_uploads(files)


def norm(s):  # tolerant compare: ground truth writes "St. Xavier's College, Mumbai"
    return "".join(c for c in (s or "").lower() if c.isalnum())


def main():
    key = {}
    with open(APPS / "GROUND_TRUTH_answer_key.csv") as f:
        for row in csv.DictReader(f):
            key[row["applicant_id"]] = row

    grouped = load_docs()
    for label, use_declared in (("A) declared university given", True),
                                ("B) no declaration (auto-detect parent)", False)):
        print(f"\n=== Pass {label} ===")
        correct = 0
        for app_id, truth in sorted(key.items()):
            docs = grouped.get(app_id, {})
            declared = truth["university_on_cv"] if use_declared else None
            det = verify_schooling(docs, declared)
            truth_school = truth["actual_school_on_transcript"]
            ok = norm(det.school) == norm(truth_school) or (
                 det.school and norm(det.school) in norm(truth_school)) or (
                 det.school and norm(truth_school) in norm(det.school))
            correct += ok
            flag = "OK " if ok else "MISS"
            print(f"{flag} {app_id} [{truth['structure']:<14}] "
                  f"detected={det.school!r} ({det.confidence:.0f}%, {det.source_document}, "
                  f"p{det.page}, corroborated={det.corroborated}) "
                  f"truth={truth_school!r}"
                  + (f"  notes={det.notes}" if det.notes else ""))
        print(f"Score: {correct}/{len(key)}")


if __name__ == "__main__":
    main()
