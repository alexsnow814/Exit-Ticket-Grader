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
            rows.append(
                [
                    student,
                    question["standard"],
                    question["exit_ticket"],
                    exit_ticket_date,
                    question_id,
                    float(question["possible_points"]),
                    "AE"
                    if student in absent_students
                    else float(student_grades.get(question_id, 0)),
                ]
            )
    return rows


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
            else float(grades.get(student, {}).get(MANUAL_QUESTION, 0)),
        ]
        for student in students
    ]
