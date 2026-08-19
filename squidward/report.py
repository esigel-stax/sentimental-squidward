"""Renders a digest into a standalone HTML document — every group, every comment.

The Discord embeds show three comments per group because embeds have a 1024
character field limit. This is the full record behind them: one page, no
pagination, no API calls, linkable from anywhere.
"""

import html
import json
import os
from typing import Any, Dict

SENTIMENT = {"positive": "positive", "negative": "negative",
             "mixed": "mixed", "neutral": "neutral"}

CSS = """
:root{
  --paper:#f7f8f7; --raised:#ffffff; --ink:#10171d; --body:#2c383f;
  --muted:#5c6a72; --rule:#dde3e2; --accent:#2f7d72; --accent-soft:#e6f0ee;
  --pos:#2e7d4f; --neg:#b23c33; --mix:#a2701a; --neu:#6b757c;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#0d1317; --raised:#141c21; --ink:#eef3f2; --body:#c3cfd2;
    --muted:#8b9a9e; --rule:#243036; --accent:#6fc0b3; --accent-soft:#16282a;
    --pos:#5cc98a; --neg:#e8776c; --mix:#d9a441; --neu:#8b9a9e;
  }
}
:root[data-theme="dark"]{
  --paper:#0d1317; --raised:#141c21; --ink:#eef3f2; --body:#c3cfd2;
  --muted:#8b9a9e; --rule:#243036; --accent:#6fc0b3; --accent-soft:#16282a;
  --pos:#5cc98a; --neg:#e8776c; --mix:#d9a441; --neu:#8b9a9e;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--body);
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:16px; line-height:1.6; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:56rem; margin:0 auto; padding:4rem 1.5rem 6rem;
      display:flex; flex-direction:column; gap:3rem}
h1,h2,h3{font-family:Newsreader,Georgia,serif; color:var(--ink);
         text-wrap:balance; margin:0; font-weight:600; letter-spacing:-.01em}
h1{font-size:2.6rem; line-height:1.12}
h2{font-size:1.75rem}
h3{font-size:1.2rem; font-family:"IBM Plex Sans",sans-serif; font-weight:600}
.eyebrow{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:.72rem;
  text-transform:uppercase; letter-spacing:.14em; color:var(--muted)}
.lede{font-size:1.12rem; color:var(--body); max-width:62ch}
.meta{display:flex; flex-wrap:wrap; gap:1.25rem; font-family:"IBM Plex Mono",monospace;
      font-size:.78rem; color:var(--muted); font-variant-numeric:tabular-nums}
.rule{height:1px; background:var(--rule); border:0; margin:0}
.platform{display:flex; flex-direction:column; gap:1.5rem}
.phead{display:flex; align-items:baseline; gap:.9rem; flex-wrap:wrap;
       padding-bottom:.6rem; border-bottom:2px solid var(--accent)}
.pcount{font-family:"IBM Plex Mono",monospace; font-size:.8rem; color:var(--muted);
        font-variant-numeric:tabular-nums}
.group{background:var(--raised); border:1px solid var(--rule);
       border-left:3px solid var(--gc,var(--neu)); border-radius:3px;
       padding:1.4rem 1.5rem; display:flex; flex-direction:column; gap:1rem}
.ghead{display:flex; align-items:baseline; gap:.75rem; flex-wrap:wrap}
.pill{font-family:"IBM Plex Mono",monospace; font-size:.68rem; text-transform:uppercase;
      letter-spacing:.1em; color:var(--gc,var(--neu)); border:1px solid currentColor;
      border-radius:2px; padding:.12rem .45rem; white-space:nowrap}
.share{margin-left:auto; font-family:"IBM Plex Mono",monospace; font-size:.8rem;
       color:var(--muted); font-variant-numeric:tabular-nums}
.says{max-width:66ch; margin:0}
.why{max-width:66ch; margin:0; padding-left:.9rem; border-left:2px solid var(--rule);
     color:var(--muted); font-size:.94rem}
.why b{color:var(--ink); font-weight:600}
.comments{list-style:none; margin:0; padding:0; display:flex;
          flex-direction:column; border-top:1px solid var(--rule)}
.c{display:grid; grid-template-columns:7.5rem 1fr; gap:1rem;
   padding:.9rem 0; border-bottom:1px solid var(--rule)}
.c:last-child{border-bottom:0; padding-bottom:0}
.cmeta{font-family:"IBM Plex Mono",monospace; font-size:.74rem; color:var(--muted);
       font-variant-numeric:tabular-nums; display:flex; flex-direction:column; gap:.15rem}
.score{color:var(--ink); font-weight:600}
.cbody{display:flex; flex-direction:column; gap:.35rem; min-width:0}
.who a{color:var(--accent); text-decoration:none; font-weight:600; font-size:.9rem}
.who a:hover,.who a:focus-visible{text-decoration:underline}
.ctx{color:var(--muted); font-size:.78rem}
.txt{margin:0; font-size:.92rem; color:var(--body); overflow-wrap:anywhere}
a:focus-visible,summary:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.note{font-size:.84rem; color:var(--muted); max-width:62ch}
@media (max-width:640px){
  h1{font-size:2rem} .wrap{padding:2.5rem 1.1rem 4rem}
  .c{grid-template-columns:1fr; gap:.35rem}
}
"""


