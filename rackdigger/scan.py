"""Scan Ableton .als files (read-only) and catalog every track's device chain."""
import gzip
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

TRACK_TAGS = ("AudioTrack", "MidiTrack", "GroupTrack", "ReturnTrack")
RACK_TAGS = ("AudioEffectGroupDevice", "InstrumentGroupDevice", "DrumGroupDevice", "MidiEffectGroupDevice")
SKIP_DIRS = {"Backup", "Ableton Project Info"}


def val(el, path):
    if el is None:
        return None
    node = el.find(path)
    return node.get("Value") if node is not None else None


def device_name(dev):
    """Readable name: plugin name for plugins, user name if renamed, else device type."""
    tag = dev.tag
    if tag in ("PluginDevice", "AuPluginDevice"):
        for p in ("PluginDesc/VstPluginInfo/PlugName", "PluginDesc/Vst3PluginInfo/Name",
                  "PluginDesc/AuPluginInfo/Name"):
            n = val(dev, p)
            if n:
                return n
        return "Plugin"
    user = val(dev, "UserName")
    return f"{tag} \"{user}\"" if user else tag


def device_on(dev):
    return val(dev, "On/Manual") != "false"


def walk_devices(devices_el, depth=0):
    """Return list of dicts; racks include their branches' chains."""
    out = []
    if devices_el is None:
        return out
    for dev in devices_el:
        item = {"name": device_name(dev), "type": dev.tag, "on": device_on(dev)}
        if dev.tag in RACK_TAGS:
            branches = []
            for br in (dev.find("Branches") if dev.find("Branches") is not None else []):
                if br.find("DeviceChain") is not None:
                    inner = br.find("DeviceChain/MidiToAudioDeviceChain/Devices")
                    if inner is None:
                        inner = br.find("DeviceChain/AudioToAudioDeviceChain/Devices")
                    if inner is None:
                        inner = br.find("DeviceChain/MidiToMidiDeviceChain/Devices")
                    if inner is not None:
                        branches.append({"name": val(br, "Name") or "", "devices": walk_devices(inner, depth + 1)})
            item["branches"] = branches
        out.append(item)
    return out


def count_devices(devs):
    n = 0
    for d in devs:
        n += 1
        for b in d.get("branches", []):
            n += count_devices(b["devices"])
    return n


def signature(devs):
    """Top-level chain signature (ignores parameter values)."""
    return " > ".join(d["name"] for d in devs)


def parse_als(path):
    with gzip.open(path, "rb") as f:
        root = ET.parse(f).getroot()
    live = root.find("LiveSet")
    tracks = []
    for tr in live.find("Tracks"):
        if tr.tag not in TRACK_TAGS:
            continue
        name = val(tr, "Name/EffectiveName") or val(tr, "Name/UserName") or tr.tag
        devs = walk_devices(tr.find("DeviceChain/DeviceChain/Devices"))
        tracks.append({"track": name, "kind": tr.tag, "devices": devs})
    for master_tag in ("MainTrack", "MasterTrack"):
        m = live.find(master_tag)
        if m is not None:
            devs = walk_devices(m.find("DeviceChain/DeviceChain/Devices"))
            tracks.append({"track": "MASTER", "kind": "MainTrack", "devices": devs})
            break
    return {"creator": root.get("Creator"), "tracks": tracks}


def is_live_set(path):
    """A real .als: not in Live's Backup folder and not a macOS '._' resource-fork file."""
    path = Path(path)
    return (path.suffix.lower() == ".als" and not path.name.startswith("._")
            and not SKIP_DIRS & set(path.parts))


def scan_folder(folder, on_error=None):
    """Parse every .als under folder (or one .als), skipping backups and macOS '._' files."""
    folder = Path(folder)
    sets = [folder] if folder.suffix.lower() == ".als" else sorted(folder.rglob("*.als"))
    results = []
    for als in sets:
        if not is_live_set(als):
            continue
        try:
            data = parse_als(als)
        except Exception as e:  # noqa: BLE001 - one bad set shouldn't stop a scan
            if on_error:
                on_error(als, e)
            continue
        project = als.parent.name.removesuffix(" Project")
        for t in data["tracks"]:
            t["total"] = count_devices(t["devices"])
            t["sig"] = signature(t["devices"])
        results.append({"project": project, "file": als.name, "path": str(als),
                        "creator": data["creator"], "tracks": data["tracks"]})
    return results


def summarize(results):
    """Which chains repeat across *different songs* (versions of one song count once)."""
    chains = defaultdict(lambda: {"songs": set(), "examples": []})
    devices = defaultdict(set)
    for r in results:
        for t in r["tracks"]:
            for d in t["devices"]:
                devices[d["name"]].add(r["project"])
            if len(t["devices"]) >= 2:
                c = chains[t["sig"]]
                c["songs"].add(r["project"])
                if len(c["examples"]) < 6:
                    c["examples"].append(f'{r["project"]} / {t["track"]}')
    return chains, devices


def write_json(results, path):
    chains, devices = summarize(results)
    Path(path).write_text(json.dumps({
        "files": results,
        "chains": {k: {"songs": sorted(v["songs"]), "examples": v["examples"]} for k, v in chains.items()},
        "devices": {k: sorted(v) for k, v in devices.items()},
    }, indent=1), encoding="utf-8")


def print_report(results, out):
    chains, devices = summarize(results)

    def p(*a):
        print(*a, file=out)

    p(f"Scanned {len(results)} sets from {len({r['project'] for r in results})} songs; "
      f"Live version: {sorted({r['creator'] for r in results})}\n")
    p("== Most-used devices (by # of songs) ==")
    for name, songs in sorted(devices.items(), key=lambda kv: -len(kv[1]))[:40]:
        p(f"{len(songs):3}  {name}")
    p("\n== Chains (2+ devices) repeated across songs ==")
    for sig, c in sorted(chains.items(), key=lambda kv: (-len(kv[1]["songs"]), -kv[0].count(">"))):
        if len(c["songs"]) >= 2:
            p(f'{len(c["songs"]):3} songs | {sig}\n      e.g. {"; ".join(c["examples"][:3])}')
    p("\n== Longest chains (one row per distinct chain per song) ==")
    seen = set()
    rows = []
    for r in results:
        for t in r["tracks"]:
            key = (r["project"], t["sig"])
            if key in seen or t["total"] < 4:
                continue
            seen.add(key)
            rows.append((t["total"], r["project"], r["file"], t["track"], t["sig"]))
    for total, proj, f, trk, sig in sorted(rows, reverse=True)[:40]:
        p(f"{total:3} devs | {proj} / {trk}  [{f}]\n         {sig}")
