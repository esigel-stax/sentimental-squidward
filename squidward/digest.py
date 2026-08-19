"""Builds the digest: the one artifact everything downstream reads.

The CLI prints it. The Discord bot serves it. Nothing else re-runs the pipeline,
so a Discord user clicking a button never triggers a model call — the click just
reads a group's mentions, already sorted by engagement.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .analyze import contrast_sources, group_source, score_mentions
from .cache import Cache
from .llm import GROUPER, SCORER, Spend, build_router
from .schemas import Mention
from .sources import SOURCES

BOT_NAME = "Sentimental Squidward"


def build(sources: List[str],
          days: int = 7,
          limit: int = 200,
          use_cache: bool = True,
          out_dir: str = "out",
          repo: str = "BerriAI/litellm",
          log: Optional[Callable[..., None]] = None) -> Dict[str, Any]:
    log = log or (lambda *a: None)
    started = datetime.now(timezone.utc)

    # --- 1. ingest every source; a dead one must not sink the run -----------
    mentions: List[Mention] = []
    scanned: Dict[str, int] = {}
    unavailable: Dict[str, str] = {}
    per_source_limit = max(25, limit // max(1, len(sources)))

    log(f"[1/4] ingesting {', '.join(sources)} · last {days} days")
    for name in sources:
        kw = {"repo": repo} if name == "github" else {}
        try:
            got = SOURCES[name](days=days, limit=per_source_limit, **kw)
        except Exception as e:
            reason = " ".join(str(e).split())[:200]
            log(f"      ! {name}: unavailable — {reason}")
            unavailable[name] = reason
            continue
        scanned[name] = len(got)
        log(f"      {name}: {len(got)} mentions")
        mentions.extend(got)

    if not mentions:
        raise RuntimeError("No mentions from any source. "
                           f"Unavailable: {unavailable or 'none'}")
    mentions.sort(key=lambda m: m.created_at, reverse=True)

    # --- 2. score everything in one pooled pass -----------------------------
    router, spend = build_router(), Spend()
    cache = Cache(os.path.join(out_dir, ".score-cache.json"), enabled=use_cache)
    log(f"[2/4] scoring {len(mentions)} mentions with {SCORER}")
    scores = score_mentions(router, mentions, cache, spend)
    cache.flush()
    log(f"      {sum(1 for s in scores if s.get('on_topic'))} on-topic · "
        f"{cache.hits} cached · {spend}")

    # --- 3. group per source ------------------------------------------------
    log(f"[3/4] grouping per source with {GROUPER}")
    per_source: Dict[str, Any] = {}
    for name in sources:
        if name in unavailable:
            continue
        digest, keep = group_source(router, name, mentions, scores, spend)
        if digest is None:
            log(f"      {name}: too few on-topic mentions ({len(keep)}) to group")
            per_source[name] = {
                "scanned": scanned.get(name, 0), "on_topic": len(keep),
                "groups": [], "thin": True,
            }
            continue

        groups = []
        for g in digest.groups:
            idxs = [keep[i] for i in g.mention_indexes if 0 <= i < len(keep)]
            # Engagement ordering is the whole point of the click-through.
            idxs.sort(key=lambda gi: (mentions[gi].engagement,
                                      mentions[gi].created_at), reverse=True)
            groups.append({
                "name": g.name,
                "dominant_sentiment": g.dominant_sentiment,
                "what_people_say": g.what_people_say,
                "why_it_matters": g.why_it_matters,
                "count": len(idxs),
                "share": (100.0 * len(idxs) / len(keep)) if keep else 0.0,
                "mentions": [_mention_row(mentions[gi], scores[gi]) for gi in idxs],
            })
        per_source[name] = {
            "scanned": scanned.get(name, 0), "on_topic": len(keep),
            "groups": groups, "thin": False,
        }
        log(f"      {name}: {len(groups)} groups over {len(keep)} on-topic")

    # --- 4. cross-source contrast ------------------------------------------
    contrast = None
    usable = {k: v for k, v in per_source.items() if v["groups"]}
    if len(usable) >= 2:
        log("[4/4] contrasting sources")
        c = contrast_sources(router, usable, spend)
        if c:
            contrast = {"headline": c.headline, "contrast": c.contrast}
    else:
        log("[4/4] only one source produced groups — skipping contrast")

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    return {
        "bot": BOT_NAME,
        "generated_at": started.isoformat(),
        "days": days,
        "sources_requested": sources,
        "unavailable": unavailable,
        "total_scanned": len(mentions),
        "total_on_topic": sum(1 for s in scores if s.get("on_topic")),
        "contrast": contrast,
        "by_source": per_source,
        "spend": {"summary": str(spend), "usd": round(spend.usd, 4),
                  "calls": spend.calls, "seconds": round(elapsed, 1)},
    }


def _mention_row(m: Mention, score: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "author": m.author,
        "url": m.url,
        "text": m.truncated(600),
        "created_at": m.created_at,
        "context": m.context,
        "engagement": m.engagement,
        "engagement_label": m.engagement_label or "engagement",
        "sentiment": score.get("sentiment", "neutral"),
        "intensity": score.get("intensity", 0.0),
        "topic": score.get("topic", ""),
        "summary": score.get("summary", ""),
    }


def save(digest: Dict[str, Any], out_dir: str = "out") -> str:
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(out_dir, f"digest-{stamp}.json")
    with open(path, "w") as f:
        json.dump(digest, f, indent=2)
    # The bot always reads this stable path.
    latest = os.path.join(out_dir, "latest.json")
    with open(latest, "w") as f:
        json.dump(digest, f, indent=2)
    return path


def load_latest(out_dir: str = "out") -> Optional[Dict[str, Any]]:
    path = os.path.join(out_dir, "latest.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)
