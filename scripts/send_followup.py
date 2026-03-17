import os
import base64
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN_PATH = 'token.json'
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/cloud-platform',
]

def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("Credentials not valid.")
    return build('gmail', 'v1', credentials=creds)

def create_message(to, subject, content):
    message = EmailMessage()
    message.set_content(content)
    message['To'] = to
    message['From'] = 'rawley.stanhope@gmail.com'
    message['Subject'] = subject
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': encoded_message}

def main():
    service = get_gmail_service()
    content = "Just to clarify, that last poem was actually from Gemini! And for the record, my own poetry is definitely better. ;)"
    to = "stanhope.sarah@gmail.com"
    subject = "Wait, one more thing..."
    
    print(f"Sending follow-up to {to}...")
    message = create_message(to, subject, content)
    service.users().messages().send(userId='me', body=message).execute()
    print("Follow-up sent!")

if __name__ == '__main__':
    main()
