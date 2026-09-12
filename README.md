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

The app only writes to the spreadsheet after **Save and finalize batch** is
pressed. Until then, page assignments and grades stay in the Streamlit session.

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
