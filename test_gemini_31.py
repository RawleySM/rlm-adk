import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load .env
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    # Try getting from process env if not in file
    api_key = os.environ.get("GOOGLE_API_KEY")

if not api_key:
    print("Error: GOOGLE_API_KEY not found in .env or environment")
    exit(1)

client = genai.Client(api_key=api_key)
model_id = "gemini-3.1-pro-preview"

print(f"Calling model: {model_id}...")
try:
    response = client.models.generate_content(
        model=model_id,
        contents="Hello, how are you? Tell me who you are.",
    )
    print("\nResponse:")
    print(response.text)
except Exception as e:
    print(f"\nError calling model: {e}")
