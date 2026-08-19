"""sentimental squidward — what the internet said about LiteLLM this week."""

from . import env as _env  # noqa: F401  (loads .env on import)

import argparse
import json
import os
import sys

from . import digest as digest_mod
from . import report as report_mod
from .digest import BOT_NAME
from .sources import DEFAULT, KEYLESS, SOURCES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "out")

DOT = {"positive": "+", "negative": "-", "mixed": "~", "neutral": "."}


INTRO = ("Mr. Krabs asked me analyze the LiteLLM sentiment on GitHub, "
         "HackerNews, and Twitter. Another day, another migraine!")

METHOD = ("Methodology: I use LiteLLM to switch between two models: Haiku 4.5 "
          "scores every comment for relevance and sentiment (positive, negative, "
          "mixed, neutral), then Sonnet 5 sorts each platform's comments into its "
          "three main sentiment groups and summarizes the feedback in each. "
          "Source comments linked for every grouping.")

CAVEAT = ("Squidwardbot is in testing. If something seems wrong, it probably is. "
          "Oh, my aching tentacles")

REPO = "https://github.com/esigel-stax/sentimental-squidward"


def render(d: dict, files: dict) -> str:
    """The finished post. What this prints is what gets pasted."""
    out = ["", "SENTIMENTAL SQUIDWARD", "",
           _wrap(INTRO, 76), "", _wrap(METHOD, 76), "",
           f"{d.get('total_on_topic', 0)} comments worth reading, out of "
           f"{d.get('total_scanned', 0)} I had to read."]

    for source, sd in d["by_source"].items():
        out += ["", f"{source.upper()} - {sd['on_topic']}"]
        if not sd["groups"]:
            out.append("  nothing worth grouping")
            continue
        width = max(len(g["dominant_sentiment"]) for g in sd["groups"])
        for g in sd["groups"]:
            out.append(f"  {g['dominant_sentiment']:<{width}}  {g['count']:>2}   "
                       f"{g['name']}")
            f = files.get(f"{source}/{g['name']}")
            if f:
                out.append(f"  {'':<{width}}       {os.path.relpath(f, ROOT)}")

    if d.get("unavailable"):
        out += [""] + [f"{k} unavailable" for k in d["unavailable"]]

    out += ["", f"Code: {REPO}", "", _wrap(CAVEAT, 76), ""]
    return "\n".join(out)


def _wrap(text: str, width: int, indent: str = "") -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return ("\n" + indent).join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="squidward", description=__doc__)
    p.add_argument("--source", default=",".join(DEFAULT),
                   help="comma-separated: " + ", ".join(sorted(SOURCES))
                        + f" (default: {','.join(DEFAULT)})")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--limit", type=int, default=200,
                   help="max mentions across all sources")
    p.add_argument("--repo", default="BerriAI/litellm")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--json", dest="json_only", action="store_true")
    args = p.parse_args(argv)

    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")):
        print("No model API key in the environment. Export ANTHROPIC_API_KEY.",
              file=sys.stderr)
        return 2

    wanted = [s.strip() for s in args.source.split(",") if s.strip()]
    unknown = [s for s in wanted if s not in SOURCES]
    if unknown:
        print(f"unknown source(s): {', '.join(unknown)}. "
              f"available: {', '.join(sorted(SOURCES))}", file=sys.stderr)
        return 2

    log = (lambda *a: None) if args.json_only else (lambda *a: print(*a))
    try:
        d = digest_mod.build(wanted, days=args.days, limit=args.limit,
                             use_cache=not args.no_cache, out_dir=OUT_DIR,
                             repo=args.repo, log=log)
    except RuntimeError as e:
        print(f"\n{e}", file=sys.stderr)
        return 1

    path = digest_mod.save(d, OUT_DIR)
    if args.json_only:
        print(json.dumps(d, indent=2))
        return 0

    files = report_mod.save_group_files(d, OUT_DIR)
    print(render(d, files))
    print(f"  wrote {path}")
    print(f"  and  {os.path.join(OUT_DIR, 'latest.json')}  (what the bot reads)")
    print(f"  and  {report_mod.save(d, OUT_DIR)}  (full record)")
    print(f"  {d['spend']['summary']}\n")
    return 0
