# Substack API

An unofficial Python client library for interacting with Substack newsletters and content.

## Overview

This library provides Python interfaces for interacting with Substack's unofficial API, allowing you to:

- Retrieve newsletter posts, podcasts, and recommendations
- Get user profile information and subscriptions
- Fetch post content and metadata
- Search for posts within newsletters
- Access paywalled content **that you have written or paid for** with user-provided authentication

## Installation

```bash
# Using pip
pip install substack-api

# Using poetry
poetry add substack-api
```

## Usage Examples

### Working with Newsletters

```python
from substack_api import Newsletter

# Initialize a newsletter by its URL
newsletter = Newsletter("https://example.substack.com")

# Get recent posts (returns Post objects)
recent_posts = newsletter.get_posts(limit=5)

# Get posts sorted by popularity
top_posts = newsletter.get_posts(sorting="top", limit=10)

# Search for posts
search_results = newsletter.search_posts("machine learning", limit=3)

# Get podcast episodes
podcasts = newsletter.get_podcasts(limit=5)

# Get recommended newsletters
recommendations = newsletter.get_recommendations()

# Get newsletter authors
authors = newsletter.get_authors()
```

### Working with Posts

```python
from substack_api import Post

# Initialize a post by its URL
post = Post("https://example.substack.com/p/post-slug")

# Get post metadata
metadata = post.get_metadata()

# Get the post's HTML content
content = post.get_content()
```

### Accessing Paywalled Content with Authentication

To access paywalled content, you need to provide your own session cookies from a logged-in Substack session:

```python
from substack_api import Newsletter, Post, SubstackAuth

# Set up authentication with your cookies
auth = SubstackAuth(cookies_path="path/to/your/cookies.json")

# Use authentication with newsletters
newsletter = Newsletter("https://example.substack.com", auth=auth)
posts = newsletter.get_posts(limit=5)  # Can now access paywalled posts

# Use authentication with individual posts
post = Post("https://example.substack.com/p/paywalled-post", auth=auth)
content = post.get_content()  # Can now access paywalled content

# Check if a post is paywalled
if post.is_paywalled():
    print("This post requires a subscription")
```

#### Getting Your Cookies

To access paywalled content, you need to export your browser cookies from a logged-in Substack session. The cookies should be in JSON format with the following structure:

```json
[
  {
    "name": "substack.sid",
    "value": "your_session_id",
    "domain": ".substack.com",
    "path": "/",
    "secure": true
  },
  {
    "name": "substack.lli",
    "value": "your_lli_value",
    "domain": ".substack.com",
    "path": "/",
    "secure": true
  },
  ...
]
```

**Important**: Only use your own cookies from your own authenticated session. **This feature is intended for users to access their own subscribed or authored content programmatically.**

### Working with Users

```python
from substack_api import User

# Initialize a user by their username
user = User("username")

# Get user profile information
profile_data = user.get_raw_data()

# Get user ID and name
user_id = user.id
name = user.name

# Get user's subscriptions
subscriptions = user.get_subscriptions()
```

#### Handling Renamed Accounts

Substack allows users to change their handle (username) at any time. When this happens, the old API endpoints return 404 errors. This library automatically handles these redirects by default.

##### Automatic Redirect Handling

```python
from substack_api import User

# This will automatically follow redirects if the handle has changed
user = User("oldhandle")  # Will find the user even if they renamed to "newhandle"

# Check if a redirect occurred
if user.was_redirected:
    print(f"User was renamed from {user.original_username} to {user.username}")
```

##### Disable Redirect Following

If you prefer to handle 404s yourself:

```python
# Disable automatic redirect following
user = User("oldhandle", follow_redirects=False)
```

##### Manual Handle Resolution

You can also manually resolve handle redirects:

```python
from substack_api import resolve_handle_redirect

new_handle = resolve_handle_redirect("oldhandle")
if new_handle:
    print(f"Handle was renamed to: {new_handle}")
```

### Discovery: Categories and Thought-Leader Rankings

Substack organizes newsletters into 31 categories with ranked leaderboards.

```python
from substack_api import list_all_categories, Category

# List all 31 categories
categories = list_all_categories()
# Returns: [('Culture', 96), ('Technology', 4), ('Business', 62), ...]

# Get ranked newsletters in a category (up to 525+ per category)
tech = Category(name="Technology")

# Full metadata: name, subscriber counts, ranking details
metadata = tech.get_newsletter_metadata()
# [{'name': 'ByteByteGo', 'rankingDetail': 'Tens of thousands of paid subscribers', ...}, ...]

# Just URLs
urls = tech.get_newsletter_urls()

# Newsletter objects ready to query
newsletters = tech.get_newsletters()
```

