"""Data shapes shared across Squidward.

Two kinds of type live here:
  * `Mention` — a normalized comment from any platform. Every source adapter
    (github, reddit, hn, ...) must emit these and nothing else. This is the
    seam that makes adding a platform a ~100 line job.
  * The pydantic models — the JSON contracts we hand to litellm as
    `response_format`, so the LLM's output is schema-validated, not vibes-parsed.
"""

import json
from dataclasses import dataclass, asdict
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


def _as_list(v: Any) -> Any:
    """Coerce a stringified array back into a list.

    Structured output is not uniform across providers: when litellm renders a
    nested `List[BaseModel]` into an Anthropic tool schema, the model sometimes
    fills the field with a JSON *string* rather than a JSON array. The content
    is correct, just double-encoded. Rather than fight the provider, accept both
    shapes — this is the same defensive posture litellm itself takes when
    normalizing provider responses.
    """
    # {"groups": {"groups": [...]}} — the tool path sometimes repeats the field
    # name one level down. Unwrap a single-key dict whose value is the list.
    if isinstance(v, dict) and len(v) == 1:
        inner = next(iter(v.values()))
        if isinstance(inner, (list, str)):
            v = inner
    if isinstance(v, str):
        try:
            return json.loads(v, strict=False)
        except json.JSONDecodeError as e:
            # A double-encoded field that won't parse is almost always a
            # response cut off at max_tokens. Say that, rather than letting
            # pydantic report a confusing "expected list, got str".
            stripped = v.rstrip()
            if stripped and stripped[-1] not in "]}":
                raise ValueError(
                    "model output looks truncated mid-JSON "
                    f"({len(v)} chars, ends {stripped[-40:]!r}) — raise "
                    "max_tokens for this deployment in llm.py"
                ) from e
            return v
    return v

Sentiment = Literal["positive", "negative", "neutral", "mixed"]


@dataclass
class Mention:
    """One thing a human said about LiteLLM, somewhere."""

    id: str            # stable, platform-prefixed, e.g. "github:comment:123"
    platform: str      # "github" | "reddit" | "hn" | ...
    author: str
    text: str
    url: str
    created_at: str    # ISO-8601 UTC
    context: str = ""  # thread title, subreddit, channel — whatever frames it

    # Engagement is not comparable across platforms — 40 Reddit upvotes and 40
    # GitHub reactions mean very different things — so we carry the raw number
    # AND what it is called, and only ever rank within a single platform.
    engagement: int = 0
    engagement_label: str = ""   # "upvotes" | "reactions" | "likes" | "story points"

    def truncated(self, limit: int = 1200) -> str:
        t = " ".join(self.text.split())
        return t if len(t) <= limit else t[:limit] + " …[truncated]"

    def as_dict(self) -> dict:
        return asdict(self)


# --- LLM output contracts -------------------------------------------------
# These become JSON schemas via litellm's `response_format=`. Keep the field
# descriptions sharp: they are the prompt as much as the system message is.


class MentionScore(BaseModel):
    index: int = Field(description="The [n] index of the mention being scored.")
    on_topic: bool = Field(
        description="True only if this is a human talking about LiteLLM itself "
        "(the library, proxy, or company). False for bot noise, CI output, or "
        "comments about unrelated projects."
    )
    sentiment: Sentiment = Field(description="Overall sentiment toward LiteLLM.")
    intensity: float = Field(
        ge=0.0, le=1.0,
        description="How strongly the sentiment is felt. 0.0 = passing remark, "
        "1.0 = furious or delighted.",
    )
    topic: str = Field(description="The concrete subject, 2-6 words. e.g. "
                       "'Bedrock streaming timeouts', 'router fallback config'.")
    summary: str = Field(description="What this person is actually saying, "
                         "max 25 words, plain language, no preamble.")


class ScoreBatch(BaseModel):
    scores: List[MentionScore]

    @field_validator("scores", mode="before")
    @classmethod
    def _coerce_scores(cls, v: Any) -> Any:
        return _as_list(v)


class SentimentGroup(BaseModel):
    name: str = Field(description="Short punchy name for this group, max 6 words.")
    dominant_sentiment: Sentiment
    what_people_say: str = Field(
        description="2-3 sentences synthesizing the group. Concrete and specific "
        "— name the features, providers, and error modes people mention."
    )
    why_it_matters: str = Field(
        description="One sentence on the business or product implication for the "
        "LiteLLM team. Be direct; this is read by maintainers."
    )
    mention_indexes: List[int] = Field(
        description="Indexes of every mention belonging to this group."
    )

    @field_validator("mention_indexes", mode="before")
    @classmethod
    def _coerce_indexes(cls, v: Any) -> Any:
        return _as_list(v)


class SourceDigest(BaseModel):
    """The top sentiment groups for ONE platform."""

    groups: List[SentimentGroup] = Field(
        description="At most 3 groups, most important first. Return fewer than "
        "3 if the data genuinely does not support 3 distinct themes — two honest "
        "groups beat three padded ones."
    )

    @field_validator("groups", mode="before")
    @classmethod
    def _coerce_source_groups(cls, v: Any) -> Any:
        return _as_list(v)


class CrossSourceContrast(BaseModel):
    headline: str = Field(description="One factual sentence covering the whole "
                          "week across every platform, max 25 words. State what "
                          "happened. No voice, no commentary, no jokes.")
    contrast: str = Field(
        description="3-4 sentences on how the platforms differ as signals. What "
        "does each one see that the others structurally cannot? Sober and "
        "factual here — this is the part the maintainers act on. Never claim a "
        "platform said something when it returned no data."
    )


class GroupingResult(BaseModel):
    headline: str = Field(description="One sentence summarizing the whole week, "
                          "max 20 words. The thing you'd say in standup.")
    groups: List[SentimentGroup] = Field(
        description="Exactly 3 groups, ordered most important first."
    )

    @field_validator("groups", mode="before")
    @classmethod
    def _coerce_groups(cls, v: Any) -> Any:
        return _as_list(v)
    platform_contrast: str = Field(
        description="2-3 sentences on how sentiment differs BY PLATFORM, using "
        "the platform tag on each mention. Name what each platform is good for "
        "as a signal. If only one platform is present, say so plainly in one "
        "sentence and do not speculate about the others."
    )
