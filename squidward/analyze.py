"""Two-stage analysis: score every mention, then cluster into 3 sentiment groups.

Stage 1 is a wide, cheap fan-out (batched + parallel + cached).
Stage 2 is one expensive, high-quality synthesis call over the compressed output
of stage 1 — never over the raw text. That's what keeps this affordable at
thousands of mentions.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from .cache import Cache
from .llm import GROUPER, SCORER, Spend, supports_json_schema

# logical router name -> the concrete model behind it, for capability checks
REAL_MODEL = {"scorer": SCORER, "grouper": GROUPER}
from .schemas import (CrossSourceContrast, GroupingResult, Mention,
                      MentionScore, ScoreBatch, SourceDigest)

# Bump this whenever a prompt below changes — it invalidates the cache.
PROMPT_VERSION = "v2"

SCORER_SYSTEM = """You are a sentiment analyst for LiteLLM, an open-source LLM \
gateway (Python SDK + proxy server) used by developers to call 100+ model \
providers through one OpenAI-compatible interface.

You will be given numbered developer comments. Score each one independently.

Rules:
- Judge sentiment toward LiteLLM, not toward the user's own code, the model \
providers, or life in general. "Bedrock is being flaky again" is neutral toward \
LiteLLM; "LiteLLM silently drops my Bedrock params" is negative.
- A bug report is negative even when politely worded. A merged fix, a thank-you, \
or "this saved us weeks" is positive.
- Feature requests are neutral unless the person expresses frustration.
- Set on_topic=false for CI output, changelogs, release notes, dependency bumps, \
and anything not written by a human about LiteLLM.
- topic must name the concrete surface: the provider, the feature, the error."""

GROUPER_SYSTEM = """You are briefing the LiteLLM maintainers on what the \
community said this week.

You will receive scored mentions in the form:
  [index] SENTIMENT(intensity) topic — summary

Cluster them into EXACTLY 3 groups. Optimize the grouping for usefulness to the \
team, not for tidy symmetry:
- Group by shared root cause or shared theme, never by sentiment label alone. \
"Negative" is not a group; "Streaming breaks on Bedrock + Vertex" is.
- Cover the loudest and most repeated themes first. A group of 30 mild \
complaints usually outranks a group of 2 furious ones — but say so if the \
2 are severe (data loss, cost blowout, security).
- Assign every on-topic mention to exactly one group. Put genuine miscellany in \
the third group rather than inventing a theme for it.
- why_it_matters is read by people who can ship a fix today. Be concrete and \
unsentimental. No hedging, no "it is important to note".

All mentions in one call come from a SINGLE platform, named in the user \
message along with what that platform structurally is. Calibrate to it: high \
negativity on an issue tracker is the baseline, while the same rate on a forum \
where people are still deciding is a real signal.

Mentions carry their engagement (upvotes, reactions, points). A theme carried by \
a few heavily-upvoted comments outranks one carried by many ignored ones — say \
which is which.

Write plainly and factually throughout. No persona, no jokes, no rhetorical \
flourishes, no editorialising about the project or its maintainers. Every field \
is read by people deciding what to work on; give them observations, not opinions \
about how the observations feel."""


def _extract_json(text: str) -> dict:
    """Parse model output that should be JSON but might be fenced or chatty."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1], strict=False)
            except json.JSONDecodeError:
                continue
    raise ValueError(f"could not parse JSON from model output: {text[:200]!r}")


# litellm renders `response_format` into an Anthropic tool schema. On the legacy
# tool-call path (which older litellm takes for Claude 5 — see
# docs/structured-output-bug.md) the payload comes back wrapped in a single-key
# envelope whose name the model invents: "parameters", "groups", even
# "parameter name". Rather than chase names, unwrap any single-key envelope
# until the object actually carries the fields the schema asks for.
def _unwrap(data: Any, expected: set, depth: int = 5) -> Any:
    for _ in range(depth):
        if isinstance(data, dict) and expected.intersection(data):
            return data                      # already the real payload
        if isinstance(data, dict) and len(data) == 1:
            inner = next(iter(data.values()))
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner, strict=False)
                except json.JSONDecodeError:
                    return data
            data = inner
            continue
        return data
    return data


def _complete(router, model: str, system: str, user: str,
              schema, spend: Spend) -> dict:
    """One structured call. Uses native JSON-schema output where the model
    supports it, and degrades to prompt-coerced JSON where it doesn't."""
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    kwargs: Dict[str, Any] = {"model": model, "messages": messages}

    if supports_json_schema(REAL_MODEL.get(model, model)):
        kwargs["response_format"] = schema
    else:
        messages[1]["content"] += (
            "\n\nRespond with JSON only, matching this schema:\n"
            + json.dumps(schema.model_json_schema())
        )

    response = router.completion(**kwargs)
    spend.record(response)
    return _unwrap(_extract_json(response.choices[0].message.content),
                   set(schema.model_fields))


# --- stage 1 --------------------------------------------------------------

