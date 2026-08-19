#!/usr/bin/env python3
"""Render a SAMPLE digest through the real renderers.

The mentions, authors, URLs, and engagement numbers below are REAL — pulled from
Hacker News and GitHub on 2026-08-19. The group names, prose, and Squidward
commentary are hand-authored placeholders standing in for what the model would
write, because this sample is generated without live model calls.

Run `python3 run.py` for the genuine article.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from squidward import bot_discord as B
from squidward.cli import render

def m(author, url, text, eng, label, sentiment, summary, context):
    return {"author": author, "url": url, "text": text, "created_at": "2026-08-18T00:00:00Z",
            "context": context, "engagement": eng, "engagement_label": label,
            "sentiment": sentiment, "intensity": 0.7, "topic": "", "summary": summary}

HN_T = "HN comment on \"Bifrost: open-source LLM gateway\""
HN_B = "HN comment on \"Ask HN: how do you serve models internally?\""

DIGEST = {
  "bot": "Sentimental Squidward",
  "generated_at": "2026-08-19T17:20:00+00:00",
  "days": 7,
  "sources_requested": ["hn", "github", "twitter"],
  "unavailable": {"twitter": "X returned 403 for /2/tweets/search/recent. The Free "
                             "access tier is write-only — search requires Basic or above."},
  "total_scanned": 91, "total_on_topic": 38,
  "contrast": {
    "headline": "Two rooms, two verdicts, and neither one has met the other.",
    "contrast": ("Hacker News is where LiteLLM gets compared to things it did not "
                 "ask to be compared to — a competitor launch thread produced both "
                 "the strongest endorsement and the harshest dismissal of the week, "
                 "from people with no stake in either. GitHub produces none of that: "
                 "everyone there already adopted, so its negativity is defect "
                 "reporting, not doubt. Operational friction — 'not trivial to run', "
                 "Python packaging, the database requirement — appears on HN as a "
                 "reason people chose something else, and appears on GitHub not at "
                 "all. That gap is the finding.")},
  "by_source": {
    "hn": {
      "scanned": 31, "on_topic": 22, "thin": False,
      "headline": "Someone launched a competitor and the whole neighbourhood had opinions about me.",
      "groups": [
        {"name": "Ops friction is the reason people leave",
         "dominant_sentiment": "negative", "count": 9, "share": 40.9,
         "what_people_say": ("The complaint is never the feature set — it is what it "
            "takes to run. Python dependency management, the database requirement, and "
            "config-file-only operation come up repeatedly, usually alongside an "
            "admission that LiteLLM is the more mature product."),
         "why_it_matters": ("These users evaluated LiteLLM, agreed it was better, and "
            "chose otherwise on packaging alone. A single-binary distribution would "
            "close the gap they name."),
         "squidward_says": "They like everything about me except the experience of using me.",
         "mentions": [
           m("apatheticonion", "https://news.ycombinator.com/item?id=49000176",
             "Yeah I looked at it, LiteLLM is functionally more mature. The only reason I "
             "didn't go for it is I'm not a fan of Python dependency management, Bifrost is "
             "just a single executable that uses nearly no memory and is lightning fast.",
             877, "story points", "negative", "Chose a competitor purely over Python packaging.", HN_T),
           m("aftbit", "https://news.ycombinator.com/item?id=49001243",
             "Can you configure Bifrost using entirely config files without the web "
             "interface? Can it run without a database or anything stateful? I'm using "
             "LiteLLM but it is not trivial to run.",
             877, "story points", "negative", "Current user: works, but not trivial to run.", HN_T),
           m("CuriouslyC", "https://news.ycombinator.com/item?id=49001644",
             "LiteLLM is bad. Shit performance, buggy, and none of it surprising if you "
             "look at the tangled mess that is their codebase.",
             877, "story points", "negative", "Blunt dismissal on performance and code quality.", HN_T)]},
        {"name": "Quietly, it is the default",
         "dominant_sentiment": "positive", "count": 7, "share": 31.8,
         "what_people_say": ("Unprompted, in threads about something else, people report "
            "LiteLLM as the thing their employer already standardised on for internal "
            "model access — usually as an aside, which is what makes it credible."),
         "why_it_matters": ("This is incumbency, and it is the strongest asset in the "
            "corpus. It appears nowhere on GitHub, because GitHub only hears from people "
            "with a problem."),
         "squidward_says": "Apparently I am load-bearing. Nobody thought to mention it to me.",
         "mentions": [
           m("andersonpico", "https://news.ycombinator.com/item?id=48986516",
             "Every company that I've worked with that provided models internally did so "
             "through LiteLLM and offered both Anthropic and OpenAI models so it was "
             "trivial to switch between them.",
             995, "story points", "positive", "Reports LiteLLM as the internal default everywhere they've worked.", HN_B),
           m("Aurornis", "https://news.ycombinator.com/item?id=48987964",
             "I like all the different comments in this thread saying that most companies "
             "do X, where X is a different answer from each person: LiteLLM, GitHub "
             "Copilot, Claude Code.",
             995, "story points", "neutral", "Notes LiteLLM among the named defaults.", HN_B)]},
        {"name": "Gateway shopping season",
         "dominant_sentiment": "mixed", "count": 6, "share": 27.3,
         "what_people_say": ("People are actively comparing gateways — Bifrost, Bedrock, "
            "OpenRouter — and LiteLLM is the reference point they measure against. The "
            "tone is evaluative rather than loyal."),
         "why_it_matters": ("Being the benchmark is good; being the benchmark during a "
            "competitor's launch week is a retention risk worth watching."),
         "squidward_says": "I am the one they compare the others to. It is not a compliment, it is a starting price.",
         "mentions": [
           m("robbiet480", "https://news.ycombinator.com/item?id=49000113",
             "Did you look at LiteLLM at all? It seems fine but Bifrost looks interesting too.",
             877, "story points", "mixed", "Treats LiteLLM as the baseline while shopping.", HN_T),
           m("jdgoesmarching", "https://news.ycombinator.com/item?id=49326735",
             "AWS Bedrock doesn't even try to stay on top of new open source models or "
             "their API capabilities. We've also run into all kinds of frustrating rate "
             "limiting and slowness issues.",
             475, "story points", "mixed", "Frustrated with Bedrock; weighing alternatives.",
             "HN comment on \"Stripe will reportedly acquire OpenRouter\"")]}]},
    "github": {
      "scanned": 60, "on_topic": 16, "thin": False,
      "headline": "Sixty comments. Sixteen were about the software. I counted twice.",
      "groups": [
        {"name": "The review queue, still",
         "dominant_sentiment": "negative", "count": 7, "share": 43.8,
         "what_people_say": ("Contributors with green CI, signed CLAs and every bot "
            "satisfied, bumping the same PRs across multiple days. Several state plainly "
            "that they are blocked on maintainer approval and nothing else."),
         "why_it_matters": ("Not a patch, a process. One contributor arrived with "
            "enterprise customers and an offer to co-market, and is still waiting."),
         "squidward_says": "They are so polite about being ignored. I could never.",
         "mentions": [
           m("deepanshululla", "https://github.com/BerriAI/litellm/pull/36657#issuecomment-5343507117",
             "All automated gates are green: CI fully passing, Greptile 5/5 at current HEAD, "
             "veria-ai 0/10 risk, all 5 review threads resolved, no merge conflicts. Ready "
             "for maintainer review whenever convenient.",
             1, "reactions", "negative", "Every gate green; blocked only on maintainer review.",
             "comment on BerriAI/litellm")]},
        {"name": "Provider translation edges",
         "dominant_sentiment": "negative", "count": 5, "share": 31.3,
         "what_people_say": ("tool_choice mapping, Gemini's camelCase systemInstruction, "
            "and wrong capability flags in the model catalog. Every one lands on the seam "
            "the gateway exists to hide."),
         "why_it_matters": ("Users hitting these don't file 'mapping bug' — they conclude "
            "the abstraction leaks and go shopping. See the HN group above."),
         "squidward_says": "One interface for a hundred providers. The providers were not consulted.",
         "mentions": [
           m("thehaffk", "https://github.com/BerriAI/litellm/issues/32505#issuecomment-5342911159",
             "Proxy config routes gpt-5.4 through the Responses API bridge... no tool_choice "
             "200, auto 400, any 400, none 400, tool 200. The error text is worth quoting, "
             "because it sends people looking in the wrong place.",
             0, "reactions", "negative", "tool_choice mapping returns 400s with misleading errors.",
             "comment on BerriAI/litellm")]},
        {"name": "Proxy state, quietly on fire",
         "dominant_sentiment": "negative", "count": 4, "share": 25.0,
         "what_people_say": ("A /health endpoint leaking aws_session_token, a budget reset "
            "computed for the year 2083, and 404 retries cascading into fleet-wide 5xx. "
            "Small group, worst contents."),
         "why_it_matters": ("These only bite at scale, in production, on the deployments "
            "that pay. Two are security-shaped."),
         "squidward_says": "A credential leak and a budget that resets in 2083. At least the budget will outlive the incident.",
         "mentions": [
           m("Siraj637909", "https://github.com/BerriAI/litellm/pull/37090#issuecomment-5341423372",
             "GET /health was leaking extra_headers, headers, and aws_session_token in "
             "plaintext for every deployment row. This is a 3-line, low-risk security fix.",
             0, "reactions", "negative", "Health endpoint leaks AWS session tokens in plaintext.",
             "comment on BerriAI/litellm")]}]}},
  "spend": {"summary": "14 calls · 31,204 in / 8,806 out tokens · $0.0729",
            "usd": 0.0729, "calls": 14, "seconds": 47.3}}

if __name__ == "__main__":
    os.makedirs("out", exist_ok=True)
    with open(os.path.join(os.path.dirname(__file__), "sample-digest.json"), "w") as f:
        json.dump(DIGEST, f, indent=2)
    if "--discord" in sys.argv:
        def dump(e, view=None):
            print("┌" + "─" * 72)
            print("│ " + e.title)
            if e.description: print("│ " + e.description.replace("\n", "\n│ "))
            for fl in e.fields:
                print("│" + "─" * 72)
                print("│ " + fl.name)
                print("│ " + fl.value.replace("\n", "\n│ "))
            if e.footer and e.footer.text: print("│ " + e.footer.text)
            if view: print("│ [ " + " ] [ ".join(c.label for c in view.children) + " ]")
            print("└" + "─" * 72 + "\n")
        dump(B.about_embed(DIGEST))
        for src, sd in DIGEST["by_source"].items():
            dump(B.source_embed(src, sd, DIGEST["generated_at"]), B.SourceView(src, sd["groups"]))
        dump(B.quotes_embed("hn", DIGEST["by_source"]["hn"]["groups"][0]))
    else:
        print(render(DIGEST))
