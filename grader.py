from __future__ import annotations

import re
import subprocess
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from numbers import Real

import pandas as pd


SCORE_COLUMNS = [
    "student",
    "standard",
    "exit_ticket",
    "exit_ticket_date",
    "question",
    "possible_points",
    "awarded_points",
]
MANUAL_QUESTION = "Manual total"
MANUAL_STANDARD = "Manual grading"


@dataclass(frozen=True)
class PageMatch:
    page_index: int
    student: str | None
    confidence: int
    ocr_text: str


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def assignment_key(filename: str) -> str:
    stem = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    stem = re.sub(r"\banswer\s*key\b", "", stem, flags=re.IGNORECASE)
    return normalize(stem)


def lesson_number(value: object) -> str | None:
    """Return the leading lesson number used by scan and schedule names."""
    match = re.match(r"^\s*(\d+\.\d+)\b", str(value or ""))
    return match.group(1) if match else None


def date_for_assignment(schedule: pd.DataFrame, filename: str) -> str | None:
    """Look up an exit ticket's scheduled lesson date as an ISO date string."""
    if schedule.empty or not {"lesson", "exit_ticket_date"}.issubset(schedule.columns):
        return None
    target = lesson_number(filename)
    if target is None:
        return None
    matches = schedule.loc[
        schedule["lesson"].map(lesson_number).eq(target), "exit_ticket_date"
    ]
    parsed = matches.map(
        lambda value: pd.to_datetime(value, unit="D", origin="1899-12-30")
        if isinstance(value, Real) and not isinstance(value, bool)
        else pd.to_datetime(value, errors="coerce")
    )
    parsed = parsed.loc[parsed.notna()]
    if parsed.empty:
        return None
    return parsed.iloc[0].date().isoformat()


def render_page(pdf_bytes: bytes, page_index: int, zoom: float = 1.6) -> bytes:
    import fitz

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = document.load_page(page_index)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()


