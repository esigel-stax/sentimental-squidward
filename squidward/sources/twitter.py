"""X/Twitter source adapter, via API v2 recent search.

The only paid source of the four. Recent search covers a rolling 7-day window,
which happens to be exactly the digest window, so there is no pagination-by-date
gymnastics — but it also means Twitter can never answer "what changed last
month".

Set TWITTER_BEARER_TOKEN (app-only bearer from the X developer portal). Without
it this adapter raises rather than silently returning nothing, and the CLI logs
it and carries on with the other platforms.

Engagement is likes + retweets + quotes: the closest analogue to an upvote.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

from ..schemas import Mention

PLATFORM = "twitter"
API = "https://api.x.com/2/tweets/search/recent"


class TwitterAuthError(RuntimeError):
    pass


def _is_noise(text: str) -> bool:
    if not text or len(text.strip()) < 25:
        return True
    low = text.lower()
    # Release-announcement bots and job spam dominate the raw firehose.
    if low.startswith("rt @"):
        return True
    if any(k in low for k in ("hiring", "we're hiring", "job alert", "airdrop",
                              "giveaway", "follow me", "#nft")):
        return True
    return False


def fetch(days: int = 7,
          limit: int = 200,
          query: str = "litellm",
          bearer_token: Optional[str] = None) -> List[Mention]:
    token = bearer_token or os.getenv("TWITTER_BEARER_TOKEN")
    if not token:
        raise TwitterAuthError(
            "Twitter needs TWITTER_BEARER_TOKEN (X developer portal, app-only "
            "bearer). There is no free read tier — the Basic plan is the entry "
            "point. Every other source in Squidward is free or nearly so; this "
            "is the one that costs money.")

    # Recent search is capped at 7 days regardless of what the caller wants.
    # Asking for exactly 7d00m00s is rejected as out-of-window by the time the
    # request lands, so back off a few minutes.
    days = min(days, 7)
    start = (datetime.now(timezone.utc) - timedelta(days=days)
             + timedelta(minutes=5))
    start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")

    mentions: List[Mention] = []
    users: Dict[str, str] = {}
    next_token: Optional[str] = None

    while len(mentions) < limit:
        params = {
            "query": f"{query} -is:retweet",
            "max_results": 100,
            "start_time": start_str,
            "tweet.fields": "created_at,public_metrics,lang",
            "expansions": "author_id",
            "user.fields": "username",
        }
        if next_token:
            params["next_token"] = next_token

        r = requests.get(API, params=params,
                         headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r.status_code == 401:
            raise TwitterAuthError(
                "X rejected TWITTER_BEARER_TOKEN (401). Check you copied the "
                "Bearer Token, not the Consumer Key or Secret.")
        if r.status_code == 403:
            raise TwitterAuthError(
                "X returned 403 for /2/tweets/search/recent. The Free access "
                "tier is write-only — search requires Basic or above. This is "
                "the most common wall when the token itself is valid. "
                f"Body: {r.text[:200]}")
        if r.status_code == 429:
            # Partial data beats no data: a rate limit mid-pagination should not
            # discard the pages we already paid for.
            if mentions:
                break
            reset = r.headers.get("x-rate-limit-reset", "?")
            raise TwitterAuthError(
                f"X rate limit hit (429) before any results; resets at epoch "
                f"{reset}. Recent search allows 60 requests / 15 min.")
        r.raise_for_status()
        payload = r.json()

        # X can return 200 with an errors block and no usable data.
        if "data" not in payload and payload.get("errors"):
            detail = "; ".join(e.get("detail", "") for e in payload["errors"])[:200]
            raise TwitterAuthError(f"X returned an error payload: {detail}")

        for u in payload.get("includes", {}).get("users", []):
            users[u["id"]] = u.get("username", "unknown")

        for t in payload.get("data", []):
            text = t.get("text", "")
            if t.get("lang") not in (None, "en") or _is_noise(text):
                continue
            pm = t.get("public_metrics", {}) or {}
            handle = users.get(t.get("author_id", ""), "unknown")
            mentions.append(Mention(
                id=f"{PLATFORM}:tweet:{t['id']}",
                platform=PLATFORM,
                author=f"@{handle}",
                text=text,
                url=f"https://x.com/{handle}/status/{t['id']}",
                created_at=t.get("created_at", ""),
                context="tweet",
                engagement=(pm.get("like_count", 0) + pm.get("retweet_count", 0)
                            + pm.get("quote_count", 0)),
                engagement_label="likes+RTs",
            ))

        next_token = payload.get("meta", {}).get("next_token")
        if not next_token:
            break

    mentions.sort(key=lambda m: m.created_at, reverse=True)
    return mentions[:limit]
