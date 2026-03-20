import os
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Full list of scopes for all Google Workspace APIs + GCP
SCOPES = [
    # Gmail
    'https://mail.google.com/',                              # Full Gmail access (read/compose/send/delete)
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.settings.basic',  # Email settings and filters
    # Google Drive
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.activity',        # File activity record
    # Google Docs
    'https://www.googleapis.com/auth/documents',
    # Google Sheets
    'https://www.googleapis.com/auth/spreadsheets',
    # Google Calendar
    'https://www.googleapis.com/auth/calendar',
    # Google Tasks
    'https://www.googleapis.com/auth/tasks',
    # People / Contacts
    'https://www.googleapis.com/auth/contacts',
    'https://www.googleapis.com/auth/contacts.readonly',
    # YouTube
    'https://www.googleapis.com/auth/youtube.readonly',
    # GCP (Trace/Logging/Telemetry)
    'https://www.googleapis.com/auth/cloud-platform',
]

def main():
    """Shows basic usage of the Apps Script API.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('client_secret.json'):
                print("Error: client_secret.json not found.")
                print("Please download it from the GCP Console (Credentials page) and name it 'client_secret.json'.")
                return

            flow = InstalledAppFlow.from_client_secrets_file(
                'client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        
        print("\nSUCCESS: 'token.json' has been created.")
        print("Your rlm-agent can now access Gmail, Drive, Docs, Sheets, Calendar, Tasks, Contacts, YouTube, and GCP.")

if __name__ == '__main__':
    main()
