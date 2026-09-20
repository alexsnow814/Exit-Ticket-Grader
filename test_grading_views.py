import pandas as pd

from grading_views import (
    completion_lists,
    completion_status,
    indexed_pages,
    lesson_sort_key,
    required_questions,
    unit_number,
)


def test_partial_grade_and_zero_count_correctly():
    grades = {"A": {"1": 0.0, "2": 2.0}, "B": {"1": 0.0}}
    graded, missing = completion_lists(grades, ["A", "B", "C"], ["1", "2"])
    assert graded == ["A"]
    assert missing == ["B", "C"]


def test_uploaded_ungraded_and_no_upload_are_distinct():
    grades = {"A": {"1": 0.0}, "B": {"1": 2.0}}
    graded, still, missing = completion_status(
        grades, ["A", "B", "C"], ["1", "2"], {"A", "B"}
    )
    assert graded == []
    assert still == ["A", "B"]
    assert missing == ["C"]


def test_unit_numbers_do_not_collapse_tenths():
    assert unit_number("1.10 Exit Ticket") == "1"
    assert unit_number("2.7 Exit Ticket") == "2"
    assert lesson_sort_key("1.10 Exit Ticket") > lesson_sort_key("1.9 Exit Ticket")


def test_mapped_questions_do_not_create_new_assignment_requirements():
    questions = pd.DataFrame([
        {"exit_ticket": "1.8 Exit Ticket", "question": "11a", "save_to_exit_ticket": "1.5 Exit Ticket"},
        {"exit_ticket": "1.8 Exit Ticket", "question": "14", "save_to_exit_ticket": ""},
    ])
    assert required_questions(questions) == ["11a", "14"]
    assert required_questions(questions, native_only=True) == ["14"]


def test_indexed_pages_preserve_scan_and_page_order():
    class Match:
        def __init__(self, page_index, student):
            self.page_index = page_index
            self.student = student

    scans = [{"id": "a"}, {"id": "b"}]
    matches = {"a": [Match(0, "A"), Match(1, None)], "b": [Match(0, "B")]}
    assert indexed_pages(scans, matches) == [(0, 0, "A"), (0, 1, None), (1, 0, "B")]
