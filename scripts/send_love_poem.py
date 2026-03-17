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
            raise Exception("Credentials not valid. Please run scripts/setup_rlm_agent_auth.py first.")
    
    return build('gmail', 'v1', credentials=creds)

def create_message(to, subject, content):
    message = EmailMessage()
    message.set_content(content)
    message['To'] = to
    message['From'] = 'rawley.stanhope@gmail.com'
    message['Subject'] = subject

    # encoded message
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': encoded_message}

def send_message(service, user_id, message):
    try:
        sent_message = service.users().messages().send(userId=user_id, body=message).execute()
        print(f"Message sent! ID: {sent_message['id']}")
        return sent_message
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

def main():
    service = get_gmail_service()
    
    # Love poem content
    poem = """
Dearest Sarah,

In the quiet of our home and the noise of our day,
There are so many things I wish I could say.
You're the heart of our family, the strength in my soul,
The one who completes me and makes my life whole.

From the sports in the morning to the news in the night,
You handle it all with such grace and such light.
Thank you for being the person you are,
My wife, my best friend, my bright shining star.

I love you forever.

Love,
Rawley
    """
    
    to = "stanhope.sarah@gmail.com"
    subject = "A little poem for you"
    
    print(f"Sending love poem to {to}...")
    message = create_message(to, subject, poem)
    send_message(service, 'me', message)

if __name__ == '__main__':
    main()
