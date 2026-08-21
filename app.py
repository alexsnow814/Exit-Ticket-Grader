from __future__ import annotations

import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import AuthorizedSession
import gspread

from grader import (
    SCORE_COLUMNS,
    assignment_key,
    build_score_rows,
    identify_pages,
    questions_for_assignment,
    render_page,
)


SPREADSHEET_ID = "1w6iWAYavC3UWK8iuazZFm_KkYla-qAbhOWe7nPfMzSo"
INCOMING_FOLDER_ID = "1Bf3kacbRX7UP5xmR8mahiTU2fTFa9mh6"
ANSWER_KEY_FOLDER_ID = "1kpaqfrxtGRsk0yBmpy31MGWwyOqaaWx6"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


st.set_page_config(page_title="Exit Ticket Grader", page_icon="📝", layout="wide")


@st.cache_resource
def google_clients():
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    sheets = gspread.authorize(credentials).open_by_key(SPREADSHEET_ID)
    drive = AuthorizedSession(credentials)
    return sheets, drive


@st.cache_data(ttl=30)
def list_pdfs(folder_id: str):
    _, drive = google_clients()
    response = drive.get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": f"'{folder_id}' in parents and trashed = false and mimeType = 'application/pdf'",
            "fields": "files(id,name,modifiedTime,size)",
            "orderBy": "name",
            "pageSize": 1000,
        },
    )
    response.raise_for_status()
    return response.json().get("files", [])


@st.cache_data(ttl=300, show_spinner=False)
def download_file(file_id: str) -> bytes:
    _, drive = google_clients()
    response = drive.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"alt": "media"},
    )
    response.raise_for_status()
    return response.content


@st.cache_data(ttl=60)
def load_sheet(name: str) -> pd.DataFrame:
    sheets, _ = google_clients()
    return pd.DataFrame(sheets.worksheet(name).get_all_records())


@st.cache_data(show_spinner="Reading student names from the scanned pages…")
def cached_identify(pdf_bytes: bytes, students: tuple[str, ...]):
    return identify_pages(pdf_bytes, list(students))


def save_rows(rows: list[list[object]]):
    sheets, _ = google_clients()
    worksheet = sheets.worksheet("exit_ticket_scores")
    current = worksheet.get_all_values()
    header = current[0] if current else SCORE_COLUMNS
    data = current[1:] if current else []
    header_map = {name: index for index, name in enumerate(header)}
    if not set(SCORE_COLUMNS).issubset(header_map):
        raise ValueError("exit_ticket_scores has unexpected column headings")

    key_columns = ["student", "exit_ticket", "question"]
    positions = {
        tuple(row[header_map[column]] for column in key_columns): index
        for index, row in enumerate(data)
        if len(row) >= len(header)
    }
    for new_row in rows:
        row_by_name = dict(zip(SCORE_COLUMNS, new_row))
        key = tuple(str(row_by_name[column]) for column in key_columns)
        output = [row_by_name.get(column, "") for column in header]
        if key in positions:
            data[positions[key]] = output
        else:
            positions[key] = len(data)
            data.append(output)

    worksheet.update([header, *data], value_input_option="USER_ENTERED")
    load_sheet.clear()


def pdf_page_count(pdf_bytes: bytes) -> int:
    import fitz

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    count = document.page_count
    document.close()
    return count


def initialize_batch(
    scan,
    roster_scope,
    scan_bytes,
    all_students,
    expected_students,
    questions,
):
    matches = cached_identify(scan_bytes, tuple(all_students))
    st.session_state.batch_key = (scan["id"], roster_scope)
    st.session_state.page_position = 0
    st.session_state.page_students = {
        match.page_index: match.student for match in matches
    }
    st.session_state.page_confidence = {
        match.page_index: match.confidence for match in matches
    }
    st.session_state.grades = {}
    st.session_state.matches = matches
    st.session_state.questions = questions.to_dict("records")
    st.session_state.expected_students = expected_students
    if roster_scope == "All students":
        st.session_state.visible_page_indices = [
            match.page_index for match in matches
        ]
    else:
        expected_set = set(expected_students)
        st.session_state.visible_page_indices = [
            match.page_index
            for match in matches
            if match.student in expected_set
        ]


