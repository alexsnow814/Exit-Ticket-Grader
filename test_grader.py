import pandas as pd

from grader import (
    MANUAL_QUESTION,
    assignment_key,
    build_manual_score_rows,
    build_score_rows,
    date_for_assignment,
    find_student,
    questions_for_assignment,
)


def test_assignment_key_matches_answer_key():
    assert assignment_key("1.1 Exit Ticket.pdf") == assignment_key(
        "1.1 Exit Ticket Answer Key.pdf"
    )


def test_find_student_exact_and_fuzzy():
    roster = ["Nadir Al-Asadi", "Carlos Castillo Aguirre"]
    assert find_student("Student: Nadir Al-Asadi", roster) == ("Nadir Al-Asadi", 100)
    assert find_student("CarIos Castillo Aguirre", roster)[0] == "Carlos Castillo Aguirre"


def test_question_filter_and_absent_student_ae():
    questions = pd.DataFrame([
        {"course_level": "Regular", "exit_ticket": "1.1 Exit Ticket", "question": "5", "standard": "S-ID.A.2", "possible_points": 5},
        {"course_level": "Honors", "exit_ticket": "1.1 Exit Ticket", "question": "5", "standard": "S-ID.A.2", "possible_points": 5},
    ])
    selected = questions_for_assignment(questions, "1.1 Exit Ticket.pdf", "Regular")
    rows = build_score_rows(
        ["Student One", "Student Two"],
        selected,
        {"Student One": {"5": 4}},
        "2026-08-28",
        {"Student Two"},
    )
    assert rows[0][-1] == 4
    assert rows[1][-1] == "AE"


def test_regular_and_honors_variants_remain_distinct():
    questions = pd.DataFrame([
        {"course_level": "Regular", "exit_ticket": "1.7 Exit Ticket", "question": "Regular 11d", "standard": "S-ID.A.3", "possible_points": 5},
        {"course_level": "Honors", "exit_ticket": "1.7 Exit Ticket", "question": "Honors 11c", "standard": "S-ID.A.3", "possible_points": 5},
    ])
    selected = questions_for_assignment(questions, "1.7 Exit Ticket.pdf")
    assert selected["question"].tolist() == ["Regular 11d", "Honors 11c"]


def test_batch_question_snapshot_preserves_entered_scores():
    batch_questions = pd.DataFrame([
        {"course_level": "Regular", "exit_ticket": "1.3 Exit Ticket", "question": "Regular 10a", "standard": "S-ID.A.1", "possible_points": 5},
        {"course_level": "Honors", "exit_ticket": "1.3 Exit Ticket", "question": "Regular 1 / Honors 4", "standard": "S-ID.A.1", "possible_points": 5},
    ])
    refreshed_questions = batch_questions.copy()
    refreshed_questions["question"] = ["10a", "1"]
    grades = {
        "Student One": {
            "Regular 10a": 4.5,
            "Regular 1 / Honors 4": 3,
        }
    }

    saved_from_batch = build_score_rows(
        ["Student One"], batch_questions, grades, "2026-09-02"
    )
    saved_from_refresh = build_score_rows(
        ["Student One"], refreshed_questions, grades, "2026-09-02"
    )

    assert [row[-1] for row in saved_from_batch] == [4.5, 3]
    assert [row[-1] for row in saved_from_refresh] == [0, 0]


def test_manual_grading_builds_one_row_and_marks_absent_students_ae():
    rows = build_manual_score_rows(
        ["Student One", "Student Two"],
        "Unconfigured Exit Ticket.pdf",
        12,
        {"Student One": {MANUAL_QUESTION: 9.5}},
        "2026-08-26",
        {"Student Two"},
    )

    assert rows == [
        [
            "Student One",
            "Manual grading",
            "Unconfigured Exit Ticket",
            "2026-08-26",
            "Manual total",
            12.0,
            9.5,
        ],
        [
            "Student Two",
            "Manual grading",
            "Unconfigured Exit Ticket",
            "2026-08-26",
            "Manual total",
            12.0,
            "AE",
        ],
    ]


def test_unentered_present_student_still_receives_zero():
    questions = pd.DataFrame([
        {
            "exit_ticket": "1.1 Exit Ticket",
            "question": "1",
            "standard": "S-ID.A.1",
            "possible_points": 5,
        }
    ])
    rows = build_score_rows(
        ["Present Student"], questions, {}, "2026-08-28", set()
    )
    assert rows[0][-1] == 0


def test_date_for_assignment_uses_lesson_prefix_not_today():
    schedule = pd.DataFrame([
        {"lesson": "0.2", "exit_ticket_date": "8/26/2026"},
        {"lesson": "1.8", "exit_ticket_date": 46276},
    ])

    assert date_for_assignment(schedule, "0.2 Exit Ticket.pdf") == "2026-08-26"
    assert (
        date_for_assignment(schedule, "1.8 Exit Ticket - Back Side.pdf")
        == "2026-09-11"
    )
    assert date_for_assignment(schedule, "9.9 Exit Ticket.pdf") is None
