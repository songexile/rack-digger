---
name: dig
description: Rack Digger. Grab device chains and synth patches from the user's own Ableton Live songs and save them as ready-to-use racks in their User Library, using the rackdigger command. Use for /dig, or when the user wants to dig, grab, harvest, pull or save racks, presets, chains or sounds from one of their songs or Live projects, or asks what's worth keeping from a song.
argument-hint: "<song name, .mp3, .als or project folder>"
---

# /dig: Rack Digger

Turn chains the user already made into racks in `User Library/Rack Digger/<Category>/`. The user picks by ear from songs they know; you do the breakdown, naming, macros and building. Never edit their projects.

**Make every decision a click.** Whenever the user has to choose, use the AskUserQuestion tool (buttons and checkboxes) with your recommendation first and marked "(Recommended)". Typing stays possible through its "Other" option, but the user should never *have* to type. Only fall back to asking in plain text if that tool isn't available.

## If /dig has no song

Show this, then ask which song (one short line, no tool needed):

> **Rack Digger in 3 steps**
> 1. `/dig` + a song: its name (`/dig midnight drive`), the `.mp3` you bounced, or the project folder.
> 2. Tick the tracks you want.
> 3. Press **Go**, then find the racks in Live under User Library › Rack Digger.

## 0. Make sure the tool works

Run `rackdigger --version`. If it isn't found, try `python -m rackdigger --version`. If neither works, install it:

```
python -m pip install git+https://github.com/songexile/rack-digger.git
```

(or `python -m pip install -e <path to a local clone>`). Then `rackdigger where` must print a User Library. If it doesn't, ask the user where theirs is and set `RACKDIGGER_USER_LIBRARY`.

## 1. Find the song

- A path (`.mp3`, `.als` or project folder) is used as is: a bounced `.mp3` resolves to the `.als` with the same name, a folder to its newest saved set.
- A name: run `rackdigger find "<name>"`. It searches the user's song folders (their Places folders in Live's browser, unless they set others with `rackdigger songs "<folder>"`).
  - One match: use it.
  - Several: ask which, one option per project (up to 4; newest first).
  - None: say where it looked and ask for the folder or a path; offer to save the folder with `rackdigger songs`.

## 2. Break it down and suggest

```
rackdigger show "<song>"
```

Decide **your suggestion**: the 2–4 tracks you'd grab and why (what makes the sound distinctive, not just how many devices it has), and which you'd skip (simple Init patches, near-duplicates, tracks that barely play). For a track whose source is a whole sampled song, the reusable part is usually the effect chain after the sampler.

Write the picks to `<User Library>/Rack Digger/_pages/<song>.picks.json`, with a plain-English title and a short line on how each one *sounds*:

```json
{"picks": [{"track": 11, "title": "Dreamy sample wash", "sound": "Crushed, shimmering, huge reverb"}],
 "also":  [{"track": 4, "note": "Same sample as 2, plainer delay"}]}
```

Make the page and give its full path (open it if you can):

```
rackdigger show "<song>" --html "<User Library>/Rack Digger/_pages/<song>.html" --picks "<the picks file>"
```

Keep the page and your chat reply short: which `.als` was used, then one line per pick. Then **ask which tracks to grab** with a multi-select question: one option per pick (label `11 · Dreamy sample wash`, description = the sound line), recommended ones first. Up to 4 options; other track numbers can be typed under "Other".

For each chosen track whose source is a sampled song (Simpler/Sampler playing a long sample), also ask: **Effects only (Recommended)**, which drops the sampler so the chain works on any sound, or **Keep the sample**. Several such tracks can share one question per track in the same AskUserQuestion call (up to 4).

## 3. Plan each rack (one review table)

For each chosen track run `rackdigger params "<song>" <track number>` for device numbers and current values. Always use the track **number** from `show`, never the name: songs often have several tracks with the same name. Then show ONE table:

| # | Track | Rack name | Type | Folder | Macros |
|---|---|---|---|---|---|

- **Rack name:** what it is, plus the song in brackets, e.g. `Dreamy Sample Wash (midnight drive)`.
- **Type:** Audio Effect Rack (audio tracks, or `effects_only`), or Instrument Rack (instrument tracks).
- **Folder:** one of `Vox`, `Bass`, `Synth`, `Drums`, `FX`, `Bus`, `Master`.
- **Macros:** 3–7 for the knobs a producer actually reaches for (mix, feedback, crush, decay, filter, drive):
  - Each macro **starts at the song's sound**: `min` = current value, `start` 0. Only start mid-knob (`start` 64, range around the current value) on linear 0–1 controls like mix and feedback.
  - On/off switches (`On`, `Freeze`, `FreezeOn`) use `min`/`max` as macro thresholds, e.g. `1`/`127` or `64`/`127`.
  - Only built-in Live devices; plugin knobs can't be mapped yet. Say so when a rack gets few or no macros because of that.
  - Device numbers are the track's own, as `params` shows them, also with `effects_only`.
- Below the table, flag what won't carry over: plugins the rack needs, devices that are off, a sidechain input.

Then ask with buttons: **Go (Recommended)** or **Change something** (the user types the change under it). Wait for the answer.

## 4. Build, check, report

Write one spec per rack into `<User Library>/Rack Digger/_specs/<song>/` (fields: `als`, `track` (the number from `show`), `rack_name`, `category`, optional `effects_only` and `macros`; see `examples/` in the repo). Then:

```
rackdigger build <spec files>
rackdigger check "<built .adg>"
```

`build` never overwrites; if a name is taken, ask for a new one rather than passing `--overwrite`. Finish with a short list of what landed where (full paths) and where to find it in Live: User Library › Rack Digger.

## Current limits (say so when they apply)

- **Drum Racks** and MIDI Effect Racks can't be built yet; `build` refuses tracks containing them.
- Patch names are only read for Serum. Serum 2 doesn't save one; `show` describes the patch instead (needs Python 3.14+).
- Racks with plugins only load if those plugins are installed.
- Windows and Live 12 only so far.