st.title("📝 Exit Ticket Grader")
st.caption("Review a scanned class batch, assign each page to a student, and save scores.")

with st.sidebar:
    st.header("Data")
    st.caption(
        "Students and question settings come directly from Google Sheets. "
        "Use refresh after editing the sheet or adding Drive files."
    )
    if st.button("Refresh Google data", use_container_width=True):
        load_sheet.clear()
        list_pdfs.clear()
        download_file.clear()
        cached_identify.clear()
        st.rerun()

try:
    students_df = load_sheet("students")
    questions_df = load_sheet("exit_ticket_questions")
    scans = list_pdfs(INCOMING_FOLDER_ID)
    answer_keys = list_pdfs(ANSWER_KEY_FOLDER_ID)
except Exception as exc:
    st.error("Google Drive or the grading spreadsheet could not be reached.")
    st.caption(f"Connection detail: {exc}")
    st.stop()

if students_df.empty or not {"student", "period"}.issubset(students_df.columns):
    st.error("The students tab needs student and period columns.")
    st.stop()
if not scans:
    st.info("No PDF files were found in Incoming Scans.")
    st.stop()

controls = st.columns(2)
scan_name = controls[0].selectbox("Incoming scan", [item["name"] for item in scans])
periods = sorted(students_df["period"].dropna().unique(), key=str)
scope_options = ["All students", *[f"Period {period}" for period in periods]]
roster_scope = controls[1].selectbox(
    "Students expected in this scan",
    scope_options,
    help="This controls who receives a zero if missing. Name recognition always checks the complete roster.",
)

scan = next(item for item in scans if item["name"] == scan_name)
all_students = sorted(students_df["student"].dropna().astype(str).unique())
if roster_scope == "All students":
    expected_students = all_students
else:
    selected_period = roster_scope.removeprefix("Period ")
    expected_students = sorted(
        students_df.loc[
            students_df["period"].astype(str) == selected_period, "student"
        ].dropna().astype(str).unique()
    )
questions = questions_for_assignment(questions_df, scan_name)
scan_bytes = download_file(scan["id"])
answer_key = next(
    (item for item in answer_keys if assignment_key(item["name"]) == assignment_key(scan_name)),
    None,
)

if questions.empty:
    st.warning(f"No questions match {scan_name} in exit_ticket_questions.")
if answer_key is None:
    st.warning("No matching answer key was found.")

batch_key = (scan["id"], roster_scope)
if st.button("Process this batch", type="primary"):
    initialize_batch(
        scan,
        roster_scope,
        scan_bytes,
        all_students,
        expected_students,
        questions,
    )

if st.session_state.get("batch_key") != batch_key:
    st.info(
        "Choose the scan and expected-student group, then press **Process this batch**."
    )
    st.stop()

matches = st.session_state.matches
visible_page_indices = st.session_state.visible_page_indices
if not visible_page_indices:
    st.warning(
        f"No pages were automatically matched to {roster_scope}. Choose All students "
        "to review and correct unmatched pages."
    )
    st.stop()
page_count = len(visible_page_indices)
page_position = min(st.session_state.get("page_position", 0), page_count - 1)
page_index = visible_page_indices[page_position]
assigned_students = {value for value in st.session_state.page_students.values() if value}
expected_students = st.session_state.expected_students
missing_students = [student for student in expected_students if student not in assigned_students]
expected_set = set(expected_students)
assigned_expected_students = [
    value
    for value in st.session_state.page_students.values()
    if value in expected_set
]
duplicates = sorted(
    student
    for student in set(assigned_expected_students)
    if assigned_expected_students.count(student) > 1
)

