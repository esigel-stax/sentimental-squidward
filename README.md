# 🦑 Sentimental Squidward

Reads what people said about **LiteLLM** across GitHub, Hacker News, Reddit, and
X/Twitter over the past week. Scores the sentiment, clusters each platform into
its top 3 sentiment groups, and serves them in Discord — click a sentiment to see
the highest-upvoted comments inside it.

Built on `litellm` end to end: the Router, structured outputs, cross-model
fallbacks, capability checks, and the cost map.

```bash
python3 run.py                                   # github + hn + reddit
python3 run.py --source github,hn                # keyless only
python3 run.py --days 14 --limit 300
python3 run_bot.py                               # start the Discord bot
```

## Pipeline

```
sources/*.py  →  score_mentions  →  group_source (per platform)  →  digest.json
  normalize       haiku, batched      opus, one call per source       │
  to Mention      parallel, cached    + one contrast call             ▼
                                                            bot_discord.py
                                                          embeds + buttons
```

Two-stage by design. Stage 1 sees every raw comment but runs on a cheap model in
batches of 8. Stage 2 runs on a strong model and only ever sees one compressed
line per mention, so a busy week doesn't blow up the synthesis call.

**The Discord bot never calls a model.** `run.py` writes `out/latest.json`; the
bot only reads it. Clicks stay inside Discord's 3-second ack budget and cost
nothing, no matter how many people are poking at it.

## Sources

| source | auth | what it's actually good for |
|---|---|---|
| `github` | none (token → 5000/hr) | defect reports and review-queue pressure from people already committed |
| `hn` | **none** | unsolicited comparison against OpenRouter / Portkey / Bedrock |
| `reddit` | OAuth, free | adoption and evaluation sentiment — people still deciding |
| `twitter` | **paid** | broadest reach, lowest signal density |

> **X access tiers:** the Free tier is write-only. `/2/tweets/search/recent`
> requires **Basic or above**, so a valid Free-tier bearer token still returns
> 403. The adapter names this explicitly instead of failing vaguely.

Default is `github,hn,reddit`. Reddit needs a free OAuth app (below); without it
the run logs the gap and continues on the other two.

**Reddit setup, ~2 minutes:** <https://www.reddit.com/prefs/apps> → "create
another app" → type **script** → redirect uri `http://localhost:8080`. The
client id is the string *under* the app name, not the name itself. Put both in
`.env` as `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`.

A source that can't authenticate doesn't sink the run: it's logged, recorded in
`unavailable`, reported in the digest, and the other platforms carry on.

### Engagement

Every `Mention` carries `engagement` plus an `engagement_label`, because the
numbers are not comparable across platforms — 40 Reddit upvotes and 40 GitHub
reactions mean very different things. Ranking only ever happens *within* a
platform.

| source | metric | label |
|---|---|---|
| github | reactions (+ reply count on issues) | `reactions` |
| reddit | post/comment score | `upvotes` |
| hn | parent story points | `story points` |
| twitter | likes + RTs + quotes | `likes+RTs` |

HN is the honest asterisk: it exposes no per-comment score through any public
API, so a comment inherits its story's points — how big a room the remark was
made in, not how well it landed. Labelled as such so the UI never lies.

## Discord

### 1. Create the app

<https://discord.com/developers/applications> → New Application → Bot → Reset
Token → copy it into `DISCORD_BOT_TOKEN`.

No privileged intents needed. Squidward only reads slash commands and button
clicks — it never reads message content.

### 2. Invite it

Replace `<APP_ID>` with your application ID:

```
https://discord.com/api/oauth2/authorize?client_id=<APP_ID>&scope=bot%20applications.commands&permissions=83968
```

`83968` = Send Messages + Embed Links + Read Message History. Nothing else.

### 3. Avatar

`assets/squidward-avatar.png` (1024×1024). Upload it under **Bot → Icon** in the
developer portal — Discord crops to a circle, and the art is scaled to fit the
inscribed circle so no tentacles get shaved off. `assets/squidward.svg` is the
source if you want to recolour it; `assets/squidward-128.png` is a legibility
proof at chat size.

It's an original weary-cephalopod drawing rather than the Nickelodeon character
art, so you're not shipping someone else's copyrighted design in your server.

### 4. Run

```bash
python3 run.py            # build a digest first — the bot serves it
python3 run_bot.py
```

### Commands