Available categories: Culture, Technology, Business, U.S. Politics, Finance,
Food & Drink, Podcasts, Sports, Art & Illustration, World Politics,
Health Politics, News, Fashion & Beauty, Music, Faith & Spirituality,
Climate & Environment, Science, Literature, Fiction, Health & Wellness,
Design, Travel, Parenting, Philosophy, Comics, International, Crypto,
History, Humor, Education, Film & TV.

### Discovery: Global Publication Search (requires auth)

Cross-newsletter keyword search. Requires authenticated session cookies
(returns empty results without auth).

```python
from substack_api import SubstackAuth

auth = SubstackAuth(cookies_path="~/.config/substack/cookies.json")
resp = auth.get(
    "https://substack.com/api/v1/publication/search",
    params={"query": "artificial intelligence", "page": 0, "limit": 100, "sort": "relevance"},
)
results = resp.json()  # List of publications with metadata
```

### Discovery: Trending Posts

Currently viral posts across Substack, filterable by category. No auth required.

```python
import requests

# Trending in Technology (category_id=4)
resp = requests.get(
    "https://substack.com/api/v1/trending",
    params={"limit": 50, "category_id": 4},
    headers={"User-Agent": "Mozilla/5.0"},
)
data = resp.json()
# data["posts"] — full post objects with reactions, restacks, comment_count
# data["publications"] — publisher metadata incl. author_bestseller_tier
```

### Discovery: Recommendation Graph

Each newsletter recommends related publications. Walk the graph to discover
thought-leaders starting from newsletters you already follow.

```python
from substack_api import Newsletter

# Get recommendations from a known newsletter
nl = Newsletter("https://www.latent.space")
recs = nl.get_recommendations()
# Returns list of Newsletter objects — each can be queried for their own recs

# Depth-2 graph walk
for rec in recs[:5]:
    deeper = rec.get_recommendations()
    # ...discover newsletters 2 hops away
```

### RLM SubstackClient (local wrapper)

`client.py` wraps `substack_api` with self-healing cookie auth and the
authenticated subscriptions endpoint.

```python
from rlm_adk.skills.research.sources.substack.client import SubstackClient

client = SubstackClient("rawleystanhope")

# Subscriptions (uses authenticated endpoint — returns ALL subs including hidden paid)
subs = client.get_subscriptions()
# Public API hides some paid subs; authenticated endpoint returns the full list

# Paywalled content (cookies extracted automatically from Chrome)
posts = client.get_recent_posts("https://www.racket.news", limit=3)
content = client.get_post_content("https://www.racket.news/p/some-article")

# Auth pipeline: Chrome cookies → pip-upgrade retry → cached cookies → public fallback
print(client.authenticated)  # True if cookies available
```

**Cookie extraction pipeline:**
1. Extract fresh cookies from Chrome's local DB via `browser-cookie3`
2. On failure, `pip install --upgrade browser-cookie3` and retry once
3. Fall back to cached cookies at `~/.config/substack/cookies.json`
4. Fall back to public API only (no paywalled content)

### Authenticated vs Public API

| Feature | Public API | Authenticated API |
|---------|-----------|-------------------|
| Free subscriptions | Yes | Yes |
| **All** paid subscriptions | Partial (some hidden) | Yes |
| Free post content | Yes | Yes |
| Paywalled post content | No | Yes |
| Endpoint | `/api/v1/user/{name}/public_profile` | `/api/v1/subscriptions` |

## Full API Endpoint Reference

### Public (no auth required)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/categories` | All 31 categories with subcategories |
| `GET /api/v1/category/public/{id}/{sort}?page=N` | Ranked newsletters per category (see sorts below) |
| `GET /api/v1/trending?limit=N&offset=N&category_id=N` | **Trending posts** with engagement metrics |
| `GET {nl_url}/api/v1/archive?sort=new&search={q}&offset=N&limit=N` | Search posts within one newsletter |
| `GET {nl_url}/api/v1/archive?sort=top&offset=N&limit=N` | Top posts by engagement |
| `GET {nl_url}/api/v1/recommendations/from/{pub_id}` | Outbound recommendations |
| `GET {nl_url}/api/v1/publication/users/ranked?public=true` | Authors/writers ranked |
| `GET {nl_url}/api/v1/posts/{slug}` | Post metadata + engagement stats |
| `GET /api/v1/user/{handle}/public_profile` | Profile, leaderboard status, bestseller tier |

