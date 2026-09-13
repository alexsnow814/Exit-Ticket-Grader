from __future__ import annotations

import base64

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import AuthorizedSession
import gspread

from grader import (
    MANUAL_QUESTION,
    SCORE_COLUMNS,
    assignment_key,
    build_manual_score_rows,
    build_score_rows,
    date_for_assignment,
    grades_for_assignment,
    identify_pages,
    mapped_score_keys,
    merge_score_rows,
    question_score_ticket,
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

st.markdown(
    """
    <style>
    .hold-zoom {
        width: 100%;
        overflow: visible;
        position: relative;
        z-index: 1;
        border: 1px solid rgba(128, 128, 128, 0.25);
        border-radius: 0.45rem;
        background: white;
        cursor: zoom-in;
        touch-action: manipulation;
        -webkit-touch-callout: none;
        user-select: none;
    }
    .hold-zoom img {
        display: block;
        width: 100%;
        height: auto;
        transition: transform 120ms ease-out;
        transform-origin: center center;
        -webkit-user-drag: none;
    }
    .hold-zoom:active img,
    .hold-zoom img:active {
        transform: scale(1.5);
        transform-origin: top left;
        box-shadow: 0 0.5rem 1.5rem rgba(0, 0, 0, 0.3);
    }
    .hold-zoom:active {
        z-index: 1000;
    }
    .hold-zoom-hint {
        margin-top: 0.2rem;
        color: rgba(128, 128, 128, 0.9);
        font-size: 0.72rem;
        text-align: center;
    }
    @media (max-width: 640px) {
        .block-container {
            padding-left: 0.65rem;
            padding-right: 0.65rem;
        }
        .st-key-grading_workspace,
        .st-key-grading_workspace div[data-testid="stVerticalBlock"],
        .st-key-grading_workspace div[data-testid="stColumn"] {
            overflow: visible !important;
        }
        .st-key-grading_workspace div[data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            align-items: flex-start !important;
            gap: 0.35rem !important;
        }
        .st-key-grading_workspace div[data-testid="stColumn"]:nth-child(1) {
            flex: 2 1 0 !important;
            width: 66.6667% !important;
            min-width: 0 !important;
            position: relative !important;
            z-index: 2 !important;
        }
        .st-key-grading_workspace div[data-testid="stColumn"]:nth-child(2) {
            flex: 1 1 0 !important;
            width: 33.3333% !important;
            min-width: 0 !important;
            position: relative !important;
            z-index: 1 !important;
        }
        div[data-testid="stNumberInput"] label p {
            font-size: 0.82rem;
        }
        .st-key-grading_workspace div[data-testid="stNumberInput"] input {
            min-width: 0 !important;
            padding-left: 0.35rem !important;
            padding-right: 0.35rem !important;
        }
        .st-key-grading_workspace button[data-testid="stNumberInputStepDown"],
        .st-key-grading_workspace button[data-testid="stNumberInputStepUp"] {
            display: none !important;
        }
        .st-key-save_status_row div[data-testid="stColumn"] {
            flex: 1 1 0 !important;
            width: 50% !important;
            min-width: 0 !important;
        }
        .st-key-save_status_row p {
            font-size: 0.72rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def save_rows(
    rows: list[list[object]],
    update_existing_only: set[tuple[str, str, str]] | None = None,
):
    sheets, _ = google_clients()
    worksheet = sheets.worksheet("exit_ticket_scores")
    current = worksheet.get_all_values()
    header = current[0] if current else SCORE_COLUMNS
    data = current[1:] if current else []
    header_map = {name: index for index, name in enumerate(header)}
    if not set(SCORE_COLUMNS).issubset(header_map):
        raise ValueError("exit_ticket_scores has unexpected column headings")

    data = merge_score_rows(header, data, rows, update_existing_only)

    worksheet.update([header, *data], value_input_option="USER_ENTERED")
    load_sheet.clear()


def pdf_page_count(pdf_bytes: bytes) -> int:
    import fitz

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    count = document.page_count
    document.close()
    return count


def show_zoomable_page(png_bytes: bytes):
    """Show a page that enlarges only while it is pressed or clicked."""
    encoded = base64.b64encode(png_bytes).decode("ascii")
    st.markdown(
        f"""
        <div class="hold-zoom" title="Press and hold to magnify"
             ontouchstart="">
            <img src="data:image/png;base64,{encoded}"
                 alt="PDF page" draggable="false">
        </div>
        <div class="hold-zoom-hint">Press and hold the page to magnify</div>
        """,
        unsafe_allow_html=True,
    )


def enable_mobile_grade_inputs():
    """Make grade fields replace-on-type and request a decimal phone keypad."""
    components.html(
        """
        <script>
        const doc = window.parent.document;

        function enhanceGradeInputs() {
          const inputs = doc.querySelectorAll(
            '.st-key-grading_workspace div[data-testid="stNumberInput"] input'
          );

          inputs.forEach((input) => {
            input.setAttribute('inputmode', 'decimal');
            input.inputMode = 'decimal';
            input.setAttribute('enterkeyhint', 'done');

            if (input.dataset.gradeInputEnhanced === 'true') return;
            input.dataset.gradeInputEnhanced = 'true';

            const selectCurrentValue = () => {
              window.setTimeout(() => {
                input.focus();
                input.select();
              }, 0);
            };

            input.addEventListener('focus', selectCurrentValue);
            input.addEventListener('touchstart', () => {
              input.setAttribute('inputmode', 'decimal');
              input.inputMode = 'decimal';
            }, {passive: true});
            input.addEventListener('pointerup', (event) => {
              event.preventDefault();
              selectCurrentValue();
            });
          });
        }

        enhanceGradeInputs();
        const observer = new MutationObserver(enhanceGradeInputs);
        observer.observe(doc.body, {childList: true, subtree: true});
        </script>
        """,
        height=0,
    )


def grade_count(
    grades: dict[str, dict[str, float]],
    student: str | None,
    required_questions: list[str],
) -> int:
    """Count required grades in the supplied live or saved snapshot."""
    if not student:
        return 0
    student_grades = grades.get(student, {})
    return sum(question in student_grades for question in required_questions)


def initialize_batch(
    scan,
    roster_scope,
    scan_bytes,
    all_students,
    expected_students,
    questions,
    manual_grading,
    existing_scores,
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
    saved_grades = grades_for_assignment(existing_scores, scan["name"], questions)
    st.session_state.grades = {
        student: dict(student_grades)
        for student, student_grades in saved_grades.items()
    }
    st.session_state.saved_grades = {
        student: dict(student_grades)
        for student, student_grades in saved_grades.items()
    }
    st.session_state.matches = matches
    st.session_state.questions = questions.to_dict("records")
    st.session_state.manual_grading = manual_grading
    st.session_state.manual_possible_points = 5.0
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
            # An unmatched page may be a printed "Extra" copy.  It must stay
            # visible so the teacher can assign it to a student in this period.
            if match.student is None or match.student in expected_set
        ]


st.title("📝 Exit Ticket Grader")
st.caption(
    "Review a scanned class batch, assign each page to a student, and save or resume progress."
)

try:
    students_df = load_sheet("students")
    questions_df = load_sheet("exit_ticket_questions")
    exit_ticket_dates_df = load_sheet("exit_ticket_dates")
    scores_df = load_sheet("exit_ticket_scores")
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
if not {"lesson", "exit_ticket_date"}.issubset(exit_ticket_dates_df.columns):
    st.error("The exit_ticket_dates tab needs lesson and exit_ticket_date columns.")
    st.stop()

controls = st.columns(2)
scan_name = controls[0].selectbox("Incoming scan", [item["name"] for item in scans])
periods = sorted(students_df["period"].dropna().unique(), key=str)
scope_options = ["All students", *[f"Period {period}" for period in periods]]
roster_scope = controls[1].selectbox(
    "Students expected in this scan",
    scope_options,
    help="This controls who receives AE if missing. Name recognition always checks the complete roster.",
)

scan = next(item for item in scans if item["name"] == scan_name)
exit_ticket_date = date_for_assignment(exit_ticket_dates_df, scan_name)
if exit_ticket_date is None:
    st.error(
        f"No scheduled date was found for {scan_name}. Add its lesson number and "
        "date to the exit_ticket_dates tab before saving grades."
    )
    st.stop()
st.caption(f"Exit ticket date: {pd.Timestamp(exit_ticket_date):%B %-d, %Y}")
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
    st.warning(
        f"No questions match {scan_name} in exit_ticket_questions. "
        "This scan will use manual-total grading."
    )
if answer_key is None:
    st.warning(
        "No matching answer key was found. Student work is still available, "
        "and this scan will use manual-total grading."
    )

batch_key = (scan["id"], roster_scope)
if st.button("Process this batch", type="primary"):
    initialize_batch(
        scan,
        roster_scope,
        scan_bytes,
        all_students,
        expected_students,
        questions,
        questions.empty or answer_key is None,
        scores_df,
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
        f"No pages were found for {roster_scope}. Choose All students to review "
        "pages matched to a different period."
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
    text=f"{roster_scope}: page {page_position + 1} of {page_count}",
)
document_options = ["Student work"]
if answer_key:
    document_options.append("Answer key")
document_view_key = f"document_view_{scan['id']}"
display = st.session_state.get(document_view_key, "Student work")
if display not in document_options:
    display = "Student work"

previous, next_page = st.columns(2)
go_previous = previous.button(
    "← Previous", disabled=page_position == 0, use_container_width=True
)
go_next = next_page.button(
    "Next →", disabled=page_position == page_count - 1, use_container_width=True
)

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
if current_student is None:
    st.caption(
        "No student name was detected. If this is an Extra copy, choose the "
        "student who completed it."
    )
else:
    st.caption(f"Automatic name-match confidence: {confidence}%")

with st.container(key="grading_workspace"):
    work_column, grade_column = st.columns(
        [2, 1], gap="small", vertical_alignment="top"
    )

    with work_column:
        if display == "Answer key" and answer_key:
            key_bytes = download_file(answer_key["id"])
            page_png = render_page(
                key_bytes, min(page_index, pdf_page_count(key_bytes) - 1)
            )
        else:
            page_png = render_page(scan_bytes, page_index)
        show_zoomable_page(page_png)
        with st.container(key="save_status_row"):
            save_area, status_area = st.columns([1, 1])
            save_progress = save_area.button(
                "Save",
                type="primary",
                use_container_width=True,
                disabled=bool(duplicates),
            )
            student_status = status_area.empty()
        st.radio(
            "Document",
            document_options,
            horizontal=True,
            key=document_view_key,
        )

    with grade_column:
        if selected_student:
            student_grades = dict(st.session_state.grades.get(selected_student, {}))
            if st.session_state.manual_grading:
                possible = st.number_input(
                    "Total possible points",
                    min_value=0.5,
                    value=float(st.session_state.manual_possible_points),
                    step=0.5,
                    format="%.2f",
                    key=f"manual_possible_{scan['id']}",
                    help="Used for every student's manual-total score in this batch.",
                )
                st.session_state.manual_possible_points = possible
                saved_grade = student_grades.get(MANUAL_QUESTION)
                current_grade = (
                    min(float(saved_grade), possible)
                    if saved_grade is not None
                    else None
                )
                entered_grade = st.number_input(
                    f"Manual grade (/{possible:g})",
                    min_value=0.0,
                    max_value=possible,
                    value=current_grade,
                    step=0.5,
                    format="%.2f",
                    placeholder="Ungraded",
                    key=f"manual_grade_{scan['id']}_{selected_student}",
                )
                if entered_grade is None:
                    student_grades.pop(MANUAL_QUESTION, None)
                else:
                    student_grades[MANUAL_QUESTION] = entered_grade
            else:
                for question in st.session_state.questions:
                    question_id = str(question["question"])
                    possible = float(question["possible_points"])
                    entered_grade = st.number_input(
                        f"{question_id} (/{possible:g})",
                        min_value=0.0,
                        max_value=possible,
                        value=(
                            float(student_grades[question_id])
                            if question_id in student_grades
                            else None
                        ),
                        step=0.5,
                        format="%.2f",
                        placeholder="Ungraded",
                        key=f"grade_{scan['id']}_{selected_student}_{question_id}",
                    )
                    if entered_grade is None:
                        student_grades.pop(question_id, None)
                    else:
                        student_grades[question_id] = entered_grade
            # Reassign the top-level object so Streamlit persists the edited values
            # even after this student's widgets leave the page during navigation.
            all_grades = dict(st.session_state.grades)
            all_grades[selected_student] = student_grades
            st.session_state.grades = all_grades
        else:
            st.info("Select a student before entering grades for this page.")

required_questions = (
    [MANUAL_QUESTION]
    if st.session_state.manual_grading
    else [str(question["question"]) for question in st.session_state.questions]
)


def required_for_student(student: str | None) -> list[str]:
    return required_questions


assigned_unique_students = sorted(set(assigned_expected_students))
graded_students = [
    student
    for student in assigned_unique_students
    if grade_count(st.session_state.grades, student, required_for_student(student))
    == len(required_for_student(student))
]
ungraded_students = [
    student for student in assigned_unique_students if student not in graded_students
]

enable_mobile_grade_inputs()

if save_progress:
    try:
        if st.session_state.manual_grading:
            score_rows = build_manual_score_rows(
                expected_students,
                scan_name,
                st.session_state.manual_possible_points,
                st.session_state.grades,
                exit_ticket_date,
                set(missing_students),
            )
        else:
            batch_questions = pd.DataFrame(st.session_state.questions)
            score_ticket_dates = {}
            for question in st.session_state.questions:
                score_ticket = question_score_ticket(question)
                score_date = date_for_assignment(
                    exit_ticket_dates_df, f"{score_ticket}.pdf"
                )
                if score_date:
                    score_ticket_dates[assignment_key(score_ticket)] = score_date
            score_rows = build_score_rows(
                expected_students,
                batch_questions,
                st.session_state.grades,
                exit_ticket_date,
                set(missing_students),
            )
            # Apply mapped ticket dates here instead of requiring the imported
            # grader module to accept a newly added keyword argument. Streamlit
            # can hot-reload this file while retaining an older imported
            # grader.py module, which previously made every save fail with an
            # unexpected ticket_dates argument.
            for score_row in score_rows:
                score_row[3] = score_ticket_dates.get(
                    assignment_key(score_row[2]), score_row[3]
                )
        existing_only = (
            set()
            if st.session_state.manual_grading
            else mapped_score_keys(expected_students, batch_questions)
        )
        save_rows(score_rows, existing_only)
    except Exception as exc:
        st.error("Scores could not be saved. Your page assignments and grades remain on screen.")
        st.caption(f"Connection detail: {exc}")
    else:
        st.session_state.saved_grades = {
            student: dict(student_grades)
            for student, student_grades in st.session_state.grades.items()
        }
        st.success(
            f"Progress saved: {len(graded_students)} graded, "
            f"{len(ungraded_students)} still to grade."
        )

selected_required_questions = required_for_student(selected_student)
saved_grade_count = grade_count(
    st.session_state.saved_grades,
    selected_student,
    selected_required_questions,
)
if selected_student and saved_grade_count == len(selected_required_questions):
    student_status.markdown("✅ **Grades saved**")
elif selected_student and saved_grade_count:
    student_status.markdown(
        f"⚠️ **Partially saved**  \n"
        f"{saved_grade_count}/{len(selected_required_questions)} grades saved"
    )
elif selected_student:
    student_status.markdown("**Grades not saved**")
else:
    student_status.markdown("**No saved grades**")

# Navigation is applied only after the current page's widgets have copied their
# values into the persistent grade dictionary above.
if go_previous:
    st.session_state.page_position = page_position - 1
    st.rerun()
if go_next:
    st.session_state.page_position = page_position + 1
    st.rerun()

st.divider()
st.subheader("Batch summary")
summary_a, summary_b, summary_c, summary_d = st.columns(4)
summary_a.metric("Pages in view", page_count)
summary_b.metric("Graded students", len(graded_students))
summary_c.metric("Still to grade", len(ungraded_students))
summary_d.metric("Missing students", len(missing_students))
if duplicates:
    st.error("Assigned to multiple pages: " + ", ".join(duplicates))
if missing_students:
    with st.expander("Students who will receive AE"):
        st.write("\n".join(f"• {student}" for student in missing_students))
