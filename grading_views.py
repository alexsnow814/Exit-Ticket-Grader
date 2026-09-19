"""Shared completeness and navigation rules for the grader's three views."""

from __future__ import annotations

import pandas as pd

from grader import MANUAL_QUESTION, grade_count, lesson_number, question_is_mapped


def unit_number(name: str) -> str | None:
    lesson = lesson_number(name)
    return lesson.split(".", 1)[0] if lesson else None


def lesson_sort_key(name: str) -> tuple[int, int, str]:
    lesson = lesson_number(name)
    if lesson:
        unit, number = lesson.split(".", 1)
        return int(unit), int(number), name.casefold()
    return 999999, 999999, name.casefold()


def required_questions(questions: pd.DataFrame, *, native_only: bool = False) -> list[str]:
    if questions.empty:
        return [MANUAL_QUESTION]
    rows = questions.to_dict("records")
    if native_only:
        rows = [row for row in rows if not question_is_mapped(row)]
    return list(dict.fromkeys(str(row["question"]) for row in rows))


def completion_lists(
    grades: dict[str, dict[str, float]],
    students: list[str],
    required: list[str],
) -> tuple[list[str], list[str]]:
    """A valid zero is graded; even one missing question leaves work to grade."""
    if not required:
        return sorted(students), []
    graded = sorted(
        student for student in students
        if grade_count(grades, student, required) == len(required)
    )
    missing = sorted(student for student in students if student not in set(graded))
    return graded, missing


def indexed_pages(scans: list[dict], matches_by_scan: dict[str, list]) -> list[tuple[int, int, str | None]]:
    """Return scan/page/student entries in lesson and physical page order."""
    entries = []
    for scan_index, scan in enumerate(scans):
        for match in matches_by_scan.get(scan["id"], []):
            entries.append((scan_index, match.page_index, match.student))
    return entries
