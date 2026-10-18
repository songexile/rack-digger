# Rack Digger: design decisions

Rack Digger grabs device chains from a producer's existing Ableton Live songs and turns them into ready-to-use racks. These are the decisions behind it, and what's still open.

## What it is

1. **Built for Ableton Live.** Reads `.als` projects, writes `.adg` racks. It never changes a project.
2. **A plain Python engine** (find, show, build, check) with no dependencies, usable without AI.
3. **A Claude Code skill (`/dig`) as the main front end.** Claude handles the judgement calls: which tracks are worth keeping, names, folders and macros. A desktop app may come later; Max for Live is out of scope.
4. **Song first.** The producer names a song they know and picks tracks by ear. The tool's own "worth grabbing" rating is a hint, not a decision: it can't hear.
5. **For harvest sessions**, not mid-production. Live's browser already covers finding a rack while making music, once the racks exist.

## How it works

6. **Find a song by name.** `rackdigger find` searches the folders added under Places in Live's browser, or folders the user sets. A bounced `.mp3` resolves to the `.als` with the same name; a project folder to its newest saved set. macOS `._` files and Live's Backup folders are ignored.
7. **Tracks are referred to by number**, as `show` lists them. Songs often have several tracks with the same name, so a shared name is refused rather than guessed.
8. **Every choice is a click.** In `/dig`, picking a song, ticking tracks, choosing effects-only and approving the build are buttons or checkboxes, with the recommendation first. Typing still works.
9. **One review table instead of per-rack questions.** Claude proposes a name, type, folder and macros for every picked track at once; the producer says go or edits.
10. **A simple song page.** The picks as a few cards (plain-English name, how it sounds, how much of the song it plays, key effects) and everything else on one line. A detailed page with every track and setting was tried and found overwhelming.

## What gets built

11. **Audio tracks become Audio Effect Racks; instrument tracks become Instrument Racks** with MIDI effects, the instrument and every effect after it.
12. **Effects only** is an option for instrument tracks: when the source is a whole sampled song, the reusable part is the chain after the sampler.
13. **Plugins keep their full saved state.** Racks inside the chain keep their chains, chain volumes, key/velocity zones and their own macros.
14. **Macros start at the song's sound.** Each macro's starting point reproduces the original setting; only linear controls like mix and feedback start mid-knob so they can go both ways.
15. **Library layout:** one `User Library/Rack Digger/` folder with `Vox`, `Bass`, `Synth`, `Drums`, `FX`, `Bus`, `Master`, and the song name in each rack's name. Specs (to rebuild a rack) go in `_specs/`, song pages in `_pages/`. Racks the producer made by hand are never touched.
16. **Never overwrite.** Building refuses to replace an existing rack unless asked.

## Not built yet

- **Drum Racks and MIDI Effect Racks.**
- **Macros on plugin parameters.**
- **Copying samples that live inside a project folder** into the library, so a rack survives the project being tidied up. Samples elsewhere already keep working where they are.
- **Flagging** removed sidechain sources and missing plugins in the review table.
- **Patch names for plugins other than Serum.** Serum 2 doesn't save its patch name in projects, so its patch is described instead (needs Python 3.14+ for zstd).
- **Mac and Live 11.**
- **MIDI digging:** grabbing basslines, chords and drum patterns from songs with the same flow.

## Open risks

- **Live updates can change the file format.** Ableton doesn't document `.als`/`.adg`; keep small test sets per Live version.
- **Macro ranges on curved parameters** (frequency, gain) are only exact at their endpoints.
- **The plugin knob list** Live shows in a plugin's device panel resets to Live's default in rebuilt racks (the sound isn't affected).
