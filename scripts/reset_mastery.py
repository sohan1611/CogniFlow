"""Explicitly reset persisted student mastery and diagnostic history.

Examples:

    .venv/Scripts/python.exe scripts/reset_mastery.py --student student-id --yes
    .venv/Scripts/python.exe scripts/reset_mastery.py --all --yes

Without ``--yes`` this command prints what it would change and refuses to write.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.mastery.bkt import BKTParams  # noqa: E402
from app.services.student_store import StudentStore  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reset mastery, attempts, and diagnostic state for selected students."
    )
    selected = parser.add_mutually_exclusive_group(required=True)
    selected.add_argument("--student", metavar="ID", help="reset one student")
    selected.add_argument("--all", action="store_true", help="reset every student")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="perform the reset; without this flag the command only prints a summary",
    )
    return parser


def main(argv: list[str] | None = None, *, store: StudentStore | None = None) -> int:
    args = _parser().parse_args(argv)
    student_store = store or StudentStore()

    if args.all:
        student_ids = student_store.student_ids()
    elif student_store.exists(args.student):
        student_ids = [args.student]
    else:
        print(f"No student found with id {args.student!r}.")
        return 1

    summaries = [
        (
            student_id,
            len(student_store.load_skills(student_id)),
            len(student_store.attempts_for(student_id)),
        )
        for student_id in student_ids
    ]
    print(f"Reset mastery summary ({len(summaries)} student(s)):")
    for student_id, skill_count, attempt_count in summaries:
        print(
            f"  {student_id}: {skill_count} skill row(s), "
            f"{attempt_count} attempt row(s) to delete"
        )

    if not args.yes:
        print("Refusing to make changes without the explicit --yes flag.")
        return 2

    prior = BKTParams().p_init
    reset_skills = 0
    deleted_attempts = 0
    for student_id in student_ids:
        skill_count, attempt_count = student_store.reset_mastery(student_id, prior)
        reset_skills += skill_count
        deleted_attempts += attempt_count
    print(
        f"Reset {reset_skills} skill row(s) to prior {prior:.2f}; "
        f"deleted {deleted_attempts} attempt row(s); cleared diagnostic state."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
