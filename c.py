import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# 1️⃣ Define the scope and credentials file
scope = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
creds = Credentials.from_service_account_file(
    'credentials.json', scopes=scope
)

# 2️⃣ Authenticate and access the spreadsheet
client = gspread.authorize(creds)

# 3️⃣ Open the spreadsheet by its URL
spreadsheet_url = 'https://docs.google.com/spreadsheets/d/1bAz6nUzcl52dQT2jQAGRA9-64QpE4OHC-qMOVo2yHDI/edit'
spreadsheet = client.open_by_url(spreadsheet_url)

# 4️⃣ Access the first worksheet
worksheet = spreadsheet.sheet1

# 5️⃣ Prepare the data row
new_row = [
    "John Doe",                           # Name
    "john.doe@example.com",               # Email
    "Test Subject",                       # Subject
    "This is a test message.",            # Message
    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # Timestamp
    "No"                                  # Responded status
]

# 6️⃣ Append the row to the sheet
worksheet.append_row(new_row)

print("✅ Row appended successfully!")