**Category sort variants** (`/api/v1/category/public/{id}/{sort}?page=N`):

| Sort | Ranking by |
|------|-----------|
| `paid` | Paid subscriber count (strongest thought-leader signal) |
| `bestsellers` | Overall popularity |
| `trending` | Recent momentum |
| `top` / `popular` / `all` | Overall popularity (similar results) |
| `free` | Free subscriber count |
| `new` | Recently launched |
| `featured` | Substack editorial picks |

Each response includes `rankingDetail` (e.g., "Tens of thousands of paid subscribers")
and `rankingDetailFreeSubscriberCount` (e.g., "Over 1,100,000 subscribers").

**Trending endpoint** (`/api/v1/trending`) returns:
- `posts[]` — full post objects with `reactions`, `restacks`, `comment_count`
- `publications[]` — publisher metadata incl. `author_bestseller_tier`
- `trendingPosts[]` — lightweight references with `primary_category`, `tag_id`
- Filterable by `category_id` (e.g., `4` = Technology)

**Technology subcategories** (from `/api/v1/categories`):
AI (76964), Cybersecurity (76965), Emerging Tech (76966), Gadgets (76967),
Digital Media (76968), Programming (76969), Software (76970).

### Authenticated (requires cookies)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/subscriptions` | **Full** subscription list (incl. hidden paid subs) |
| `GET /api/v1/publication/search?query=X&page=0&limit=100&sort=relevance` | **Global publication search** (empty without auth) |
| `GET /api/v1/reader/feed/profile/{user_id}?types[]=like` | User's liked posts |
| `GET /api/v1/reader/feed/profile/{user_id}` | User's restacks |
| `GET /api/v1/reader/posts` | Reader post feed |
| `GET /api/v1/feed` | Main feed |
| `GET /api/v1/notes` (cursor pagination) | Notes feed |

### Not available via API

- Cross-newsletter post search (search only works within one newsletter)
- Leaderboard Rising vs Bestseller as separate endpoints (use `paid` vs `trending` sorts instead)
- Exact subscriber counts (only tier brackets like "Tens of thousands")
- Notes search/trending

## Thought-Leader Discovery Pipeline

Four-layer strategy for topic-driven discovery:

**Layer 1 — Category Seeding** (broad, structured)
- Map topic to relevant categories from the 31 available
- Use `paid` sort for thought-leader signal, `trending` for momentum
- Paginate `/category/public/{id}/paid?page=N` for ranked newsletters
- `rankingDetail` gives subscriber tier brackets

**Layer 2 — Trending Posts** (real-time signal)
- `GET /api/v1/trending?limit=50&category_id={id}` for currently viral posts
- Extract authors and publications from trending results
- Engagement metrics (reactions, restacks, comments) identify high-impact writers
- Repeat periodically to track who consistently trends

**Layer 3 — Publication Search** (targeted, keyword-driven, requires auth)
- `GET /api/v1/publication/search?query={topic}&limit=100&sort=relevance`
- Run multiple queries per topic (synonyms, subtopics)
- Catches niche publishers missed by category rankings
- Note: returns empty results without authentication

**Layer 4 — Recommendation Graph Walk** (organic, community-driven)
- Take top 10-20 newsletters from Layers 1-3 as seeds
- BFS to depth 2 via `get_recommendations()`
- Dedup by URL; expect 200-400 unique publications from 5 seeds
- Rate limit: 2s between requests, ~30-60 min for depth-2 crawl

**Scoring candidates** (per-newsletter):
- Subscriber tier from `rankingDetail` / `rankingDetailFreeSubscriberCount`
- Bestseller tier from author profile
- Recommendation in-degree (how many others recommend them)
- Post engagement (reactions, restacks, comments from trending + archive)
- Category sort position across `paid`, `trending`, `bestsellers`

## Limitations

- This is an unofficial library and not endorsed by Substack
- APIs may change without notice, potentially breaking functionality
- Rate limiting may be enforced by Substack
- **Authentication requires users to provide their own session cookies**
- **Users are responsible for complying with Substack's terms of service when using authentication features**

## License

This project is licensed under the MIT License - see the LICENSE file for details.
