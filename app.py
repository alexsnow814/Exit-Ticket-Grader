from __future__ import annotations

import base64

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import AuthorizedSession
import gspread
from drive_batches import PDF_MIME, combine_pdfs, list_batches, list_children
from grading_views import (
    completion_lists, indexed_pages, lesson_sort_key, required_questions, unit_number,
)

from grader import (
    MANUAL_QUESTION,
    SCORE_COLUMNS,
    assignment_key,
    build_manual_score_rows,
    build_score_rows,
    date_for_assignment,
    find_student,
    grade_count,
    grades_for_assignment,
    identify_pages,
    mapped_score_keys,
    merge_score_rows,
    question_score_ticket,
    questions_for_assignment,
    render_page,
)
from scan_index import (
    INDEX_HEADERS, INDEX_SHEET, file_is_complete, indexed_prefix,
    parse_index, rows_for_pages,
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


def list_pdfs(folder_id: str):
    """Return the current PDF inventory directly from Drive.

    This deliberately is not cached. New scans are commonly uploaded while the
    grader is already open, and a cached folder listing can leave the dropdown
    showing an older inventory even after a Streamlit rerun.
    """
    _, drive = google_clients()
    return [item for item in list_children(drive, folder_id) if item['mimeType'] == PDF_MIME]


@st.cache_data(ttl=300, max_entries=2, show_spinner=False)
def download_file(file_id: str, revision: str = "", size: str = "") -> bytes:
    return fetch_file(file_id)


def fetch_file(file_id: str) -> bytes:
    _, drive = google_clients()
    response = drive.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"alt": "media"},
    )
    response.raise_for_status()
    return response.content


@st.cache_data(max_entries=2, show_spinner="Loading PDFs in this exit-ticket folder…")
def download_batch(files: tuple[tuple[str, str, str], ...]) -> bytes:
    return combine_pdfs([download_file(file_id, revision, size) for file_id, revision, size in files])


@st.cache_data(ttl=60)
def load_sheet(name: str) -> pd.DataFrame:
    sheets, _ = google_clients()
    worksheet = sheets.worksheet(name)
    if name == "exit_ticket_dates":
        # Lesson identifiers such as 1.10 must remain text. get_all_records()
        # reads that displayed value as the number 1.1, which prevents the
        # uploaded 1.10 PDF from matching its scheduled date.
        values = worksheet.get_all_values(value_render_option="FORMATTED_VALUE")
        if not values:
            return pd.DataFrame()
        return pd.DataFrame(values[1:], columns=values[0])
    return pd.DataFrame(worksheet.get_all_records())


OCR_PAGES_PER_RUN = 4


@st.cache_data(show_spinner=False)
def file_page_count(file_id: str, revision: str, size: str) -> int:
    return pdf_page_count(download_file(file_id, revision, size))


@st.cache_data(show_spinner=False)
def identify_file_chunk(file_id: str, revision: str, size: str,
                        start_page: int, stop_page: int):
    """OCR a small page range so a large PDF cannot monopolize one run."""
    return identify_pages(
        download_file(file_id, revision, size), [], start_page, stop_page
    )


