"""Test YouTube Data API v3 search via OAuth credentials.

Usage:
    python scripts/test_youtube_search.py "AI agent Facebook ads"
    python scripts/test_youtube_search.py  # defaults to "AI agent advertising automation"
"""
import json
import sys
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def get_creds():
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def search_videos(query: str, max_results: int = 10):
    youtube = build("youtube", "v3", credentials=get_creds())
    resp = youtube.search().list(
        q=query,
        part="snippet",
        type="video",
        maxResults=max_results,
        order="relevance",
    ).execute()

    videos = []
    for item in resp.get("items", []):
        vid = item["id"]["videoId"]
        snip = item["snippet"]
        videos.append({
            "title": snip["title"],
            "url": f"https://www.youtube.com/watch?v={vid}",
            "channel": snip["channelTitle"],
            "published": snip["publishedAt"][:10],
        })
    return videos


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "AI agent advertising automation"
    print(f"Searching YouTube for: {query}\n")
    results = search_videos(query)
    for i, v in enumerate(results, 1):
        print(f"{i:2d}. [{v['published']}] {v['title']}")
        print(f"    {v['url']}  ({v['channel']})")
    print(f"\n{len(results)} results")
    # Also dump JSON for piping
    json.dump(results, open("/tmp/youtube_search_results.json", "w"), indent=2)
    print(f"JSON saved to /tmp/youtube_search_results.json")
