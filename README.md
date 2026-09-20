# Exit Ticket Grader

A phone-friendly Streamlit app that reads class-batch exit-ticket PDFs from
Google Drive, matches each page to a rostered student, displays the matching
answer key, and writes question-level grades to Google Sheets.

## Google resources

- Spreadsheet: `Academic Monitoring Tool Data`
- Incoming scans folder ID: `1Bf3kacbRX7UP5xmR8mahiTU2fTFa9mh6`
- Answer keys folder ID: `1kpaqfrxtGRsk0yBmpy31MGWwyOqaaWx6`
- Score tab: `exit_ticket_scores`
- Question configuration tab: `exit_ticket_questions`
- Lesson-date lookup tab: `exit_ticket_dates`
- Roster tab: `students`

The service-account email in Streamlit secrets needs Viewer access to both
Drive folders and Editor access to the spreadsheet. Public folder access may
work, but explicitly sharing the folders with the service account is more
reliable for the Drive API.

## Local test

1. Create `.streamlit/secrets.toml` by copying the secrets from the existing app.
2. Install requirements: `python3 -m pip install -r requirements.txt`
3. Run: `python3 -m streamlit run app.py`

OCR is provided by the Python dependencies in `requirements.txt`; no operating
system package installation is required.

The app only writes scores to the spreadsheet when **Save** is pressed. Until
then, page assignments and grades stay in the Streamlit session. Save before
refreshing or closing the browser.

## Updating data after deployment

No code change or redeployment is needed when students, questions, scans, or
answer keys change:

- Edit the `students`, `exit_ticket_questions`, and `exit_ticket_dates` tabs in Google Sheets.
- Add incoming scans and answer keys to their existing Google Drive folders.
- Refresh the browser page to load the latest data. The short data caches also
  refresh automatically while the app remains open.

## Questions repeated on later exit tickets

To show an earlier question on a later grading page, duplicate its configuration
row in `exit_ticket_questions`, change `exit_ticket` to the later ticket, and put
the original ticket in `save_to_exit_ticket`. The app will display the same saved
score on every configured copy. Saving from any copy updates the single original
ticket record, so the question contributes only to the original ticket's grade.
# Multiple scan files per exit ticket

Inside Incoming Scans, create a folder named exactly like the exit ticket
(for example, `1.10 Exit Ticket`) and upload every corresponding PDF into it.
The filenames inside that folder can be anything. PDFs are read alphabetically
by filename, with pages within each file kept in their original order. The app
shows them as one continuous batch and keeps the existing student assignment,
grading, answer-key, and saved-score behavior. Non-PDF files are ignored.
Front and back tickets that have separate answer keys keep separate folders.

Refresh the page after adding or replacing a PDF. The exit-ticket view reads
names only from its selected folder. The student and unit views prepare their
wider indexes in four-page chunks, with progress shown. Each completed chunk
is written to the `scan_index` tab in the grading spreadsheet. Opening a new
browser session or restarting Streamlit reuses those rows instead of running
OCR again. A new or replaced PDF has a new Drive file version, so only its
pages need OCR. The tab's columns are `exit_ticket`, `pdf_name`, `file_id`,
`modified_time`, `file_size`, `page_number`, `page_count`, and `header_text`.
The grader creates this tab automatically with its existing spreadsheet
credentials. Do not change these column headings. If the tab cannot be
created or reached, the grader warns and continues using its prior in-memory
index. Loose PDFs in Incoming Scans remain supported for backward
compatibility. No combined file is uploaded to Drive.

## Grading views

- **By exit ticket** shows the familiar page-by-page review for one ticket.
- **By student** follows one student's recognized pages across exit tickets.
  Assign an unmatched Extra page in the exit-ticket view first; it will then
  appear in that student's view for the current browser session.
- **Unit summary** groups tickets by the number before the decimal point in
  the lesson number. It lists students with at least one missing native
  question grade and offers a queue of their scanned pages. Students with no
  page are listed but cannot be opened until their work is uploaded.

A score of zero counts as graded. AE, blank scores, and any student missing
even one required question count as still to grade. Repeated questions mapped
back to an earlier ticket are not required again for the newer ticket's unit
completion total.