def scan_index_worksheet():
    """Create the app's index tab with its existing Sheets credentials."""
    sheets, _ = google_clients()
    created = False
    try:
        worksheet = sheets.worksheet(INDEX_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        try:
            worksheet = sheets.add_worksheet(
                title=INDEX_SHEET, rows=1000, cols=len(INDEX_HEADERS)
            )
            created = True
        except gspread.exceptions.APIError:
            # Another session may have created the tab at the same moment.
            worksheet = sheets.worksheet(INDEX_SHEET)
    if created:
        worksheet.update(
            range_name="A1:H1", values=[INDEX_HEADERS], value_input_option="RAW"
        )
        worksheet.freeze(rows=1)
    return worksheet


@st.cache_data(ttl=60, show_spinner=False)
def load_persistent_scan_index():
    """One sheet read replaces replaying all OCR chunks in a new session."""
    return parse_index(scan_index_worksheet().get_all_values())


def save_index_chunk(ticket_name, pdf_name, version, page_count, matches):
    """Write several OCR chunks in one Sheets request to stay under quota."""
    worksheet = scan_index_worksheet()
    worksheet.append_rows(
        rows_for_pages(ticket_name, pdf_name, version, page_count, matches),
        value_input_option="RAW",
    )
    load_persistent_scan_index.clear()


def indexed_batch_matches(scan: dict, students: tuple[str, ...], file_index=None):
    from grader import PageMatch

    matches = []
    offset = 0
    if file_index is None:
        file_index = st.session_state.get("file_name_index", {})
    for file_id, revision, size in scan["files"]:
        version = (file_id, revision, size)
        file_matches = file_index[version]
        for match in file_matches:
            text = getattr(match, "header_text", None)
            if text is None:
                text = match.ocr_text
            student, confidence = find_student(text, list(students))
            matches.append(PageMatch(
                offset + match.page_index, student, confidence, text,
            ))
        offset += len(file_matches)
    return matches


def prepare_scan_index(scans_to_prepare: list[dict], students: tuple[str, ...]):
    """Use the sheet index; backfill at most four missing pages per rerun."""
    try:
        persistent = load_persistent_scan_index()
    except (gspread.exceptions.APIError, gspread.exceptions.WorksheetNotFound, ValueError) as exc:
        st.warning(f"The scan index is unavailable; using temporary scan memory. Detail: {exc}")
        persistent = None
    if persistent is not None:
        indexed = {}
        pending = st.session_state.setdefault("unwritten_scan_pages", {})
        for scan_number, scan in enumerate(scans_to_prepare, start=1):
            for version, pdf_name in zip(scan["files"], scan["file_names"]):
                if file_is_complete(persistent, version):
                    pending.pop(version, None)
                    continue
                file_id, revision, size = version
                stored = indexed_prefix(persistent, version)
                unwritten = [
                    match for match in pending.get(version, [])
                    if match.page_index >= len(stored)
                ]
                completed = [*stored, *unwritten]
                total_pages = stored[0].page_count if stored else file_page_count(
                    file_id, revision, size
                )
                stop_page = min(total_pages, len(completed) + OCR_PAGES_PER_RUN)
                st.progress(
                    len(completed) / total_pages,
                    text=(f"Reading {scan['name']}: pages {len(completed) + 1}–"
                          f"{stop_page} of {total_pages} "
                          f"(folder {scan_number} of {len(scans_to_prepare)})"),
                )
                with st.spinner("Reading student names from these pages…"):
                    next_pages = identify_file_chunk(
                        file_id, revision, size, len(completed), stop_page
                    )
                    pending[version] = [*unwritten, *next_pages]
                    st.session_state.unwritten_scan_pages = pending
                    if len(pending[version]) >= 16 or stop_page == total_pages:
                        save_index_chunk(
                            scan["name"], pdf_name, version, total_pages,
                            pending[version],
                        )
                        pending.pop(version, None)
                        st.session_state.unwritten_scan_pages = pending
                st.rerun()
            file_index = {
                version: indexed_prefix(persistent, version)
                for version in scan["files"]
            }
            indexed[scan["id"]] = indexed_batch_matches(
                scan, students, file_index
            )
        st.session_state.scan_name_index = indexed
        return indexed

    # A Sheets setup/access problem must not make existing grading unusable.
    indexed = st.session_state.setdefault("scan_name_index", {})
    file_index = st.session_state.setdefault("file_name_index", {})
    for scan_number, scan in enumerate(scans_to_prepare, start=1):
        if scan["id"] in indexed:
            continue
        for version in scan["files"]:
            file_id, revision, size = version
            total_pages = file_page_count(file_id, revision, size)
            completed = file_index.get(version, [])
            if len(completed) < total_pages:
                stop_page = min(total_pages, len(completed) + OCR_PAGES_PER_RUN)
                st.progress(
                    len(completed) / total_pages,
                    text=(f"Reading {scan['name']}: pages {len(completed) + 1}–"
                          f"{stop_page} of {total_pages} "
                          f"(folder {scan_number} of {len(scans_to_prepare)})"),
                )
                with st.spinner("Reading student names from these pages…"):
                    next_pages = identify_file_chunk(
                        file_id, revision, size, len(completed), stop_page
                    )
                    file_index[version] = [*completed, *next_pages]
                    st.session_state.file_name_index = file_index
                st.rerun()
        indexed[scan["id"]] = indexed_batch_matches(scan, students)
        st.session_state.scan_name_index = indexed
        if scan_number < len(scans_to_prepare):
            st.rerun()
    return {scan["id"]: indexed[scan["id"]] for scan in scans_to_prepare}


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


def initialize_batch(
    scan,
    roster_scope,
    all_students,
    expected_students,
    questions,
    manual_grading,
    existing_scores,
):
    matches = st.session_state["scan_name_index"][scan["id"]]
    st.session_state.batch_key = (scan["id"], roster_scope)
    st.session_state.page_position = 0
    st.session_state.page_students = {
        match.page_index: match.student for match in matches
    }
    overrides = st.session_state.get("page_assignment_overrides", {})
    for page_index in st.session_state.page_students:
        key = (scan["id"], page_index)
        if key in overrides:
            st.session_state.page_students[page_index] = overrides[key]
    st.session_state.page_confidence = {
        match.page_index: match.confidence for match in matches
    }
    saved_grades = grades_for_assignment(
        existing_scores, scan["name"], None if manual_grading else questions
    )
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
            # Unmatched pages may be Extra copies assigned during grading.
            if match.student is None or match.student in expected_set
        ]