def score_mentions(router,
                   mentions: List[Mention],
                   cache: Cache,
                   spend: Spend,
                   batch_size: int = 8,
                   workers: int = 6) -> List[Dict[str, Any]]:
    """Return one score dict per mention, in the same order as `mentions`."""
    results: List[Optional[Dict[str, Any]]] = [None] * len(mentions)
    todo: List[int] = []

    for i, m in enumerate(mentions):
        cached = cache.get(f"{PROMPT_VERSION}:{SCORER}:{m.id}")
        if cached:
            results[i] = cached
        else:
            todo.append(i)

    batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]

    def run_batch(idxs: List[int]) -> Tuple[List[int], List[dict]]:
        lines = []
        for slot, gi in enumerate(idxs):
            m = mentions[gi]
            lines.append(f"[{slot}] ({m.context}, by {m.author})\n{m.truncated()}")
        user = ("Score every mention below.\n\n" + "\n\n---\n\n".join(lines))
        data = _complete(router, "scorer", SCORER_SYSTEM, user, ScoreBatch, spend)
        if isinstance(data, list):          # bare array instead of {"scores": [...]}
            data = {"scores": data}
        parsed = ScoreBatch.model_validate(data)
        return idxs, [s.model_dump() for s in parsed.scores]

    if batches:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for idxs, scores in pool.map(_safe(run_batch), batches):
                by_slot = {s["index"]: s for s in scores}
                for slot, gi in enumerate(idxs):
                    s = by_slot.get(slot)
                    if s is None:
                        # Scoring failed for this one. Leave it unscored for this
                        # run, but never cache the failure — a cached placeholder
                        # would make every future run inherit a transient error.
                        results[gi] = _unscored()
                        continue
                    results[gi] = s
                    cache.put(f"{PROMPT_VERSION}:{SCORER}:{mentions[gi].id}", s)

    return [r or _unscored() for r in results]


def _unscored() -> Dict[str, Any]:
    return {"index": -1, "on_topic": False, "sentiment": "neutral",
            "intensity": 0.0, "topic": "unscored", "summary": "(scoring failed)"}


def _safe(fn):
    """A failed batch must not take down the run — 8 mentions is not the report."""
    def wrapped(idxs):
        try:
            return fn(idxs)
        except Exception as e:
            detail = " ".join(str(e).split())[:160]
            print(f"  ! batch of {len(idxs)} failed ({type(e).__name__}: {detail})")
            return idxs, []
    return wrapped


# --- stage 2: one grouping call per source --------------------------------

SOURCE_LABEL = {
    "github": "the BerriAI/litellm GitHub issue tracker",
    "reddit": "Reddit",
    "hn": "Hacker News",
    "twitter": "X/Twitter",
}

SOURCE_CHARACTER = {
    "github": "Everyone here already chose LiteLLM and cares enough to file. "
              "Expect defect reports and review-queue pressure, not adoption "
              "doubt. High negativity is the baseline, not news.",
    "reddit": "People here are evaluating, comparing, and deciding whether to "
              "adopt at all. Expect comparisons to OpenRouter, Portkey, and "
              "raw provider SDKs.",
    "hn": "Mostly people talking about something else who mention LiteLLM in "
          "passing. The comparisons are unsolicited, which makes them honest.",
    "twitter": "Short, reactive, low context. Announcements and hot takes. "
               "Weight volume lightly; a single viral complaint is not a trend.",
}


def group_source(router,
                 platform: str,
                 mentions: List[Mention],
                 scores: List[Dict[str, Any]],
                 spend: Spend) -> Tuple[Optional[SourceDigest], List[int]]:
    """Cluster one platform's on-topic mentions into up to 3 groups.

    Returns (None, []) when the platform has too little to say — better an
    honest gap in the report than three groups invented from four comments.
    """
    keep = [i for i, s in enumerate(scores)
            if s.get("on_topic") and mentions[i].platform == platform]
    if len(keep) < 2:
        return None, keep

    lines = []
    for slot, gi in enumerate(keep):
        s = scores[gi]
        m = mentions[gi]
        eng = f", {m.engagement} {m.engagement_label}" if m.engagement else ""
        lines.append(f"[{slot}] {s['sentiment'].upper()}({s['intensity']:.1f}{eng}) "
                     f"{s['topic']} — {s['summary']}")

    user = (f"{len(keep)} scored mentions about LiteLLM from "
            f"{SOURCE_LABEL.get(platform, platform)} over the past week.\n\n"
            f"What this platform is: {SOURCE_CHARACTER.get(platform, '')}\n\n"
            + "\n".join(lines))

    data = _complete(router, "grouper", GROUPER_SYSTEM, user, SourceDigest, spend)
    digest = SourceDigest.model_validate(data)
    # Trim to 3 defensively — the model is asked for at most 3, not trusted for it.
    digest.groups = digest.groups[:3]
    return digest, keep


def contrast_sources(router,
                     per_source: Dict[str, Any],
                     spend: Spend) -> Optional[CrossSourceContrast]:
    """One cheap call that reads only the per-source group names and rationales."""
    if len(per_source) < 2:
        return None
    lines = []
    for platform, d in per_source.items():
        lines.append(f"## {SOURCE_LABEL.get(platform, platform)} "
                     f"({d['on_topic']} on-topic of {d['scanned']} scanned)")
        for g in d["groups"]:
            lines.append(f"  - [{g['dominant_sentiment']}, {g['count']} mentions] "
                         f"{g['name']}: {g['why_it_matters']}")
    data = _complete(router, "grouper", CONTRAST_SYSTEM, "\n".join(lines),
                     CrossSourceContrast, spend)
    return CrossSourceContrast.model_validate(data)


CONTRAST_SYSTEM = """You are briefing the LiteLLM maintainers on a week of \
community sentiment gathered from several platforms.

You will receive a per-platform summary. Write the cross-platform read.

The point is not to average the platforms together — it is to say what each one \
sees that the others structurally cannot. An issue tracker only hears from \
people who already adopted. A forum hears from people deciding whether to. A \
social feed hears reactions without context. Where two platforms disagree, that \
disagreement is the finding.

Never describe a platform that reported no data. If a platform is absent from \
the input, it is absent from your answer.

Both fields are plain and factual. No persona, no jokes, no editorialising."""
