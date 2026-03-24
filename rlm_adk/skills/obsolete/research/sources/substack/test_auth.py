#!/usr/bin/env python3
"""Test script: authenticate and print subscriptions, then fetch a paywalled post.

Usage:
    python test_auth.py [username]

    # Default username from env
    SUBSTACK_USERNAME=rawleystanhope python test_auth.py
"""

import logging
import os
import sys

from rlm_adk.skills.research.sources.substack.client import SubstackClient


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    username = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SUBSTACK_USERNAME")
    if not username:
        print("Usage: python test_auth.py <username>", file=sys.stderr)
        sys.exit(1)

    client = SubstackClient(username)
    user = client.get_user()
    print(f"User: {user.name} (ID: {user.id})")
    print(f"Authenticated: {client.authenticated}")

    subscriptions = client.get_subscriptions()
    if not subscriptions:
        print("No subscriptions found.")
        return

    paid = [s for s in subscriptions if s.get("membership_state") == "subscribed"]
    free = [s for s in subscriptions if s.get("membership_state") != "subscribed"]

    print(f"\nSubscriptions: {len(subscriptions)} total ({len(paid)} paid, {len(free)} free)")
    print("-" * 60)

    if paid:
        print("\nPaid:")
        for i, sub in enumerate(paid, 1):
            print(f"  {i:3}. {sub['publication_name']}")
            print(f"       https://{sub['domain']}")

    if free:
        print(f"\nFree ({len(free)}):")
        for i, sub in enumerate(free, 1):
            print(f"  {i:3}. {sub['publication_name']}")
            print(f"       https://{sub['domain']}")

    # Test paywalled content if authenticated
    if client.authenticated and paid:
        print("\n" + "=" * 60)
        print("Paywalled content test:")
        newsletter_url = f"https://{paid[0]['domain']}"
        posts = client.get_recent_posts(newsletter_url, limit=1)
        if posts:
            meta = posts[0].get_metadata()
            content = posts[0].get_content()
            print(f"  Title: {meta.get('title', 'Unknown')}")
            print(f"  Content: {len(content)} chars")
            print(f"  Preview: {content[:200]}...")


if __name__ == "__main__":
    main()
