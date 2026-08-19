"""Stack Overflow source adapter, via the Stack Exchange API.

Zero auth: 300 requests/day from an unregistered IP, 10,000/day with a free key
(StackApps). A weekly digest uses two or three.

Distinct from the other three sources in a useful way: nobody posts to Stack
Overflow to praise or complain. They post because they are stuck. So the
sentiment here is narrow — frustration, confusion, resolution — but the *topics*
are the highest-fidelity signal in the whole corpus, because each one is a place
the documentation or the API surface failed a real person.

Engagement is the vote score, which on SO is a genuine quality signal rather
than a popularity one — a +12 question is one a lot of people also had.
"""

import html
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from ..schemas import Mention

PLATFORM = "stackoverflow"
API = "https://api.stackexchange.com/2.3/search/advanced"
SITE = "stackoverflow"

TAG_RE = re.compile(r"<[^>]+>")
CODE_RE = re.compile(r"<pre>.*?</pre>", re.DOTALL)


def _clean(body: str) -> str:
    """Strip HTML, and drop code blocks — they blow the token budget and the
    model scores prose, not tracebacks."""
    if not body:
        return ""
    body = CODE_RE.sub(" [code] ", body)
    return " ".join(html.unescape(TAG_RE.sub(" ", body)).split())


def fetch(days: int = 7,
          limit: int = 100,
          query: str = "litellm",
          api_key: Optional[str] = None) -> List[Mention]:
    api_key = api_key or os.getenv("STACKEXCHANGE_KEY")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    mentions: List[Mention] = []
    page = 1

    while len(mentions) < limit and page <= 5:
        params = {
            "order": "desc", "sort": "creation", "q": query, "site": SITE,
            "pagesize": 100, "page": page, "filter": "withbody",
            "fromdate": int(cutoff.timestamp()),
        }
        if api_key:
            params["key"] = api_key

        r = requests.get(API, params=params, timeout=30,
                         headers={"Accept-Encoding": "gzip"})
        if r.status_code == 400:
            raise RuntimeError(f"Stack Exchange rejected the query: {r.text[:200]}")
        r.raise_for_status()
        data = r.json()

        # The API asks callers to sleep when it says so; ignoring it gets you
        # throttled for the day.
        backoff = data.get("backoff")
        if backoff:
            time.sleep(min(int(backoff), 10))

        for i in data.get("items", []):
            created = datetime.fromtimestamp(i.get("creation_date", 0), timezone.utc)
            if created < cutoff:
                continue
            body = _clean(i.get("body", ""))
            title = i.get("title") or ""
            if query.lower() not in (body + " " + title).lower():
                continue
            owner = (i.get("owner") or {}).get("display_name", "unknown")
            tags = ", ".join(i.get("tags", [])[:4])
            mentions.append(Mention(
                id=f"{PLATFORM}:q:{i.get('question_id')}",
                platform=PLATFORM,
                author=owner,
                text=f"{html.unescape(title)}\n\n{body}",
                url=i.get("link", ""),
                created_at=created.isoformat().replace("+00:00", "Z"),
                context=f"SO question [{tags}] · {i.get('answer_count', 0)} answers",
                engagement=int(i.get("score", 0) or 0),
                engagement_label="votes",
            ))

        if not data.get("has_more"):
            break
        page += 1

    mentions.sort(key=lambda m: m.created_at, reverse=True)
    return mentions[:limit]
