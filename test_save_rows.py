"""Focused tests for the grader's narrow Google Sheets writes."""

import ast
from pathlib import Path

import gspread

from grader import SCORE_COLUMNS, merge_score_rows


class FakeWorksheet:
    def __init__(self, values):
        self.values = values
        self.updates = []
        self.appends = []

    def get_all_values(self):
        return self.values

    def batch_update(self, updates, value_input_option):
        self.updates.append((updates, value_input_option))

    def append_rows(self, rows, value_input_option):
        self.appends.append((rows, value_input_option))


def save_with_fake_sheet(values, incoming):
    # Import only the function: importing app.py would start Streamlit and
    # connect to the teacher's live Google Sheet during a unit test.
    app_path = Path(__file__).with_name("app.py")
    module = ast.parse(app_path.read_text())
    function = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "save_rows"
    )
    namespace = {"gspread": gspread, "SCORE_COLUMNS": SCORE_COLUMNS,
                 "merge_score_rows": merge_score_rows}
    worksheet = FakeWorksheet(values)
    namespace["google_clients"] = lambda: (type("Sheets", (), {
        "worksheet": lambda self, name: worksheet,
    })(), None)
    cleared = []
    namespace["load_sheet"] = type("Cache", (), {
        "clear": lambda self: cleared.append(True),
    })()
    annotations = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=[annotations, function], type_ignores=[])
    ), str(app_path), "exec"), namespace)
    namespace["save_rows"](incoming)
    return worksheet, cleared


def test_only_changed_score_row_is_written():
    old = ["Student One", "S-ID.A.1", "1.1 Exit Ticket", "2026-08-31", "1", "5", "2"]
    untouched = ["Student Two", "S-ID.A.1", "1.1 Exit Ticket", "2026-08-31", "1", "5", "4"]
    incoming = ["Student One", "S-ID.A.1", "1.1 Exit Ticket", "2026-08-31", "1", 5.0, 3.0]
    worksheet, cleared = save_with_fake_sheet([SCORE_COLUMNS, old, untouched], [incoming])
    assert worksheet.updates == [([{"range": "A2:G2", "values": [incoming]}], "USER_ENTERED")]
    assert worksheet.appends == []
    assert cleared == [True]


def test_identical_numeric_grade_does_not_rewrite_sheet():
    old = ["Student One", "S-ID.A.1", "1.1 Exit Ticket", "2026-08-31", "1", "5", "2"]
    incoming = ["Student One", "S-ID.A.1", "1.1 Exit Ticket", "2026-08-31", "1", 5.0, 2.0]
    worksheet, cleared = save_with_fake_sheet([SCORE_COLUMNS, old], [incoming])
    assert worksheet.updates == []
    assert worksheet.appends == []
    assert cleared == []


def test_blank_last_cell_is_updated_in_place_without_duplicate():
    old_without_trailing_blank = [
        "Student One", "S-ID.A.1", "1.1 Exit Ticket", "2026-08-31", "1", "5",
    ]
    incoming = ["Student One", "S-ID.A.1", "1.1 Exit Ticket", "2026-08-31", "1", 5.0, 0.0]
    worksheet, _ = save_with_fake_sheet([SCORE_COLUMNS, old_without_trailing_blank], [incoming])
    assert worksheet.updates == [([{"range": "A2:G2", "values": [incoming]}], "USER_ENTERED")]
    assert worksheet.appends == []


def test_new_student_score_is_appended_without_rewriting_others():
    old = ["Student One", "S-ID.A.1", "1.1 Exit Ticket", "2026-08-31", "1", "5", "2"]
    incoming = ["Student Two", "S-ID.A.1", "1.1 Exit Ticket", "2026-08-31", "1", 5.0, 4.0]
    worksheet, cleared = save_with_fake_sheet([SCORE_COLUMNS, old], [incoming])
    assert worksheet.updates == []
    assert worksheet.appends == [([incoming], "USER_ENTERED")]
    assert cleared == [True]
