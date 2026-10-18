# Rack Digger — for Ableton Live

Dig through songs you've already made and turn the device chains you like into ready-to-use racks in your Live browser.

You've probably built great vocal chains, bass sounds and FX setups in old projects, then rebuilt them from scratch in the next one. Rack Digger reads your `.als` projects, shows you every track's chain, and saves the ones you pick as racks, with plugin settings and macros, into `User Library/Rack Digger/`. Audio tracks become Audio Effect Racks; instrument tracks become Instrument Racks with the synth, its patch and its effects together.

> **Status: early (v0.1).** Windows and Live 12 only so far. It only ever *reads* your projects; it writes new racks to your User Library and never overwrites a file unless you ask.

## Quick start (with Claude Code)

1. **`/dig` + a song:** its name (`/dig midnight drive`), the `.mp3` you bounced, or the project folder.
2. **Tick the tracks you want.** Claude suggests the best ones and shows a short page of them.
3. **Press Go,** then find the racks in Live under **User Library › Rack Digger**.

Every choice along the way is a button; you can still type anything instead.

To get `/dig`, install the tool (below), then copy the `skills/dig` folder from this repo into `%USERPROFILE%\.claude\skills\`.

## Install

You need [Python 3.9 or newer](https://www.python.org/downloads/). During Python setup, tick **"Add python.exe to PATH"**.

```bash
pip install git+https://github.com/songexile/rack-digger.git
```

Check it can find your User Library:

```bash
rackdigger where
```

## Using the commands directly

**0. Find a song by name.** It searches the folders you've added under Places in Live's browser (or set your own with `rackdigger songs "C:\Music\Songs"`):

```bash
rackdigger find "midnight drive"
```

**1. See what's in a song.** Point it at the project folder, a `.als`, or the `.mp3` you bounced (it uses the matching set):

```bash
rackdigger show "C:\Music\My Song Project"
```

Each track is broken down in plain words: what it is (bass, vocal, FX hit…), the synth and patch or the sample it plays, how much of the song it's in, and what every effect is doing. Tracks are sorted into **worth grabbing**, **maybe** and **skipped**, and identical chains are listed once. For Serum the patch name is read from the plugin. Serum 2 doesn't save patch names in projects, so you get what the patch is made of instead (oscillators, wavetables, filter, FX, mono/poly); this needs Python 3.14+. Other plugins show their name only. macOS `._` files in projects copied from a Mac are ignored.

Add `--html song.html` for a simple page: the tracks worth grabbing as cards (how each sounds, how much of the song it plays, its key effects) and everything else as one line. Add `--picks picks.json` to choose the cards and give them plain-English names (see the skill for the format). It's one file with no internet needed.

To look for chains you reuse across many songs, scan a whole folder:

```bash
rackdigger scan "C:\Music\Songs"
```

**2. Describe the rack you want** in a small JSON spec. See [examples/lofi-radio.json](examples/lofi-radio.json):

- `als` and `track`: the song and the track name as shown in Live.
- `rack_name` and `category`: the rack is saved to `User Library/Rack Digger/<category>/<rack_name>.adg`.
- `macros`: optional. Each macro maps to parameters on devices in the chain (`device` is the position in the chain, starting at 0). Set `min` to the parameter's current value so the rack sounds exactly like your song with the macro at 0.

**3. Build it:**

```bash
rackdigger build my-spec.json
```

**4. Check it** (optional), then find it in Live's browser under User Library › Rack Digger:

```bash
rackdigger check "C:\...\User Library\Rack Digger\FX\Lo-Fi Radio (my song).adg"
```

## What it keeps

- Built-in Live devices with all their settings, including devices that are switched off.
- On instrument tracks: MIDI effects, the instrument and every effect after it, as one Instrument Rack.
- VST2 and VST3 plugins with their full saved state. The plugin must be installed to load.
- Racks inside the chain (Audio Effect and Instrument Racks), with their chains, chain volumes, key/velocity zones and their own macros.

## Not yet

- Drum Racks and MIDI Effect Racks.
- The list of plugin knobs Live shows in a plugin's device panel resets to Live's default (the sound isn't affected).
- Macros that control plugin parameters.
- Mac, and Live 11.
- Sidechain sources and project samples aren't handled yet; check those racks in Live.

## Settings

If `rackdigger where` can't find your User Library, set the folder yourself:

```bash
setx RACKDIGGER_USER_LIBRARY "D:\Ableton\User Library"
```

## How it works

`.als` and `.adg` files are gzipped XML. Rack Digger copies the devices out of your project and wraps them in the same layout Live uses when you save a rack. Design decisions are in [docs/DECISIONS.md](docs/DECISIONS.md).

Ableton and Ableton Live are trademarks of Ableton AG. This project isn't affiliated with Ableton.