def extract_page_text(pdf_bytes: bytes, page_index: int) -> str:
    import fitz

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = document.load_page(page_index)
        embedded = page.get_text("text").strip()
        if embedded:
            return embedded
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        completed = subprocess.run(
            ["tesseract", "stdin", "stdout"],
            input=pixmap.tobytes("png"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return completed.stdout.decode("utf-8", errors="replace")
    finally:
        document.close()


def find_student(text: str, students: list[str], minimum_score: int = 72):
    normalized_text = normalize(text)
    for student in students:
        if normalize(student) in normalized_text:
            return student, 100

    best_student = None
    best_score = 0
    for student in students:
        student_text = normalize(student)
        try:
            from rapidfuzz import fuzz

            score = int(fuzz.partial_ratio(student_text, normalized_text))
        except ImportError:
            words = normalized_text.split()
            width = max(1, len(student_text.split()))
            candidates = [
                " ".join(words[start : start + width + 1])
                for start in range(max(1, len(words) - width + 1))
            ]
            score = int(
                100
                * max(
                    (SequenceMatcher(None, student_text, item).ratio() for item in candidates),
                    default=0,
                )
            )
        if score > best_score:
            best_student, best_score = student, score
    if best_score < minimum_score:
        return None, best_score
    return best_student, best_score


def identify_pages(pdf_bytes: bytes, students: list[str]) -> list[PageMatch]:
    import fitz

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_count = document.page_count
    document.close()
    matches = []
    for page_index in range(page_count):
        text = extract_page_text(pdf_bytes, page_index)
        student, confidence = find_student(text, students)
        matches.append(PageMatch(page_index, student, confidence, text))
    return matches


def questions_for_assignment(
    questions: pd.DataFrame, filename: str, course_level: str | None = None
) -> pd.DataFrame:
    if questions.empty:
        return questions
    target = assignment_key(filename)
    mask = questions["exit_ticket"].map(assignment_key).eq(target)
    if course_level and "course_level" in questions.columns:
        mask &= questions["course_level"].astype(str).str.casefold().eq(
            course_level.casefold()
        )
    # Each row is a distinct grading item. The question label includes
    # Regular/Honors when the same assessment number refers to different work.
    # Never collapse those rows merely because their numbers or standards match.
    return questions.loc[mask].copy().reset_index(drop=True)


def question_score_ticket(question: object) -> str:
    """Return the ticket whose score row a displayed question should update."""
    if hasattr(question, "get"):
        mapped = question.get("save_to_exit_ticket", "")
        if not pd.isna(mapped) and str(mapped).strip():
            return str(mapped).strip()
        displayed = question.get("exit_ticket", "")
        return "" if pd.isna(displayed) else str(displayed).strip()
    return ""


def question_is_mapped(question: object) -> bool:
    displayed = question.get("exit_ticket", "") if hasattr(question, "get") else ""
    return assignment_key(question_score_ticket(question)) != assignment_key(
        str(displayed)
    )


def grades_for_assignment(
    scores: pd.DataFrame,
    filename: str,
    questions: pd.DataFrame | None = None,
) -> dict[str, dict[str, float]]:
    """Restore previously entered numeric scores for one exit ticket."""
    required = {"student", "exit_ticket", "question", "awarded_points"}
    if scores.empty or not required.issubset(scores.columns):
        return {}

    target = assignment_key(filename)
    expected_sources = None
    if questions is not None and not questions.empty:
        expected_sources = {
            (assignment_key(question_score_ticket(question)), str(question["question"]))
            for _, question in questions.iterrows()
        }
        selected = scores.loc[
            scores.apply(
                lambda row: (
                    assignment_key(row["exit_ticket"]), str(row["question"])
                )
                in expected_sources,
                axis=1,
            )
        ]
    else:
        selected = scores.loc[
            scores["exit_ticket"].map(assignment_key).eq(target)
        ]
    grades: dict[str, dict[str, float]] = {}
    for _, row in selected.iterrows():
        awarded = row["awarded_points"]
        if pd.isna(awarded) or str(awarded).strip() in {"", "AE"}:
            continue
        try:
            points = float(awarded)
        except (TypeError, ValueError):
            continue
        student = str(row["student"])
        question = str(row["question"])
        grades.setdefault(student, {})[question] = points
    return grades


def grade_count(
    grades: dict[str, dict[str, float]],
    student: str | None,
    required_questions: list[str],
) -> int:
    """Count required numeric grades in one in-memory or saved grade snapshot."""
    if not student:
        return 0
    student_grades = grades.get(student, {})
    return sum(question in student_grades for question in required_questions)


def build_score_rows(
    students: list[str],
    questions: pd.DataFrame,
    grades: dict[str, dict[str, float]],
    exit_ticket_date: str,
    absent_students: set[str] | None = None,
) -> list[list[object]]:
    absent_students = absent_students or set()
    rows = []
    for student in students:
        student_grades = grades.get(student, {})
        for _, question in questions.iterrows():
            question_id = str(question["question"])
            mapped = question_is_mapped(question)
            if mapped and question_id not in student_grades:
                # A missing page on the newer ticket must not erase an older
                # score. Only an explicitly loaded or entered numeric grade may
                # update a mapped historical question.
                continue
            awarded = student_grades.get(question_id, "") if mapped else (
                "AE"
                if student in absent_students
                else student_grades.get(question_id, "")
            )
            rows.append(
                [
                    student,
                    question["standard"],
                    question_score_ticket(question),
                    exit_ticket_date,
                    question_id,
                    float(question["possible_points"]),
                    awarded if awarded == "AE" or awarded == "" else float(awarded),
                ]
            )
    return rows


def mapped_score_keys(
    students: list[str], questions: pd.DataFrame
) -> set[tuple[str, str, str]]:
    """Keys that may update existing score rows but may never create new ones."""
    return {
        (student, question_score_ticket(question), str(question["question"]))
        for student in students
        for _, question in questions.iterrows()
        if question_is_mapped(question)
    }


def unavailable_mapped_questions(
    students: list[str], questions: pd.DataFrame, scores: pd.DataFrame
) -> set[tuple[str, str]]:
    """Mapped UI fields that have no historical score row to update."""
    required = {"student", "exit_ticket", "question"}
    existing = set()
    if not scores.empty and required.issubset(scores.columns):
        existing = {
            (
                str(row["student"]),
                assignment_key(row["exit_ticket"]),
                str(row["question"]),
            )
            for _, row in scores.iterrows()
        }
    return {
        (student, str(question["question"]))
        for student in students
        for _, question in questions.iterrows()
        if question_is_mapped(question)
        and (
            student,
            assignment_key(question_score_ticket(question)),
            str(question["question"]),
        )
        not in existing
    }


def merge_score_rows(
    header: list[str],
    data: list[list[object]],
    rows: list[list[object]],
    update_existing_only: set[tuple[str, str, str]] | None = None,
) -> list[list[object]]:
    """Merge score rows while protecting mapped historical records."""
    update_existing_only = update_existing_only or set()
    header_map = {name: index for index, name in enumerate(header)}
    key_columns = ["student", "exit_ticket", "question"]
    positions = {
        tuple(str(row[header_map[column]]) for column in key_columns): index
        for index, row in enumerate(data)
        if len(row) >= len(header)
    }
    for new_row in rows:
        row_by_name = dict(zip(SCORE_COLUMNS, new_row))
        key = tuple(str(row_by_name[column]) for column in key_columns)
        output = [row_by_name.get(column, "") for column in header]
        if key in positions:
            if key in update_existing_only:
                data[positions[key]][header_map["awarded_points"]] = row_by_name[
                    "awarded_points"
                ]
            else:
                data[positions[key]] = output
        elif key in update_existing_only:
            raise ValueError(
                "Mapped score could not be saved because the original row does not "
                f"exist: {key[0]} — {key[1]} — {key[2]}"
            )
        else:
            positions[key] = len(data)
            data.append(output)
    return data


def build_manual_score_rows(
    students: list[str],
    filename: str,
    possible_points: float,
    grades: dict[str, dict[str, float]],
    exit_ticket_date: str,
    absent_students: set[str] | None = None,
) -> list[list[object]]:
    """Build one overall-score row per student for an unconfigured ticket."""
    absent_students = absent_students or set()
    exit_ticket = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE).strip()
    return [
        [
            student,
            MANUAL_STANDARD,
            exit_ticket,
            exit_ticket_date,
            MANUAL_QUESTION,
            float(possible_points),
            "AE"
            if student in absent_students
            else (
                float(grades[student][MANUAL_QUESTION])
                if MANUAL_QUESTION in grades.get(student, {})
                else ""
            ),
        ]
        for student in students
    ]
