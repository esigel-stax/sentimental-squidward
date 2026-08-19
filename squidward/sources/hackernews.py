"""Hacker News source adapter, via the Algolia search API.

Zero auth, no rate limit worth worrying about, clean JSON. The cheapest signal
of the four sources and the only one that reliably catches *comparison* talk —
people weighing LiteLLM against OpenRouter, Portkey, or Bedrock in threads that
were never about LiteLLM in the first place.

Engagement caveat: HN does not expose per-comment scores through any public API.
Algolia returns `points: null` for every comment. So a comment inherits its
story's points, labelled honestly as "story points" — it measures how big a room
the remark was made in, not how well it landed. Ranking only ever happens within
a platform, so this never gets compared against Reddit upvotes.
"""

import html
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from ..schemas import Mention

PLATFORM = "hn"
API = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_API = "https://hn.algolia.com/api/v1/items"
MAX_STORY_LOOKUPS = 30

TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    """Algolia returns HTML-escaped comment bodies with <p> and <a> tags."""
    if not text:
        return ""
    text = TAG_RE.sub(" ", text)
    return html.unescape(text).strip()


def _hit_to_mention(h: dict, keyword: str,
                    story_points: Optional[int] = None) -> Optional[Mention]:
    author = h.get("author") or "unknown"
    is_story = bool(h.get("title"))
    body = h.get("title") if is_story else _clean(h.get("comment_text") or "")
    if is_story and h.get("url"):
        body = f"{body}\n({h['url']})"
    if not body or len(body) < 15:
        return None
    # Algolia matches on the whole thread, so a comment in a litellm thread that
    # never says "litellm" is usually about something else entirely.
    if not is_story and keyword not in body.lower():
        return None

    oid = h.get("objectID")
    points = h.get("points")
    if is_story:
        engagement, label = int(points or 0), "points"
    else:
        engagement, label = int(story_points or 0), "story points"

    created = h.get("created_at") or ""
    story = h.get("story_title") or h.get("title") or ""
    return Mention(
        id=f"{PLATFORM}:{'story' if is_story else 'comment'}:{oid}",
        platform=PLATFORM,
        author=author,
        text=body,
        url=f"https://news.ycombinator.com/item?id={oid}",
        created_at=created,
        context=("HN story" if is_story
                 else f"HN comment on \"{story[:60]}\""),
        engagement=engagement,
        engagement_label=label,
    )


def fetch(days: int = 7,
          limit: int = 200,
          query: str = "litellm") -> List[Mention]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    since = int(cutoff.timestamp())
    keyword = query.lower()
    mentions: List[Mention] = []

    # Stories first — their point totals become the engagement proxy for the
    # comments underneath them.
    story_points: dict = {}
    pending: List[tuple] = []   # (mention, story_id) awaiting a points backfill
    for tags in ("story", "comment"):
        page, seen_pages = 0, 1
        while page < seen_pages and page < 10 and len(mentions) < limit:
            r = requests.get(API, params={
                "query": query, "tags": tags, "hitsPerPage": 100, "page": page,
                "numericFilters": f"created_at_i>{since}",
            }, timeout=30)
            r.raise_for_status()
            data = r.json()
            seen_pages = data.get("nbPages", 1)
            for h in data.get("hits", []):
                if tags == "story":
                    story_points[str(h.get("objectID"))] = int(h.get("points") or 0)
                sid = str(h.get("story_id")) if tags == "comment" else None
                m = _hit_to_mention(h, keyword, story_points.get(sid) if sid else None)
                if m:
                    mentions.append(m)
                    if sid and sid not in story_points:
                        pending.append((m, sid))
            page += 1

    # Most comments matching the query live in threads that did NOT match it, so
    # their parent story never appeared above. One cheap lookup each fills in the
    # score, deduped and capped so a busy week can't turn into 200 requests.
    for sid in list(dict.fromkeys(s for _, s in pending))[:MAX_STORY_LOOKUPS]:
        try:
            r = requests.get(f"{ITEM_API}/{sid}", timeout=20)
            r.raise_for_status()
            story_points[sid] = int(r.json().get("points") or 0)
        except (requests.RequestException, ValueError):
            story_points[sid] = 0
    for m, sid in pending:
        m.engagement = story_points.get(sid, 0)

    mentions.sort(key=lambda m: m.created_at, reverse=True)
    return mentions[:limit]