BATCH_STATE_FIELDS = (
    "page_position", "page_students", "page_confidence", "grades",
    "saved_grades", "matches", "questions", "manual_grading",
    "manual_possible_points", "expected_students", "visible_page_indices",
)


def activate_batch(scan, roster_scope, all_students, expected_students,
                   questions, manual_grading, scores_df):
    target = (scan["id"], roster_scope)
    states = st.session_state.setdefault("batch_states", {})
    previous = st.session_state.get("batch_key")
    if previous and previous != target:
        states[previous] = {
            field: st.session_state.get(field) for field in BATCH_STATE_FIELDS
        }
    if previous == target:
        return
    if target in states:
        for field, value in states[target].items():
            st.session_state[field] = value
        st.session_state.batch_key = target
        return
    initialize_batch(
        scan, roster_scope, all_students, expected_students, questions,
        manual_grading, scores_df,
    )


st.title("📝 Exit Ticket Grader")
st.caption(
    "Review a scanned class batch, assign each page to a student, and save or resume progress."
)

try:
    students_df = load_sheet("students")
    questions_df = load_sheet("exit_ticket_questions")
    exit_ticket_dates_df = load_sheet("exit_ticket_dates")
    scores_df = load_sheet("exit_ticket_scores")
    _, drive = google_clients()
    scans = list_batches(drive, INCOMING_FOLDER_ID)
    answer_keys = list_pdfs(ANSWER_KEY_FOLDER_ID)
except Exception as exc:
    st.error("Google Drive or the grading spreadsheet could not be reached.")
    st.caption(f"Connection detail: {exc}")
    st.stop()

if students_df.empty or not {"student", "period"}.issubset(students_df.columns):
    st.error("The students tab needs student and period columns.")
    st.stop()
if not scans:
    st.info("No PDFs were found in the exit-ticket folders in Incoming Scans.")
    st.stop()
if not {"lesson", "exit_ticket_date"}.issubset(exit_ticket_dates_df.columns):
    st.error("The exit_ticket_dates tab needs lesson and exit_ticket_date columns.")
    st.stop()

view_mode = st.radio(
    "View", ["By exit ticket", "By student", "Unit summary"],
    horizontal=True,
)
periods = sorted(students_df["period"].dropna().unique(), key=str)
scope_options = ["All students", *[f"Period {period}" for period in periods]]
roster_scope = st.selectbox(
    "Students to review",
    scope_options,
    help="This controls whose work appears and who receives AE when a ticket is saved.",
)
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

# Ticket view prepares only the selected folder. Student and unit views build
# their wider index in small page chunks, avoiding a long, resource-heavy run.
matches_by_scan = {}
all_pages = []
states = st.session_state.setdefault("batch_states", {})
def page_student(scan_index, page_index, detected):
    override_key = (scans[scan_index]["id"], page_index)
    overrides = st.session_state.get("page_assignment_overrides", {})
    if override_key in overrides:
        return overrides[override_key]
    if st.session_state.get("batch_key") == (scans[scan_index]["id"], roster_scope):
        return st.session_state.page_students.get(page_index)
    state = states.get((scans[scan_index]["id"], roster_scope))
    if state:
        return state["page_students"].get(page_index)
    return detected

