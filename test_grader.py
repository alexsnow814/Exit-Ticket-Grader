import pandas as pd

from grader import assignment_key, build_score_rows, find_student, questions_for_assignment


def test_assignment_key_matches_answer_key():
    assert assignment_key("1.1 Exit Ticket.pdf") == assignment_key(
        "1.1 Exit Ticket Answer Key.pdf"
    )


def test_find_student_exact_and_fuzzy():
    roster = ["Nadir Al-Asadi", "Carlos Castillo Aguirre"]
    assert find_student("Student: Nadir Al-Asadi", roster) == ("Nadir Al-Asadi", 100)
    assert find_student("CarIos Castillo Aguirre", roster)[0] == "Carlos Castillo Aguirre"


def test_question_filter_and_missing_student_zero():
    questions = pd.DataFrame([
        {"course_level": "Regular", "exit_ticket": "1.1 Exit Ticket", "question": "5", "standard": "S-ID.A.2", "possible_points": 5},
        {"course_level": "Honors", "exit_ticket": "1.1 Exit Ticket", "question": "5", "standard": "S-ID.A.2", "possible_points": 5},
    ])
    selected = questions_for_assignment(questions, "1.1 Exit Ticket.pdf", "Regular")
    rows = build_score_rows(["Student One", "Student Two"], selected, {"Student One": {"5": 4}})
    assert rows[0][-1] == 4
    assert rows[1][-1] == 0


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

    saved_from_batch = build_score_rows(["Student One"], batch_questions, grades)
    saved_from_refresh = build_score_rows(["Student One"], refreshed_questions, grades)

    assert [row[-1] for row in saved_from_batch] == [4.5, 3]
    assert [row[-1] for row in saved_from_refresh] == [0, 0]
