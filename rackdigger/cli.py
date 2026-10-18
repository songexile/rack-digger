"""rackdigger command line: where, show, scan, build, check."""
import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .build import BuildError, build, find_track, load_gz
from .check import check
from .describe import describe_device, describe_song, device_on, resolve_song
from .report import render
from .scan import RACK_TAGS
from .songs import find_projects, save_song_folders, song_folders
from .library import find_user_library, output_root
from .scan import print_report, scan_folder, write_json


def cmd_where(args):
    lib, how = find_user_library()
    if lib is None:
        print("User Library: not found. Set RACKDIGGER_USER_LIBRARY to its folder.")
        return 1
    print(f"User Library: {lib}  ({how})")
    print(f"Racks go to:  {output_root(lib)}")
    return 0


def cmd_scan(args):
    results = scan_folder(args.path, on_error=lambda als, e: print(f"!! couldn't read {als}: {e}", file=sys.stderr))
    if not results:
        print(f"no Live sets found in {args.path}")
        return 1
    if args.json:
        write_json(results, args.json)
    print_report(results, sys.stdout)
    return 0


def cmd_show(args):
    try:
        als, why = resolve_song(args.song)
    except FileNotFoundError as e:
        print(f"!! {e}", file=sys.stderr)
        return 1
    song = describe_song(als)
    if args.json:
        Path(args.json).write_text(json.dumps({"als": str(als), **song}, indent=1), encoding="utf-8")
    if args.html:
        picks = None
        if args.picks:
            try:
                picks = json.loads(Path(args.picks).read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as e:
                print(f"!! can't read picks file {args.picks}: {e}", file=sys.stderr)
                return 1
        Path(args.html).write_text(render(song, als, why, picks), encoding="utf-8")
        print(f"page written to {Path(args.html).resolve()}\n")

    print(f"{als.parent.name.removesuffix(' Project')}  ·  {als.name} ({why})")
    print(f"{song['bars']:.0f} bars  ·  {song['creator']}\n")
    numbered = list(enumerate(song["tracks"], 1))
    for verdict, title in (("grab", "★ WORTH GRABBING"), ("maybe", "? MAYBE")):
        rows = [(n, t) for n, t in numbered if t["verdict"][0] == verdict]
        if not rows:
            continue
        print(title)
        for n, t in rows:
            if t.get("same_as"):
                print(f"  {n:>2}  {t['track']}  —  same chain as {t['same_as']}" +
                      (f"  ·  {'  ·  '.join(t['usage'])}" if t["usage"] else "") + "\n")
                continue
            print(f"  {n:>2}  {t['track']}  —  {t['role']}" + (f"  ·  {'  ·  '.join(t['usage'])}" if t["usage"] else ""))
            print(f"      {'  →  '.join(t['steps'])}")
            if t["clip_names"]:
                print(f"      clips: {', '.join(t['clip_names'])}")
            print(f"      why: {t['verdict'][1]}\n")
    skipped = [(n, t) for n, t in numbered if t["verdict"][0] == "skip"]
    if skipped:
        print(f"SKIPPED ({len(skipped)})")
        for n, t in skipped:
            print(f"  {n:>2}  {t['track']}  —  {t['verdict'][1]}")
    return 0


def cmd_find(args):
    folders, how = song_folders()
    if not folders:
        print("No song folders known. Set one with:  rackdigger songs \"C:\\path\\to\\your\\Songs\"")
        return 1
    hits = find_projects(args.name, folders)
    if not hits:
        print(f"No project matching {args.name!r} in {how}:")
        for f in folders:
            print(f"  {f}")
        return 1
    for project, als, versions in hits[:args.limit]:
        mp3 = "  (has a bounce)" if any(project.glob("*.mp3")) or any(project.glob("*.wav")) else ""
        print(f"{project.name.removesuffix(' Project')}{mp3}\n  {project}\n  newest: {als.name}"
              + (f"  ({versions} versions)" if versions > 1 else "") + "\n")
    if len(hits) > args.limit:
        print(f"…and {len(hits) - args.limit} more; be more specific.")
    return 0


def cmd_songs(args):
    if args.folders:
        missing = [f for f in args.folders if not Path(f).is_dir()]
        if missing:
            print(f"!! not a folder: {', '.join(missing)}", file=sys.stderr)
            return 1
        save_song_folders(args.folders)
    folders, how = song_folders()
    print(f"Searching {how}:" if folders else "No song folders set.")
    for f in folders:
        print(f"  {f}")
    return 0


def cmd_params(args):
    """Device numbers and current settings for one track: what a spec's macros need."""
    try:
        als, _ = resolve_song(args.song)
        track = find_track(load_gz(als), args.track)
    except (FileNotFoundError, BuildError) as e:
        print(f"!! {e}", file=sys.stderr)
        return 1
    print(f"{als}\ntrack {args.track!r} ({track.tag})\n")
    for i, dev in enumerate(track.find("DeviceChain/DeviceChain/Devices")):
        text, _, _ = describe_device(dev)
        print(f"[{i}] {dev.tag}  —  {text}" + ("" if device_on(dev) else "  (off)"))
        if dev.tag in ("PluginDevice", "AuPluginDevice") or not args.all and dev.tag in RACK_TAGS:
            continue
        for p in dev:
            m = p.find("Manual")
            if m is not None and (p.find("MidiControllerRange") is not None or
                                  p.find("MidiCCOnOffThresholds") is not None):
                print(f"      {p.tag} = {m.get('Value')}")
    return 0


def cmd_build(args):
    status = 0
    for spec in args.specs:
        try:
            out, kind, devices, n_macros = build(spec, overwrite=args.overwrite)
        except BuildError as e:
            print(f"!! {spec}: {e}", file=sys.stderr)
            status = 1
            continue
        label = "Instrument Rack" if kind == "InstrumentGroupDevice" else "Audio Effect Rack"
        print(f"built {out}  ({label}, {len(devices)} devices, {n_macros} macros)")
    return status


def cmd_check(args):
    status = 0
    for path in args.racks:
        try:
            problems, lines = check(path)
        except (OSError, EOFError) as e:
            print(f"!! {path}: can't read it as a rack file ({e})", file=sys.stderr)
            status = 1
            continue
        print(f"{path}: {'OK' if not problems else 'PROBLEMS'}")
        for p in problems:
            print(f"  !! {p}")
            status = 1
        for line in lines:
            print(line)
    return status


def main(argv=None):
    # Track and plugin names are often non-ASCII; don't let the Windows console codepage crash us.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="rackdigger",
                                     description="Grab device chains from your Ableton Live songs as racks.")
    parser.add_argument("--version", action="version", version=f"rackdigger {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("where", help="show where your User Library is and where racks will go")
    p.set_defaults(func=cmd_where)

    p = sub.add_parser("scan", help="list every track's device chain in a song, project or folder")
    p.add_argument("path", help="a .als file, a project folder, or a folder of projects")
    p.add_argument("--json", help="also write the full scan to this JSON file")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("find", help="find a song's project by (part of) its name")
    p.add_argument("name")
    p.add_argument("--limit", type=int, default=8)
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("songs", help="show or set the folders `find` searches")
    p.add_argument("folders", nargs="*", help="set these as your song folders")
    p.set_defaults(func=cmd_songs)

    p = sub.add_parser("show", help="break down a song's tracks in plain words, with what's worth grabbing")
    p.add_argument("song", help="a .als, an exported .mp3/.wav next to one, or a project folder")
    p.add_argument("--json", help="also write the breakdown to this JSON file")
    p.add_argument("--html", help="also write a simple page of the picks as cards to this .html file")
    p.add_argument("--picks", help="JSON with chosen tracks, plain-English titles and notes for the page")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("params", help="list a track's devices by number with their current settings")
    p.add_argument("song", help="a .als, an exported .mp3/.wav next to one, or a project folder")
    p.add_argument("track", help="track number as `show` lists it, or its exact name")
    p.add_argument("--all", action="store_true", help="also list settings of racks in the chain")
    p.set_defaults(func=cmd_params)

    p = sub.add_parser("build", help="build racks from spec files")
    p.add_argument("specs", nargs="+", help="spec .json files (see examples/)")
    p.add_argument("--overwrite", action="store_true", help="replace a rack that already exists")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("check", help="sanity-check built .adg racks")
    p.add_argument("racks", nargs="+")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
