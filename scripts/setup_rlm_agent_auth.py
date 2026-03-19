import os
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Full list of scopes requested for Gmail, Drive, Tasks, and GCP (Trace/Logging)
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/youtube.readonly',  # YouTube Data API v3 (search, list videos)
    'https://www.googleapis.com/auth/cloud-platform',  # Required for Trace/Logging/Telemetry
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
        print("Your rlm-agent can now access Gmail, Drive, Tasks, Trace, and Logging.")

if __name__ == '__main__':
    main()
