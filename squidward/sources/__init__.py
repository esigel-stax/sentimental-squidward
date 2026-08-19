"""Source registry.

Adding a platform = write a module exposing `fetch(days, limit, **kw) -> List[Mention]`
and register it here. Nothing downstream changes.

Cost/auth at a glance:
    hn       free, no auth          — best for competitive comparison talk
    github   free, token optional   — best for defect reports
    reddit   free, OAuth required   — best for adoption/evaluation sentiment
    twitter  PAID, bearer required  — broadest reach, lowest signal density
"""

from . import github, hackernews, reddit, stackoverflow, twitter

SOURCES = {
    "github": github.fetch,
    "hn": hackernews.fetch,
    "reddit": reddit.fetch,
    # Available, but ~5 LiteLLM questions exist per YEAR — opt in with
    # --source stackoverflow, don't expect a weekly signal from it.
    "stackoverflow": stackoverflow.fetch,
    "twitter": twitter.fetch,
}

# Sources that work with no credentials at all.
KEYLESS = ["github", "hn"]

# The default run. Reddit needs a free OAuth app; if it isn't configured the run
# logs it, records it in `unavailable`, and continues with the other two.
DEFAULT = ["github", "hn", "twitter"]