scan_choice = None
navigation_key = None
navigation_pages = None
if view_mode == "By exit ticket":
    scan_choice = st.selectbox(
        "Exit ticket", range(len(scans)),
        format_func=lambda index: scans[index]["name"],
    )
    try:
        matches_by_scan = prepare_scan_index([scans[scan_choice]], tuple(all_students))
    except Exception as exc:
        st.error("Could not read names in this exit-ticket folder. Nothing was saved.")
        st.caption(str(exc))
        st.stop()
elif view_mode == "By student":
    student_choice = st.selectbox("Student", expected_students)
    try:
        matches_by_scan = prepare_scan_index(scans, tuple(all_students))
    except Exception as exc:
        st.error("Could not prepare the student-work index. Nothing was saved.")
        st.caption(str(exc))
        st.stop()
    all_pages = indexed_pages(scans, matches_by_scan)
    navigation_pages = [
        (scan_index, page_index)
        for scan_index, page_index, detected in all_pages
        if page_student(scan_index, page_index, detected) == student_choice
    ]
    navigation_key = f"student_position_{roster_scope}_{student_choice}"
    if not navigation_pages:
        st.info("No scanned page is assigned to this student yet. An Extra page can be assigned in the exit-ticket view.")
        st.stop()
else:
    configured_names = (
        questions_df["exit_ticket"].dropna().astype(str).unique().tolist()
        if "exit_ticket" in questions_df.columns else []
    )
    units = sorted(
        {unit_number(name) for name in
         [*(item["name"] for item in scans), *configured_names]
         if unit_number(name)},
        key=int,
    )
    if not units:
        st.info("No numbered exit tickets were found.")
        st.stop()
    selected_unit = st.selectbox("Unit", units, format_func=lambda unit: f"Unit {unit}")
    unit_indices = [
        index for index, item in enumerate(scans)
        if unit_number(item["name"]) == selected_unit
    ]
    scanned_keys = {assignment_key(scans[index]["name"]) for index in unit_indices}
    summary_tickets = [(index, scans[index]["name"]) for index in unit_indices]
    summary_tickets.extend(
        (None, name) for name in configured_names
        if unit_number(name) == selected_unit
        and assignment_key(name) not in scanned_keys
    )
    summary_tickets.sort(key=lambda item: lesson_sort_key(item[1]))
    st.subheader(f"Unit {selected_unit} grading summary")
    missing_by_scan = {}
    summary_rows = []
    summary_missing = []
    for index, ticket_name in summary_tickets:
        ticket_questions = questions_for_assignment(questions_df, ticket_name)
        has_answer_key = any(
            assignment_key(key["name"]) == assignment_key(ticket_name)
            for key in answer_keys
        )
        manual_ticket = ticket_questions.empty or (index is not None and not has_answer_key)
        required = required_questions(
            pd.DataFrame() if manual_ticket else ticket_questions,
            native_only=True,
        )
        saved = grades_for_assignment(
            scores_df, ticket_name, None if manual_ticket else ticket_questions
        )
        graded, missing = completion_lists(saved, expected_students, required)
        summary_missing.append(missing)
        if index is not None:
            missing_by_scan[index] = set(missing)
        summary_rows.append({
            "Exit ticket": ticket_name,
            "Graded students": len(graded),
            "Still to grade": len(missing),
            "Scans": "Available" if index is not None else "Not uploaded",
        })
    st.dataframe(pd.DataFrame(summary_rows), hide_index=True, use_container_width=True)
    for row, missing in zip(summary_rows, summary_missing):
        if missing:
            with st.expander(f"{row['Exit ticket']}: {len(missing)} still to grade"):
                st.write(", ".join(missing))
    try:
        matches_by_scan = prepare_scan_index(
            [scans[index] for index in unit_indices], tuple(all_students)
        )
    except Exception as exc:
        st.error("Could not prepare the missing-work queue. The summary above is still available.")
        st.caption(str(exc))
        st.stop()
    all_pages = indexed_pages(scans, matches_by_scan)
    navigation_pages = [
        (scan_index, page_index)
        for scan_index, page_index, detected in all_pages
        if scan_index in missing_by_scan
        and (page_student(scan_index, page_index, detected) in missing_by_scan[scan_index]
             or page_student(scan_index, page_index, detected) is None)
    ]
    navigation_key = f"unit_position_{roster_scope}_{selected_unit}"
    st.caption("The review queue includes scanned pages with at least one missing grade, plus unmatched Extra pages. Students without a page appear in the lists above.")
    if not navigation_pages:
        st.success("There are no scanned pages with missing grades in this unit.")
        st.stop()

