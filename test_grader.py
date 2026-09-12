import pandas as pd

from grader import (
    MANUAL_QUESTION,
    assignment_key,
    build_manual_score_rows,
    build_score_rows,
    date_for_assignment,
    find_student,
    grade_count,
    grades_for_assignment,
    mapped_score_keys,
    merge_score_rows,
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


def test_extra_copy_stays_unassigned_for_manual_student_selection():
    roster = ["Wilson Example", "Extraordinary Student"]
    text = "1.4 Exit Ticket  Extra  Calculate the median and explain your work."
    assert find_student(text, roster) == (None, 100)


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
    assert [row[-1] for row in saved_from_refresh] == ["", ""]


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


def test_unentered_present_student_remains_blank():
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
    assert rows[0][-1] == ""

    zero_rows = build_score_rows(
        ["Present Student"],
        questions,
        {"Present Student": {"1": 0}},
        "2026-08-28",
        set(),
    )
    assert zero_rows[0][-1] == 0.0


def test_existing_numeric_scores_restore_but_blank_and_ae_do_not():
    scores = pd.DataFrame([
        {"student": "Student One", "exit_ticket": "1.1 Exit Ticket", "question": "1", "awarded_points": 0},
        {"student": "Student One", "exit_ticket": "1.1 Exit Ticket", "question": "2", "awarded_points": ""},
        {"student": "Student Two", "exit_ticket": "1.1 Exit Ticket", "question": "1", "awarded_points": "AE"},
        {"student": "Student Three", "exit_ticket": "1.2 Exit Ticket", "question": "1", "awarded_points": 4},
    ])

    assert grades_for_assignment(scores, "1.1 Exit Ticket.pdf") == {
        "Student One": {"1": 0.0}
    }


def test_mapped_questions_display_on_new_ticket_but_restore_and_save_old_scores():
    questions = pd.DataFrame([
        {
            "exit_ticket": "1.2 Exit Ticket",
            "save_to_exit_ticket": "",
            "question": "7a",
            "standard": "S-ID.A.2",
            "possible_points": 5,
        },
        {
            "exit_ticket": "1.2 Exit Ticket",
            "save_to_exit_ticket": "1.1 Exit Ticket",
            "question": "7b",
            "standard": "S-ID.A.2",
            "possible_points": 5,
        },
    ])
    scores = pd.DataFrame([
        {"student": "Student One", "exit_ticket": "1.2 Exit Ticket", "question": "7a", "awarded_points": 3},
        {"student": "Student One", "exit_ticket": "1.1 Exit Ticket", "question": "7b", "awarded_points": 4},
    ])

    selected = questions_for_assignment(questions, "1.2 Exit Ticket.pdf")
    assert grades_for_assignment(scores, "1.2 Exit Ticket.pdf", selected) == {
        "Student One": {"7a": 3.0, "7b": 4.0}
    }
    rows = build_score_rows(
        ["Student One"], selected, {"Student One": {"7a": 3, "7b": 5}}, "2026-09-01"
    )
    assert [row[2] for row in rows] == ["1.2 Exit Ticket", "1.1 Exit Ticket"]
    assert mapped_score_keys(["Student One"], selected) == {
        ("Student One", "1.1 Exit Ticket", "7b")
    }


def test_ungraded_mapped_question_does_not_overwrite_old_score_with_absent():
    questions = pd.DataFrame([
        {
            "exit_ticket": "1.2 Exit Ticket",
            "save_to_exit_ticket": "1.1 Exit Ticket",
            "question": "7b",
            "standard": "S-ID.A.2",
            "possible_points": 5,
        }
    ])
    assert build_score_rows(
        ["Student One"], questions, {}, "2026-09-01", {"Student One"}
    ) == []


def test_mapped_merge_updates_only_awarded_points_and_uses_one_canonical_row():
    header = [
        "student", "standard", "exit_ticket", "exit_ticket_date",
        "question", "possible_points", "awarded_points",
    ]
    current = [[
        "Student One", "OLD-STANDARD", "1.1 Exit Ticket", "2026-08-31",
        "7b", "5", "3",
    ]]
    incoming = [[
        "Student One", "NEW-STANDARD", "1.1 Exit Ticket", "2026-09-01",
        "7b", 5, 4,
    ]]
    protected = {("Student One", "1.1 Exit Ticket", "7b")}
    assert merge_score_rows(header, current, incoming, protected) == [[
        "Student One", "OLD-STANDARD", "1.1 Exit Ticket", "2026-08-31",
        "7b", "5", 4,
    ]]

    missing = [[
        "Student Two", "S-ID.A.2", "1.1 Exit Ticket", "2026-09-01",
        "7b", 5, 4,
    ]]
    merged = merge_score_rows(
        header, current, missing,
        {("Student Two", "1.1 Exit Ticket", "7b")},
    )
    assert merged[-1] == missing[0]


def test_new_mapped_score_uses_the_original_ticket_date():
    questions = pd.DataFrame([
        {
            "exit_ticket": "1.2 Exit Ticket",
            "save_to_exit_ticket": "1.1 Exit Ticket",
            "question": "7b",
            "standard": "S-ID.A.2",
            "possible_points": 5,
        }
    ])
    rows = build_score_rows(
        ["New Student"],
        questions,
        {"New Student": {"7b": 5}},
        "2026-09-01",
        ticket_dates={assignment_key("1.1 Exit Ticket"): "2026-08-31"},
    )
    assert rows[0][2] == "1.1 Exit Ticket"
    assert rows[0][3] == "2026-08-31"
    assert rows[0][-1] == 5.0


def test_grade_count_uses_the_supplied_saved_snapshot():
    required = ["1", "2"]
    saved = {"Student One": {"1": 4.0}}
    live_edits = {"Student One": {"1": 4.0, "2": 3.0}}

    assert grade_count(saved, "Student One", required) == 1
    assert grade_count(live_edits, "Student One", required) == 2
    assert grade_count(saved, None, required) == 0


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
