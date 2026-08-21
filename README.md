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
- Roster tab: `students`

The service-account email in Streamlit secrets needs Viewer access to both
Drive folders and Editor access to the spreadsheet. Public folder access may
work, but explicitly sharing the folders with the service account is more
reliable for the Drive API.

## Local test

1. Create `.streamlit/secrets.toml` by copying the secrets from the existing app.
2. Install requirements: `python3 -m pip install -r requirements.txt`
3. Install Tesseract OCR: `brew install tesseract`
4. Run: `python3 -m streamlit run app.py`

The app only writes to the spreadsheet after **Save and finalize batch** is
pressed. Until then, page assignments and grades stay in the Streamlit session.

## Updating data after deployment

No code change or redeployment is needed when students, questions, scans, or
answer keys change:

- Edit the `students` and `exit_ticket_questions` tabs in Google Sheets.
- Add incoming scans and answer keys to their existing Google Drive folders.
- In the app sidebar, press **Refresh Google data** to load the changes
  immediately. Otherwise, the short data caches refresh automatically.
