"""Reddit source adapter.

Unlike GitHub, Reddit has no usable anonymous path any more — `.json` endpoints
return a 403 HTML page to non-browser clients regardless of User-Agent. So this
adapter uses the app-only OAuth flow, which is free and takes ~2 minutes to set
up:

    1. https://www.reddit.com/prefs/apps  ->  "create another app..."
    2. pick type "script", redirect uri http://localhost:8080
    3. export REDDIT_CLIENT_ID (under the app name) and REDDIT_CLIENT_SECRET

Rate limit is 100 requests/minute, which is far more than a weekly digest needs.

Pulls both submissions matching the query and the comments underneath them —
the comments are where the sentiment actually lives; a post titled "LiteLLM vs
OpenRouter" is neutral, its 40 replies are not.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

from ..schemas import Mention

PLATFORM = "reddit"
UA = "python:squidward-sentiment-bot:0.1 (LiteLLM community digest)"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"

# Subreddits worth searching directly — global search misses low-karma posts in
# niche subs, and these are where LLM infrastructure actually gets discussed.
DEFAULT_SUBS = ["LocalLLaMA", "LLMDevs", "MachineLearning", "OpenAI",
                "ChatGPTCoding", "AI_Agents", "devops"]

BOT_AUTHORS = {"AutoModerator", "[deleted]", "reddit-bot", "sneakpeekbot",
               "RemindMeBot", "WikiSummarizerBot", "B0tRank"}


class RedditAuthError(RuntimeError):
    pass


def _token(client_id: str, client_secret: str) -> str:
    r = requests.post(TOKEN_URL,
                      auth=(client_id, client_secret),
                      data={"grant_type": "client_credentials"},
                      headers={"User-Agent": UA}, timeout=30)
    if r.status_code == 401:
        raise RedditAuthError(
            "Reddit rejected REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET (401). "
            "Check the app is type 'script' and the id is the string under the "
            "app name, not the app name itself.")
    r.raise_for_status()
    return r.json()["access_token"]


def _get(path: str, params: dict, token: str) -> dict:
    r = requests.get(f"{API}{path}", params=params,
                     headers={"Authorization": f"bearer {token}", "User-Agent": UA},
                     timeout=30)
    if r.status_code == 429:
        time.sleep(2)
        r = requests.get(f"{API}{path}", params=params,
                         headers={"Authorization": f"bearer {token}",
                                  "User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.json()


def _is_noise(author: str, body: str) -> bool:
    if not body or not body.strip():
        return True
    if body.strip() in ("[deleted]", "[removed]"):
        return True
    if author in BOT_AUTHORS or author.lower().endswith("bot"):
        return True
    if len(body.strip()) < 15:
        return True
    return False


def _walk_comments(children: list, post: dict, cutoff: datetime,
                   out: List[Mention], keyword: str) -> None:
    """Depth-first through Reddit's nested comment listing."""
    for child in children:
        if child.get("kind") != "t1":
            continue
        c = child.get("data", {})
        created = datetime.fromtimestamp(c.get("created_utc", 0), timezone.utc)
        author = c.get("author", "unknown")
        body = c.get("body", "")
        # Only keep comments that actually mention the tool — a 200-reply thread
        # about model routing is mostly not about LiteLLM.
        if created >= cutoff and keyword in body.lower() and not _is_noise(author, body):
            out.append(Mention(
                id=f"{PLATFORM}:comment:{c['id']}",
                platform=PLATFORM,
                author=author,
                text=body,
                url=f"https://reddit.com{c.get('permalink', '')}",
                created_at=created.isoformat().replace("+00:00", "Z"),
                context=f"r/{c.get('subreddit', '?')} · comment on \"{post.get('title','')[:60]}\"",
                engagement=int(c.get("score", 0) or 0),
                engagement_label="upvotes",
            ))
        replies = c.get("replies")
        if isinstance(replies, dict):
            _walk_comments(replies.get("data", {}).get("children", []),
                           post, cutoff, out, keyword)


def fetch(days: int = 7,
          limit: int = 200,
          query: str = "litellm",
          subs: Optional[List[str]] = None,
          with_comments: bool = True,
          client_id: Optional[str] = None,
          client_secret: Optional[str] = None) -> List[Mention]:
    client_id = client_id or os.getenv("REDDIT_CLIENT_ID")
    client_secret = client_secret or os.getenv("REDDIT_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise RedditAuthError(
            "Reddit needs credentials: set REDDIT_CLIENT_ID and "
            "REDDIT_CLIENT_SECRET. Reddit returns 403 to anonymous JSON clients "
            "— there is no keyless path. See the docstring in sources/reddit.py "
            "for the 2-minute setup.")

    token = _token(client_id, client_secret)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    keyword = query.lower()
    mentions: List[Mention] = []
    seen = set()
    posts: List[dict] = []

    # --- submissions: global search plus each high-signal subreddit
    searches = [("/search", {"q": query, "sort": "new", "t": "week",
                             "limit": 100, "type": "link"})]
    for sub in (subs if subs is not None else DEFAULT_SUBS):
        searches.append((f"/r/{sub}/search",
                         {"q": query, "restrict_sr": 1, "sort": "new",
                          "t": "week", "limit": 50}))

    for path, params in searches:
        try:
            data = _get(path, params, token)
        except requests.HTTPError:
            continue  # private/banned sub — skip, don't kill the run
        for child in data.get("data", {}).get("children", []):
            p = child.get("data", {})
            if p.get("id") in seen:
                continue
            seen.add(p.get("id"))
            created = datetime.fromtimestamp(p.get("created_utc", 0), timezone.utc)
            if created < cutoff:
                continue
            posts.append(p)
            author = p.get("author", "unknown")
            body = f"{p.get('title','')}\n\n{p.get('selftext','') or ''}"
            if not _is_noise(author, body):
                mentions.append(Mention(
                    id=f"{PLATFORM}:post:{p['id']}",
                    platform=PLATFORM,
                    author=author,
                    text=body,
                    url=f"https://reddit.com{p.get('permalink','')}",
                    created_at=created.isoformat().replace("+00:00", "Z"),
                    context=f"r/{p.get('subreddit','?')} · post "
                            f"({p.get('score',0)} pts, {p.get('num_comments',0)} comments)",
                    engagement=int(p.get("score", 0) or 0),
                    engagement_label="upvotes",
                ))

    # --- comments under those posts, filtered to ones naming the tool
    if with_comments:
        for p in posts[:40]:  # cap: one request each, 100/min budget
            if len(mentions) >= limit:
                break
            try:
                listing = _get(f"/comments/{p['id']}",
                               {"limit": 100, "depth": 4, "sort": "top"}, token)
            except requests.HTTPError:
                continue
            if isinstance(listing, list) and len(listing) > 1:
                _walk_comments(listing[1].get("data", {}).get("children", []),
                               p, cutoff, mentions, keyword)

    mentions.sort(key=lambda m: m.created_at, reverse=True)
    return mentions[:limit]