def _e(t: Any) -> str:
    return html.escape(str(t if t is not None else ""))


def render(d: Dict[str, Any]) -> str:
    gen = d.get("generated_at", "")[:16].replace("T", " ")
    contrast = d.get("contrast") or {}
    parts = ['<meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             "<title>LiteLLM Community Sentiment</title>",
             '<link rel="preconnect" href="https://fonts.googleapis.com">',
             '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
             '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
             'family=Newsreader:opsz,wght@6..72,500;6..72,600&'
             'family=IBM+Plex+Sans:wght@400;500;600&'
             'family=IBM+Plex+Mono:wght@400;500;600&display=swap">',
             f"<style>{CSS}</style>", '<div class="wrap">']

    parts.append(
        f'<header style="display:flex;flex-direction:column;gap:1rem">'
        f'<div class="eyebrow">Week ending {_e(gen[:10])} · {d.get("days", 7)}-day window</div>'
        f"<h1>What the internet said about LiteLLM</h1>"
        + (f'<p class="lede">{_e(contrast.get("headline", ""))}</p>' if contrast else "")
        + f'<div class="meta">'
          f"<span>{d.get('total_on_topic', 0)} on-topic of {d.get('total_scanned', 0)} scanned</span>"
          f"<span>{len(d.get('by_source', {}))} platforms</span>"
          f"<span>{_e(d.get('spend', {}).get('summary', ''))}</span></div>"
        f"</header>")

    if contrast.get("contrast"):
        parts.append(f'<section><div class="eyebrow">Across platforms</div>'
                     f'<p class="says" style="margin-top:.6rem">{_e(contrast["contrast"])}</p></section>')

    for source, sd in d.get("by_source", {}).items():
        parts.append('<section class="platform">')
        parts.append(f'<div class="phead"><h2>{_e(source)}</h2>'
                     f'<span class="pcount">{sd.get("on_topic", 0)} on-topic '
                     f'of {sd.get("scanned", 0)} scanned</span></div>')
        if not sd.get("groups"):
            parts.append('<p class="note">Too few on-topic mentions to group.</p></section>')
            continue
        for g in sd["groups"]:
            var = {"positive": "--pos", "negative": "--neg",
                   "mixed": "--mix"}.get(g["dominant_sentiment"], "--neu")
            parts.append(f'<article class="group" style="--gc:var({var})">')
            parts.append(f'<div class="ghead"><h3>{_e(g["name"])}</h3>'
                         f'<span class="pill">{_e(g["dominant_sentiment"])}</span>'
                         f'<span class="share">{g["count"]} mentions · '
                         f'{g["share"]:.0f}%</span></div>')
            parts.append(f'<p class="says">{_e(g["what_people_say"])}</p>')
            parts.append(f'<p class="why"><b>Why it matters:</b> {_e(g["why_it_matters"])}</p>')
            parts.append('<ul class="comments">')
            for m in g["mentions"]:
                score = (f'<span class="score">{m["engagement"]}</span> '
                         f'{_e(m["engagement_label"])}' if m.get("engagement")
                         else '<span class="score">—</span> no score')
                parts.append(
                    f'<li class="c"><div class="cmeta">{score}'
                    f'<span>{_e(m.get("sentiment", ""))} · {m.get("intensity", 0):.1f}</span>'
                    f'<span>{_e((m.get("created_at") or "")[:10])}</span></div>'
                    f'<div class="cbody">'
                    f'<div class="who"><a href="{_e(m["url"])}" target="_blank" '
                    f'rel="noopener">{_e(m["author"])}</a></div>'
                    f'<div class="ctx">{_e(m.get("context", ""))}</div>'
                    f'<p class="txt">{_e(m.get("text", ""))}</p></div></li>')
            parts.append("</ul></article>")
        parts.append("</section>")

    if d.get("unavailable"):
        rows = "".join(f"<li><b>{_e(k)}</b> — {_e(v)}</li>"
                       for k, v in d["unavailable"].items())
        parts.append(f'<section><div class="eyebrow">Not reachable this run</div>'
                     f'<ul class="note">{rows}</ul></section>')

    parts.append('<hr class="rule"><p class="note">Sentiment scored per comment and '
                 'grouped per platform using LiteLLM. Engagement is ranked within a '
                 'platform only — upvotes, reactions and likes are not comparable '
                 'across sites. Generated by Sentimental Squidward, which is in testing.</p>')
    parts.append("</div>")
    return "\n".join(parts)


def save(d: Dict[str, Any], out_dir: str = "out") -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "report.html")
    with open(path, "w") as f:
        f.write(render(d))
    return path
