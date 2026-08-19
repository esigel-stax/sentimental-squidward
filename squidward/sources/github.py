"""GitHub source adapter.

Pulls the last N days of human chatter from a repo: issue bodies and issue/PR
comments. Works unauthenticated (60 req/hr, ~6000 comments) — set GITHUB_TOKEN
to get 5000 req/hr.

Deliberately NOT using /search/issues: search is capped at 10 req/min
unauthenticated and its relevance ranking hides recent low-engagement threads,
which are exactly the ones an FDE wants to see.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from ..schemas import Mention

API = "https://api.github.com"
PLATFORM = "github"

# The comments endpoint reliably 504s at per_page=100 on a repo this busy but
# serves 50 fine. Halving the page size costs one extra request per 100 items.
PAGE_SIZE = 50

# Accounts whose output is machinery, not opinion.
BOT_LOGINS = {
    "codspeed-hq[bot]", "github-actions[bot]", "dependabot[bot]", "codecov[bot]",
    "CLAassistant", "vercel[bot]", "netlify[bot]", "sonarcloud[bot]",
    "greptileai", "greptile-apps[bot]", "coderabbitai[bot]", "sweep-ai[bot]",
    "semantic-release-bot", "renovate[bot]", "stale[bot]", "cursor[bot]",
}

# Substrings that mark a body as generated, even from a human-looking account.
BOT_BODY_MARKERS = (
    "__CODSPEED_PERFORMANCE_REPORT_COMMENT__",
    "cla-assistant.io/pull/badge",
    "<!-- This is an auto-generated comment",
    "## Walkthrough",  # coderabbit
    "Codecov Report",
)


def _headers(token: Optional[str]) -> dict:
    h = {"Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28",
         "User-Agent": "squidward-sentiment-bot"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url: str, params: dict, token: Optional[str], attempts: int = 3) -> list:
    # GitHub serves transient 502/503/504 under load often enough that a single
    # unlucky page would otherwise abort a whole week's ingest.
    r = None
    for attempt in range(attempts):
        r = requests.get(url, params=params, headers=_headers(token), timeout=30)
        if r.status_code not in (502, 503, 504):
            break
        if attempt < attempts - 1:
            time.sleep(2 ** attempt)
    if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
        reset = int(r.headers.get("x-ratelimit-reset", "0"))
        wait = max(0, reset - int(time.time()))
        raise RuntimeError(
            f"GitHub rate limit exhausted (resets in {wait // 60}m {wait % 60}s). "
            "Set GITHUB_TOKEN in your environment to raise the limit to 5000/hr."
        )
    r.raise_for_status()
    return r.json()


def _is_noise(login: str, body: str) -> bool:
    if not body or not body.strip():
        return True
    if login in BOT_LOGINS or login.endswith("[bot]"):
        return True
    if any(m in body for m in BOT_BODY_MARKERS):
        return True
    # "@greptileai re-review", "/gemini review" — human keystrokes, zero signal.
    stripped = body.strip()
    if len(stripped) < 40 and (stripped.startswith("@") or stripped.startswith("/")):
        return True
    return False


def fetch(days: int = 7,
          limit: int = 400,
          repo: str = "BerriAI/litellm",
          token: Optional[str] = None) -> List[Mention]:
    """Return human mentions from `repo` created in the last `days` days."""
    token = token or os.getenv("GITHUB_TOKEN")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    mentions: List[Mention] = []

    # --- issue + PR comments, newest first, walk back until we pass the cutoff
    page = 1
    while len(mentions) < limit and page <= 40:
        batch = _get(f"{API}/repos/{repo}/issues/comments",
                     {"sort": "created", "direction": "desc",
                      "per_page": PAGE_SIZE, "page": page}, token)
        if not batch:
            break
        stop = False
        for c in batch:
            created = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
            if created < cutoff:
                stop = True
                break
            login = (c.get("user") or {}).get("login", "unknown")
            body = c.get("body") or ""
            if _is_noise(login, body):
                continue
            mentions.append(Mention(
                id=f"{PLATFORM}:comment:{c['id']}",
                platform=PLATFORM,
                author=login,
                text=body,
                url=c["html_url"],
                created_at=c["created_at"],
                context=f"comment on {repo}",
                engagement=(c.get("reactions") or {}).get("total_count", 0),
                engagement_label="reactions",
            ))
        if stop:
            break
        page += 1

    # --- issue bodies (skip PRs: those are contributor intent, not user sentiment)
    page = 1
    while len(mentions) < limit and page <= 10:
        batch = _get(f"{API}/repos/{repo}/issues",
                     {"state": "all", "sort": "created", "direction": "desc",
                      "per_page": PAGE_SIZE, "page": page}, token)
        if not batch:
            break
        stop = False
        for i in batch:
            created = datetime.fromisoformat(i["created_at"].replace("Z", "+00:00"))
            if created < cutoff:
                stop = True
                break
            if "pull_request" in i:
                continue
            login = (i.get("user") or {}).get("login", "unknown")
            body = i.get("body") or ""
            title = i.get("title") or ""
            if _is_noise(login, title + "\n" + body):
                continue
            mentions.append(Mention(
                id=f"{PLATFORM}:issue:{i['id']}",
                platform=PLATFORM,
                author=login,
                text=f"{title}\n\n{body}",
                url=i["html_url"],
                created_at=i["created_at"],
                context=f"issue #{i['number']} on {repo}",
                engagement=((i.get("reactions") or {}).get("total_count", 0)
                            + (i.get("comments") or 0)),
                engagement_label="reactions+replies",
            ))
        if stop:
            break
        page += 1

    mentions.sort(key=lambda m: m.created_at, reverse=True)
    return mentions[:limit]