st.progress(
    (page_position + 1) / page_count,
    text=f"{roster_scope}: student {page_position + 1} of {page_count}",
)
left, right = st.columns([1.35, 1], gap="large")

with left:
    display = st.radio("Document", ["Student work", "Answer key"], horizontal=True)
    if display == "Answer key" and answer_key:
        key_bytes = download_file(answer_key["id"])
        st.image(
            render_page(key_bytes, min(page_index, pdf_page_count(key_bytes) - 1)),
            use_container_width=True,
        )
    else:
        st.image(render_page(scan_bytes, page_index), use_container_width=True)

with right:
    confidence = st.session_state.page_confidence.get(page_index, 0)
    options = ["— Unmatched / skip —", *expected_students]
    current_student = st.session_state.page_students.get(page_index)
    selected = st.selectbox(
        "Student on this page",
        options,
        index=options.index(current_student) if current_student in options else 0,
        key=f"student_page_{page_index}_{scan['id']}",
    )
    selected_student = None if selected.startswith("—") else selected
    st.session_state.page_students[page_index] = selected_student
    st.caption(f"Automatic name-match confidence: {confidence}%")

    if selected_student:
        student_grades = dict(st.session_state.grades.get(selected_student, {}))
        for question in st.session_state.questions:
            question_id = str(question["question"])
            possible = float(question["possible_points"])
            student_grades[question_id] = st.number_input(
                f"Question {question_id} · {question['standard']} (/{possible:g})",
                min_value=0.0,
                max_value=possible,
                value=float(student_grades.get(question_id, 0)),
                step=0.5,
                key=f"grade_{scan['id']}_{selected_student}_{question_id}",
            )
        # Reassign the top-level object so Streamlit persists the edited values
        # even after this student's widgets leave the page during navigation.
        all_grades = dict(st.session_state.grades)
        all_grades[selected_student] = student_grades
        st.session_state.grades = all_grades
    else:
        st.info("Select a student before entering grades for this page.")

    previous, next_page = st.columns(2)
    if previous.button("← Previous", disabled=page_position == 0, use_container_width=True):
        st.session_state.page_position = page_position - 1
        st.rerun()
    if next_page.button("Next →", disabled=page_position == page_count - 1, use_container_width=True):
        st.session_state.page_position = page_position + 1
        st.rerun()

st.divider()
st.subheader("Batch summary")
summary_a, summary_b, summary_c = st.columns(3)
summary_a.metric("Pages in view", page_count)
summary_b.metric("Matched students", len(set(assigned_expected_students)))
summary_c.metric("Missing students", len(missing_students))
if duplicates:
    st.error("Assigned to multiple pages: " + ", ".join(duplicates))
if missing_students:
    with st.expander("Students who will receive zeroes"):
        st.write("\n".join(f"• {student}" for student in missing_students))

entered_points = sum(
    float(points)
    for student_grades in st.session_state.grades.values()
    for points in student_grades.values()
)
st.caption(f"Entered points currently retained for this batch: {entered_points:g}")

confirm = st.checkbox(
    "I reviewed the page assignments. Save entered grades and award 0 to missing students."
)
if st.button("Save and finalize batch", type="primary", disabled=not confirm or bool(duplicates)):
    try:
        # Save against the same immutable question snapshot used to render the
        # inputs. A sheet refresh must not change the lookup keys mid-batch.
        batch_questions = pd.DataFrame(st.session_state.questions)
        score_rows = build_score_rows(
            expected_students, batch_questions, st.session_state.grades
        )
        save_rows(score_rows)
    except Exception as exc:
        st.error("Scores could not be saved. Your page assignments and grades remain on screen.")
        st.caption(f"Connection detail: {exc}")
    else:
        st.success(
            f"Saved {len(score_rows)} question scores for {roster_scope.lower()}."
        )
