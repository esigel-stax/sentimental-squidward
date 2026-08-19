"""Sentimental Squidward — the Discord half.

Design note: clicking a button never calls a model. `run.py` produces
`out/latest.json`; the bot only reads it. That keeps interactions inside
Discord's 3-second ack budget and means a channel full of curious people costs
nothing. Refreshing is an explicit, permissioned command.

Buttons use persistent custom_ids (`sq|<source>|<group index>`) and are
re-registered on startup, so they keep working after a redeploy instead of
going dead the way timeout-based views do.
"""

from . import env as _env  # noqa: F401  (loads .env on import)

import asyncio
import csv
import io
import os
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from . import digest as digest_mod

OUT_DIR = os.getenv("SQUIDWARD_OUT_DIR", "out")
SOURCE_EMOJI = {"github": "🐙", "reddit": "👽", "hn": "🟠", "twitter": "🐦"}
SENTIMENT_COLOR = {
    "positive": discord.Color.from_rgb(46, 160, 67),
    "negative": discord.Color.from_rgb(218, 54, 51),
    "mixed": discord.Color.from_rgb(210, 153, 34),
    "neutral": discord.Color.from_rgb(125, 133, 144),
}
SENTIMENT_DOT = {"positive": "🟢", "negative": "🔴", "mixed": "🟡", "neutral": "⚪"}
MAX_QUOTES = 5

BETA_NOTE = ("I am in testing. If something seems wrong, it probably is. "
             "Oh, my aching tentacles!")

NUMBER_WORD = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}

SOURCE_BLURB = {
    "github": "the LiteLLM issue tracker, where people who already committed "
              "file their grievances",
    "hn": "Hacker News, where people mention LiteLLM while arguing about "
          "something else entirely",
    "reddit": "Reddit, where people are still deciding whether to bother",
    "twitter": "X, where nobody has the room to finish a thought",
}


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


# --- rendering ------------------------------------------------------------

def source_embed(source: str, data: Dict[str, Any], generated_at: str) -> discord.Embed:
    e = discord.Embed(title=f"{SOURCE_EMOJI.get(source, '•')} {source} — "
                            f"{data.get('on_topic', 0)} comments",
                      color=discord.Color.from_rgb(88, 101, 242))
    if not data.get("groups"):
        e.description = "Nothing worth grouping this week."
        return e
    e.description = "\n".join(
        f"{SENTIMENT_DOT.get(g['dominant_sentiment'], '⚪')} **{_clip(g['name'], 70)}** — "
        f"{g['dominant_sentiment']}, {g['count']}"
        for g in data["groups"])
    e.set_footer(text="press a button for that group's comments · in testing")
    return e


def quotes_embed(source: str, group: Dict[str, Any]) -> discord.Embed:
    e = discord.Embed(
        title=f"{SOURCE_EMOJI.get(source, '•')} {_clip(group['name'], 200)}",
        description=f"Top {min(MAX_QUOTES, len(group['mentions']))} of "
                    f"{group['count']} by engagement. "
                    f"All {group['count']} are in the attached CSV — platform, "
                    f"sentiment, score and upvotes per comment.",
        color=SENTIMENT_COLOR.get(group["dominant_sentiment"], discord.Color.greyple()),
    )
    for m in group["mentions"][:MAX_QUOTES]:
        eng = (f"{m['engagement']} {m['engagement_label']}"
               if m["engagement"] else "no score available")
        dot = SENTIMENT_DOT.get(m["sentiment"], "⚪")
        value = (f"{dot} **{eng}** · {_clip(m.get('context', ''), 60)}\n"
                 f"> {_clip(m['text'], 380)}\n[open]({m['url']})")
        e.add_field(name=_clip(m["author"], 80), value=_clip(value, 1020),
                    inline=False)
    if not group["mentions"]:
        e.add_field(name="empty", value="No mentions landed in this group.",
                    inline=False)
    return e


