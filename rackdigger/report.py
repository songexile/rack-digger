"""Render a song as a short, simple page: a few picked tracks as cards, everything else in one line each.

Picks normally come from a picks file (written by whoever chose them, e.g. Claude):
{
  "picks": [{"track": 11, "title": "Dreamy sample wash", "sound": "Crushed, shimmering, huge reverb"}],
  "also":  [{"track": 4, "note": "Same as 2, plainer delay"}]
}
Without one, the tracks Rack Digger rates "worth grabbing" become the cards.
"""
import math
from html import escape

# Devices that tidy a sound rather than define it; left out of a card's short effect list.
PLUMBING = {"EQ Eight", "EQ Three", "Channel EQ", "Utility", "Spectrum", "Tuner", "Compressor",
            "Glue Compressor", "Limiter", "Simpler", "Sampler", "Arpeggiator"}
MAX_EFFECTS = 5

CSS = """
:root {
  --bg: #eef0ec; --card: #fbfcfa; --ink: #1d2629; --soft: #66726f; --line: #d5dad3; --track: #e1e5df;
  --accent: #b86e0e;
  --display: "Bahnschrift SemiCondensed", "Bahnschrift", "Arial Narrow", sans-serif;
  --body: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14191b; --card: #1c2326; --ink: #e4e9e5; --soft: #98a4a1; --line: #2d373a; --track: #2a3336;
    --accent: #eba545;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 var(--body); }
main { max-width: 640px; margin: 0 auto; padding: 40px 16px 64px; }
h1 { font: 700 clamp(30px, 7vw, 46px)/1 var(--display); margin: 0 0 6px; overflow-wrap: anywhere; }
.meta { margin: 0 0 32px; color: var(--soft); font-size: 14px; }
h2 { font: 700 15px/1 var(--display); letter-spacing: .08em; text-transform: uppercase; color: var(--soft); margin: 0 0 12px; }
.card { display: grid; grid-template-columns: 3.4rem 1fr; gap: 2px 14px; background: var(--card);
  border: 1px solid var(--line); border-radius: 12px; padding: 18px 20px; margin-bottom: 14px; }
.num { grid-row: span 4; font: 700 40px/1 var(--display); color: var(--accent); }
.card h3 { font: 600 22px/1.2 var(--display); margin: 0; }
.sound { margin: 2px 0 10px; }
.plays { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--soft); }
.bar { flex: 0 0 120px; height: 8px; border-radius: 4px; background: var(--track); overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--accent); border-radius: 4px; }
.fx { margin: 10px 0 0; font-size: 13px; color: var(--soft); }
.also { list-style: none; padding: 0; margin: 32px 0 0; }
.also li { display: flex; gap: 14px; padding: 8px 0; border-top: 1px solid var(--line); }
.also b { font: 600 16px/1.5 var(--display); color: var(--soft); min-width: 2rem; text-align: right; }
@media (max-width: 480px) { .card { grid-template-columns: 2.6rem 1fr; padding: 16px; } .num { font-size: 32px; } }
"""


def _played(t, bars):
    played = sum(e - s for s, e in t["segments"])
    return min(played, bars)


def _key_effects(t):
    out = []
    for d in t["chain"]:
        if not d["on"] or d["name"] in PLUMBING:
            continue
        if d["type"] == "source":  # the card's title and sound line already say what the instrument is
            continue
        if d["name"] not in out:
            out.append(d["name"])
    return out[:MAX_EFFECTS]


def _default_sound(t):
    sources = [d for d in t["chain"] if d["type"] == "source"]
    if sources and sources[0]["detail"]:
        return f'{t["role"].capitalize()} · {sources[0]["detail"]}'
    return t["role"].capitalize()


NO_CLIPS = {"ReturnTrack": "send effect (return track)", "GroupTrack": "group bus",
            "MainTrack": "main output", "MasterTrack": "main output"}


def _card(n, t, bars, title, sound):
    effects = _key_effects(t)
    fx = f'<p class="fx">{escape(" · ".join(effects))}</p>' if effects else ""
    if t["kind"] in NO_CLIPS:  # these tracks process other tracks rather than play clips
        plays = f'<div class="plays">{NO_CLIPS[t["kind"]]}</div>'
    else:
        played = _played(t, bars)
        pct = played / bars * 100 if bars else 0
        plays = (f'<div class="plays"><div class="bar" aria-hidden="true"><span style="width:{pct:.0f}%"></span></div>'
                 f'plays {played:.0f} of {bars} bars</div>')
    return (f'<article class="card"><div class="num">{n}</div>'
            f'<h3>{escape(title)}</h3><p class="sound">{escape(sound)}</p>{plays}{fx}</article>')


def render(song, als, why, picks=None):
    bars = max(1, math.ceil(song["bars"] or 1))
    tracks = dict(enumerate(song["tracks"], 1))
    title = als.parent.name.removesuffix(" Project")

    if picks:
        cards = [(p["track"], p.get("title") or tracks[p["track"]]["track"], p.get("sound") or _default_sound(tracks[p["track"]]))
                 for p in picks.get("picks", []) if p["track"] in tracks]
        also = [(a["track"], a.get("note", "")) for a in picks.get("also", []) if a["track"] in tracks]
        heading = "My picks"
    else:
        cards = [(n, t["track"], _default_sound(t)) for n, t in tracks.items()
                 if t["verdict"][0] == "grab" and not t.get("same_as")]
        also = [(n, f'{t["track"]}: {t["role"]}') for n, t in tracks.items()
                if t["verdict"][0] == "maybe" or (t["verdict"][0] == "grab" and t.get("same_as"))]
        heading = "Worth grabbing"

    out = [f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f'<title>{escape(title)} · Rack Digger</title><style>{CSS}</style></head><body><main>'
           f'<h1>{escape(title)}</h1><p class="meta">{bars} bars · {escape(als.name)}</p>'
           f'<h2>{heading}</h2>']
    out += [_card(n, tracks[n], bars, t, s) for n, t, s in cards]
    if also:
        out.append('<h2 style="margin-top:32px">Also in the song</h2><ul class="also">')
        out += [f'<li><b>{n}</b><span>{escape(note)}</span></li>' for n, note in also]
        out.append("</ul>")
    out.append("</main></body></html>")
    return "".join(out)