| command | who | what |
|---|---|---|
| `/about` | anyone | what the bot is, how it uses litellm, and the testing caveat |
| `/sentiment` | anyone | cross-source contrast, then one embed per platform with 3 sentiment buttons |
| `/sentiment source:hn` | anyone | just that platform |
| *(click a button)* | anyone | top 5 comments in that group by engagement, **plus a CSV of all of them** — platform, author, sentiment, intensity, engagement, url, full text |

`/refresh` rebuilds the digest and is gated on **Manage Server**, because it
spends money. It runs the pipeline in a worker thread so the bot stays responsive.

Buttons use persistent `custom_id`s (`sq|<source>|<index>`) re-registered on
startup, so they keep working after a redeploy instead of going dead the way
timeout-based views do.

### Keeping it fresh

```bash
0 9 * * MON /path/to/squidward/refresh.sh >> /tmp/squidward.log 2>&1
```

Or in Docker:

```bash
docker build -t squidward .
docker run -d --env-file .env -v squidward-data:/data squidward
```

## The litellm surface this exercises

- **`Router`** with logical names (`scorer`, `grouper`) — no vendor string appears
  outside `llm.py`. Swap Anthropic → Bedrock/Azure/vLLM by editing one dict.
- **`fallbacks=[{"scorer": ["scorer-backup"]}]`** — a 429 on Haiku reroutes to
  Sonnet mid-run.
- **`num_retries` / `allowed_fails` / `cooldown_time`** — a flapping deployment
  stops receiving traffic instead of failing 200 comments.
- **`response_format=<pydantic model>`** — schema-validated output.
- **`litellm.supports_response_schema()`** — capability is *checked*, degrading to
  prompt-coerced JSON rather than discovering a 400 in production.
- **`litellm.completion_cost()`** — every run reports what it actually spent.

### One rough edge worth knowing

litellm renders a nested `List[BaseModel]` in `response_format` into an Anthropic
tool schema, and the model sometimes fills the field with a JSON *string* rather
than an array. The content is correct, just double-encoded, and nothing in the
library normalizes it. `schemas._as_list` accepts both shapes. See
`ScoreBatch.scores`, `SourceDigest.groups`, `SentimentGroup.mention_indexes`.

## Layout

| file | role |
|---|---|
| `squidward/schemas.py` | `Mention` (the cross-platform seam) + the pydantic contracts |
| `squidward/sources/*.py` | one adapter per platform, all emitting `Mention` |
| `squidward/llm.py` | the Router, capability checks, spend tally |
| `squidward/analyze.py` | both LLM stages and every prompt |
| `squidward/digest.py` | assembles `out/latest.json` — the one artifact downstream reads |
| `squidward/bot_discord.py` | slash commands, embeds, persistent buttons |
| `squidward/cache.py` | persistent score cache; failures are never cached |

## Adding an output surface

`digest.py` emits a plain dict; every renderer reads it and nothing more. The
Discord layer is ~280 lines against that dict, so Slack, email, or a static HTML
page are each a small module — no pipeline changes. (An earlier Slack Block Kit
renderer was removed when the digest was restructured per-source; it was written
against the old single-grouping API and no longer applied.)

## Adding a platform

Write a module exposing `fetch(days, limit, **kw) -> List[Mention]`, register it
in `sources/__init__.py`. Scoring, grouping, engagement ranking, the digest, and
the whole Discord layer are platform-agnostic. Populate `engagement` and
`engagement_label` and the click-through ranks it correctly for free.

## Known limits

- GitHub covers issue comments and issue bodies; Discussions need GraphQL.
- Twitter recent search is a hard 7-day window regardless of `--days`.
- Grouping is one call per source. Past a few thousand mentions per platform
  you'd want a map-reduce over topic buckets.
- Roughly 60% of `BerriAI/litellm` comment volume is review mechanics
  (`@greptileai please re-review`, `bugbot run`, CI status). The cheap rule layer
  catches the short ones; the rest cost a token to reject.

## Sample output

`samples/make_sample.py` renders a digest through the real renderers so you can
see the format without spending anything:

```bash
python3 samples/make_sample.py --discord   # as Discord embeds
python3 samples/make_sample.py             # as console output
```

The mentions, authors, URLs, and engagement numbers in it are real (HN + GitHub,
2026-08-19). The group names and commentary are hand-authored placeholders —
it is a format demo, not a model output. Run `python3 run.py` for the real thing.