def about_embed(data: Optional[Dict[str, Any]]) -> discord.Embed:
    e = discord.Embed(
        title="🦑 Sentimental Squidward",
        description=(
            "Mr. Krabs asked me analyze the LiteLLM sentiment on GitHub, "
            "HackerNews, and Twitter. Another day, another migraine!\n\n"
            "**Methodology:** I use LiteLLM to switch between two models: "
            "Haiku 4.5 scores every comment for relevance and sentiment "
            "(positive, negative, mixed, neutral), then Sonnet 5 sorts each "
            "platform's comments into its three main sentiment groups and "
            "summarizes the feedback in each. Source comments linked for every "
            "grouping.\n\n"
            "**Caveat:** Squidwardbot is in testing. If something seems wrong, "
            "it probably is. Oh, my aching tentacles"
        ),
        color=discord.Color.from_rgb(88, 101, 242),
    )
    if data:
        e.set_footer(text=f"{data.get('total_on_topic', 0)} comments of "
                          f"{data.get('total_scanned', 0)} scanned · "
                          f"{data.get('generated_at', '')[:10]}")
    return e


CSV_COLUMNS = ["platform", "author", "sentiment", "intensity", "engagement",
               "engagement_label", "created_at", "topic", "summary", "context",
               "url", "text"]


def group_csv(source: str, group: Dict[str, Any]) -> discord.File:
    """Every mention in the group as a spreadsheet, not just the top few.

    utf-8-sig so Excel on Windows opens the accented usernames correctly instead
    of mojibake — the single most common complaint about CSV exports.
    """
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore",
                       quoting=csv.QUOTE_ALL)
    w.writeheader()
    for m in group["mentions"]:
        row = dict(m)
        row["platform"] = source
        row["text"] = " ".join((m.get("text") or "").split())
        w.writerow(row)

    slug = "".join(c if c.isalnum() else "-" for c in group["name"]).strip("-")[:40]
    data = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    return discord.File(data, filename=f"{source}-{slug or 'group'}.csv")


# --- interactive view -----------------------------------------------------

