import os
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# The file token.json stores the user's access and refresh tokens.
TOKEN_PATH = 'token.json'
SCOPES = [
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
            raise Exception("Credentials not valid. Please run scripts/setup_rlm_agent_auth.py first.")
    
    return build('gmail', 'v1', credentials=creds)

def fetch_latest_emails(service, count=10):
    # Fetch messages from the primary category
    results = service.users().messages().list(userId='me', q='label:INBOX category:primary', maxResults=count).execute()
    messages = results.get('messages', [])
    
    email_data = []
    for msg in messages:
        m = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        
        # Extract headers
        headers = m['payload']['headers']
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
        date = next((h['value'] for h in headers if h['name'] == 'Date'), 'Unknown Date')
        snippet = m.get('snippet', '')
        
        email_data.append({
            'id': msg['id'],
            'subject': subject,
            'from': sender,
            'date': date,
            'snippet': snippet
        })
    
    return email_data

def main():
    try:
        service = get_gmail_service()
        print(f"Fetching latest 10 primary emails...")
        emails = fetch_latest_emails(service)
        
        # Save to tmp directory
        tmp_dir = '/home/rawley-stanhope/.gemini/tmp/rlm-adk'
        os.makedirs(tmp_dir, exist_ok=True)
        output_file = os.path.join(tmp_dir, 'latest_emails.json')
        
        with open(output_file, 'w') as f:
            json.dump(emails, f, indent=2)
            
        print(f"\nSaved emails to {output_file}")
        
        # Print summaries for the user
        print("\n--- Latest 10 Primary Emails Summary ---")
        for i, email in enumerate(emails, 1):
            print(f"{i}. [{email['date']}] {email['from']}")
            print(f"   Subject: {email['subject']}")
            print(f"   Snippet: {email['snippet'][:100]}...")
            print("-" * 40)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