if navigation_pages is not None:
    navigation_position = min(st.session_state.get(navigation_key, 0), len(navigation_pages) - 1)
    scan_choice, navigation_page_index = navigation_pages[navigation_position]
scan = scans[scan_choice]
scan_name = scan["name"]
questions = questions_for_assignment(questions_df, scan_name)
exit_ticket_date = date_for_assignment(exit_ticket_dates_df, scan_name)
if exit_ticket_date is None:
    st.error(f"No scheduled date was found for {scan_name} in exit_ticket_dates.")
    st.stop()
st.caption(f"{scan_name} · {pd.Timestamp(exit_ticket_date):%B %-d, %Y} · {len(scan['files'])} PDF file(s)")
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

activate_batch(
    scan, roster_scope, all_students, expected_students, questions,
    questions.empty or answer_key is None, scores_df,
)
try:
    scan_bytes = download_batch(scan["files"])
except Exception as exc:
    st.error("Could not read this exit-ticket folder. Nothing was saved.")
    st.caption(str(exc))
    st.stop()

matches = st.session_state.matches
visible_page_indices = st.session_state.visible_page_indices
if not visible_page_indices:
    st.warning(
        f"No pages were found for {roster_scope}. Choose All students to review "
        "pages matched to a different period."
    )
    st.stop()
if navigation_pages is None:
    page_count = len(visible_page_indices)
    page_position = min(st.session_state.get("page_position", 0), page_count - 1)
    page_index = visible_page_indices[page_position]
else:
    page_count = len(navigation_pages)
    page_position = navigation_position
    page_index = navigation_page_index
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
    text=f"{view_mode}: page {page_position + 1} of {page_count}",
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
st.session_state.setdefault("page_assignment_overrides", {})[
    (scan["id"], page_index)
] = selected_student
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

required_ids = (
    [MANUAL_QUESTION]
    if st.session_state.manual_grading
    else [str(question["question"]) for question in st.session_state.questions]
)


def required_for_student(student: str | None) -> list[str]:
    return required_ids


graded_students, ungraded_students = completion_lists(
    st.session_state.grades, expected_students, required_ids,
)

enable_mobile_grade_inputs()

if save_progress:
    try:
        # A previously graded student can lack a page in a later upload. Do
        # not replace their saved numeric work with AE merely for that reason.
        absent_without_work = {
            student for student in missing_students
            if grade_count(st.session_state.grades, student, required_ids) == 0
        }
        if st.session_state.manual_grading:
            score_rows = build_manual_score_rows(
                expected_students,
                scan_name,
                st.session_state.manual_possible_points,
                st.session_state.grades,
                exit_ticket_date,
                absent_without_work,
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
                absent_without_work,
            )
            # Apply mapped ticket dates here instead of requiring the imported
            # grader module to accept a newly added keyword argument. Streamlit
            # can hot-reload this file while retaining an older imported
            # grader.py module, which previously made every save fail with an
            # unexpected ``ticket_dates`` argument.
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
    if navigation_key is None:
        st.session_state.page_position = page_position - 1
    else:
        st.session_state[navigation_key] = page_position - 1
    st.rerun()
if go_next:
    if navigation_key is None:
        st.session_state.page_position = page_position + 1
    else:
        st.session_state[navigation_key] = page_position + 1
    st.rerun()

st.divider()
st.subheader("Batch summary")
summary_a, summary_b, summary_c, summary_d = st.columns(4)
summary_a.metric("Pages in view", page_count)
summary_b.metric("Graded students", len(graded_students))
summary_c.metric("Still to grade", len(ungraded_students))
summary_d.metric("Missing students", len(missing_students))
if ungraded_students:
    with st.expander(f"Still to grade: {len(ungraded_students)} students"):
        st.write(", ".join(ungraded_students))
if duplicates:
    st.error("Assigned to multiple pages: " + ", ".join(duplicates))
if missing_students:
    with st.expander("Students who will receive AE"):
        st.write("\n".join(f"• {student}" for student in missing_students))