class GroupButton(discord.ui.Button):
    def __init__(self, source: str, index: int, group: Dict[str, Any]):
        super().__init__(
            label=_clip(f"{index + 1}. {group['name']}", 78),
            emoji=SENTIMENT_DOT.get(group["dominant_sentiment"], "⚪"),
            style=discord.ButtonStyle.secondary,
            custom_id=f"sq|{source}|{index}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        _, source, idx = self.custom_id.split("|")
        data = digest_mod.load_latest(OUT_DIR)
        if not data:
            await interaction.response.send_message(
                "No digest on disk. Someone needs to run `/refresh`.",
                ephemeral=True)
            return
        groups = data.get("by_source", {}).get(source, {}).get("groups", [])
        if int(idx) >= len(groups):
            await interaction.response.send_message(
                "That group is gone — the digest was rebuilt since this message. "
                "Run `/sentiment` again.", ephemeral=True)
            return
        group = groups[int(idx)]
        await interaction.response.send_message(
            embed=quotes_embed(source, group),
            file=group_csv(source, group),
            ephemeral=True)


class SourceView(discord.ui.View):
    """Persistent: no timeout, stable custom_ids, survives a bot restart."""

    def __init__(self, source: str, groups: List[Dict[str, Any]]):
        super().__init__(timeout=None)
        for i, g in enumerate(groups[:3]):
            self.add_item(GroupButton(source, i, g))


# --- bot ------------------------------------------------------------------

class SquidwardBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!sq ", intents=discord.Intents.default())

    async def setup_hook(self) -> None:
        # Re-register views so buttons on old messages keep responding.
        data = digest_mod.load_latest(OUT_DIR)
        if data:
            for source, sd in data.get("by_source", {}).items():
                if sd.get("groups"):
                    self.add_view(SourceView(source, sd["groups"]))
        await self.tree.sync()

    async def on_ready(self) -> None:
        print(f"Sentimental Squidward online as {self.user}")


bot = SquidwardBot()


def _available_sources(data: Optional[Dict[str, Any]]) -> List[str]:
    if not data:
        return []
    return list(data.get("by_source", {}))


@bot.tree.command(name="sentiment",
                  description="Top 3 sentiments about LiteLLM, per source")
@app_commands.describe(source="Which platform (omit for all)")
async def sentiment(interaction: discord.Interaction,
                    source: Optional[str] = None) -> None:
    data = digest_mod.load_latest(OUT_DIR)
    if not data:
        await interaction.response.send_message(
            "No digest yet. Run `python3 run.py` or `/refresh`.", ephemeral=True)
        return

    sources = _available_sources(data)
    if source and source not in sources:
        await interaction.response.send_message(
            f"`{source}` isn't in the latest digest. Available: "
            f"{', '.join(sources) or 'none'}", ephemeral=True)
        return

    targets = [source] if source else sources
    await interaction.response.defer()

    contrast = data.get("contrast")
    if contrast and not source:
        lead = discord.Embed(
            title="🦑 Sentimental Squidward",
            description=f"*{_clip(contrast['headline'], 300)}*\n\n"
                        f"{_clip(contrast['contrast'], 1500)}",
            color=discord.Color.from_rgb(88, 101, 242))
        unavailable = data.get("unavailable") or {}
        if unavailable:
            lead.add_field(
                name="Not reachable this run",
                value="\n".join(f"`{k}` — {_clip(v, 120)}"
                                for k, v in unavailable.items())[:1020],
                inline=False)
        await interaction.followup.send(embed=lead)

    for s in targets:
        sd = data["by_source"][s]
        view = SourceView(s, sd["groups"]) if sd.get("groups") else None
        await interaction.followup.send(
            embed=source_embed(s, sd, data.get("generated_at", "")), view=view)


@sentiment.autocomplete("source")
async def _source_ac(interaction: discord.Interaction, current: str):
    data = digest_mod.load_latest(OUT_DIR)
    return [app_commands.Choice(name=s, value=s)
            for s in _available_sources(data) if current.lower() in s][:25]


@bot.tree.command(name="about",
                  description="What Sentimental Squidward is and how it works")
async def about(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        embed=about_embed(digest_mod.load_latest(OUT_DIR)))


@bot.tree.command(name="refresh",
                  description="Rebuild the digest (slow, costs money)")
@app_commands.describe(days="Lookback window", sources="Comma-separated platforms")
async def refresh(interaction: discord.Interaction,
                  days: int = 7,
                  sources: str = "github,hn") -> None:
    perms = getattr(interaction.user, "guild_permissions", None)
    if perms is not None and not perms.manage_guild:
        await interaction.response.send_message(
            "`/refresh` spends money, so it's limited to people who can manage "
            "the server.", ephemeral=True)
        return

    wanted = [s.strip() for s in sources.split(",") if s.strip()]
    await interaction.response.defer(thinking=True)
    try:
        # The pipeline is synchronous and slow; keep the event loop free.
        data = await asyncio.to_thread(
            digest_mod.build, wanted, days, 200, True, OUT_DIR)
        digest_mod.save(data, OUT_DIR)
    except Exception as e:
        await interaction.followup.send(
            f"Refresh failed: `{_clip(str(e), 400)}`", ephemeral=True)
        return

    await interaction.followup.send(
        f"Digest rebuilt: {data['total_on_topic']} on-topic of "
        f"{data['total_scanned']} scanned across "
        f"{', '.join(data['by_source'])} · {data['spend']['summary']}. "
        f"Run `/sentiment` to read it.")


def main() -> None:
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "DISCORD_BOT_TOKEN is not set. Create an application at "
            "https://discord.com/developers/applications, add a Bot, copy its "
            "token, and export it.")
    bot.run(token)
