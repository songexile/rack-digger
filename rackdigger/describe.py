"""Describe a song's tracks in plain words so you can decide what to grab."""
import binascii
import gzip
import math
import re
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

from . import serum2
from .scan import RACK_TAGS, TRACK_TAGS, is_live_set, val

FRIENDLY = {
    "Eq8": "EQ Eight", "Compressor2": "Compressor", "StereoGain": "Utility", "OriginalSimpler": "Simpler",
    "MultiSampler": "Sampler", "MultibandDynamics": "Multiband Dynamics", "AutoFilter": "Auto Filter",
    "PhaserNew": "Phaser-Flanger", "Redux2": "Redux", "ChannelEq": "Channel EQ", "FilterEQ3": "EQ Three",
    "GlueCompressor": "Glue Compressor", "DrumGroupDevice": "Drum Rack", "InstrumentGroupDevice": "Instrument Rack",
    "AudioEffectGroupDevice": "Effect Rack", "MidiEffectGroupDevice": "MIDI Effect Rack",
    "MidiArpeggiator": "Arpeggiator", "SpectrumAnalyzer": "Spectrum", "FrequencyShifter": "Frequency Shifter",
    "Tuner": "Tuner", "Gate": "Gate", "Limiter": "Limiter", "Saturator": "Saturator", "Overdrive": "Overdrive",
    "Reverb": "Reverb", "Delay": "Delay", "Chorus2": "Chorus-Ensemble", "AutoPan": "Auto Pan",
    "DrumBuss": "Drum Buss", "Erosion": "Erosion", "Vinyl": "Vinyl Distortion", "Echo": "Echo",
    "HybridReverb": "Hybrid Reverb", "Roar": "Roar", "Pedal": "Pedal", "Amp": "Amp", "Cabinet": "Cabinet",
}
INSTRUMENT_TAGS = {"OriginalSimpler", "MultiSampler", "InstrumentVector", "UltraAnalog", "Operator", "Collision",
                   "LoungeLizard", "StringStudio", "Drift", "Meld", "InstrumentImpulse", "DrumGroupDevice",
                   "InstrumentGroupDevice"}
# Plugin name fragment -> what it does. Checked in order, case-insensitive.
PLUGIN_KINDS = [
    ("serumfx", "Serum FX"), ("serum", "synth"), ("nexus", "ROMpler synth"), ("sylenth", "synth"),
    ("massive", "synth"), ("vital", "synth"), ("jp6k", "synth"), ("viper", "synth"), ("spire", "synth"),
    ("omnisphere", "synth"), ("kontakt", "sampler"), ("auto-tune", "pitch correction"), ("melodyne", "pitch editing"),
    ("pro-c", "compressor"), ("pro-ds", "de-esser"), ("pro-q", "EQ"), ("pro-mb", "multiband compressor"),
    ("pro-l", "limiter"), ("pro-r", "reverb"), ("ott", "multiband squash"), ("kickstart", "sidechain pump"),
    ("lfotool", "sidechain pump"), ("valhalladelay", "delay"), ("valhallafreqecho", "delay"),
    ("valhallasupermassive", "reverb / delay"), ("valhalla", "reverb"), ("rx950", "vintage sampler grit"),
    ("sp950", "vintage sampler grit"), ("sp1200", "vintage sampler grit"), ("rc-20", "lo-fi texture"), ("la-2a", "compressor"), ("1176", "compressor"),
    ("distressor", "compressor / saturation"), ("plate", "reverb"), ("ampex", "tape saturation"),
    ("j37", "tape saturation"), ("tape", "tape saturation"), ("decapitator", "saturation"),
    ("soothe", "resonance suppressor"), ("ozone", "mastering"), ("trash", "distortion"),
]
SYNTH_KINDS = ("synth", "ROMpler synth", "sampler")
VOCAL_KINDS = ("pitch correction", "pitch editing", "de-esser")
DRUM_WORDS = ("kick", "snare", "clap", "hat", "perc", "cymbal", "crash", "ride", "tom", "rim", "shaker", "808",
              "drum", "loop", "fill", "break")
FX_WORDS = ("impact", "riser", "sweep", "fx", "uplifter", "downlifter", "noise", "whoosh", "reverse")
VOX_WORDS = ("vox", "vocal", "voc", "acapella", "adlib", "rap")  # not verse/hook/chorus: those name song sections


def _f(el, path, default=None):
    v = val(el, path)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _db(amp):
    return 20 * math.log10(amp) if amp and amp > 0 else None


def _pct(x):
    return f"{x * 100:.0f}%"


# ---------- plugins ----------

def plugin_name(dev):
    info = dev.find("PluginDesc")[0]
    for tag in ("Name", "PlugName"):
        n = info.find(tag)
        if n is not None and n.get("Value"):
            return n.get("Value")
    return "Plugin"


def plugin_kind(name):
    low = name.lower()
    for frag, kind in PLUGIN_KINDS:
        if frag in low:
            return kind
    return None


def _plugin_state(dev):
    info = dev.find("PluginDesc")[0]
    preset = info.find("Preset")
    if preset is None or not len(preset):
        return b""
    p = preset[0]
    buf = p.find("ProcessorState") if p.find("ProcessorState") is not None else p.find("Buffer")
    try:
        return binascii.unhexlify("".join((buf.text or "").split()))
    except (AttributeError, binascii.Error):
        return b""


def serum_patch(dev):
    """Serum keeps its patch zlib-compressed; the name sits after the wavetable paths.
    Returns (patch, author) or (None, None)."""
    raw = _plugin_state(dev)
    for i in range(len(raw) - 1):
        if raw[i] != 0x78 or raw[i + 1] not in (0x01, 0x5E, 0x9C, 0xDA):
            continue
        try:
            out = zlib.decompressobj().decompress(raw[i:])
        except zlib.error:
            continue
        strings = [s.decode("latin1").strip() for s in re.findall(rb"[A-Za-z][\x20-\x7e]{3,60}", out)]
        wavs = [k for k, s in enumerate(strings) if s.lower().endswith(".wav")]
        if not wavs:
            continue
        rest = strings[wavs[-1] + 1:]
        if not rest:
            return None, None
        patch = rest[0].rstrip(" -")
        author = rest[1] if len(rest) > 1 and not rest[1].startswith("Macro") else None
        return patch, author
    return None, None


# ---------- built-in devices ----------

def describe_native(dev):
    tag = dev.tag
    name = FRIENDLY.get(tag, tag)
    user = val(dev, "UserName")
    if user and user != name:
        name = f'{name} "{user}"'
    bits = []
    if tag == "Reverb":
        decay = _f(dev, "DecayTime/Manual")
        direct = _f(dev, "MixDirect/Manual")
        if decay:
            bits.append(f"{decay / 1000:.1f}s decay")
        if direct is not None and direct < 0.4:
            bits.append("mostly wet")
        if (_f(dev, "RoomSize/Manual") or 0) > 80:
            bits.append("huge room")
    elif tag in ("Delay", "Echo"):
        fb, mix = _f(dev, "Feedback/Manual"), _f(dev, "DryWet/Manual")
        if val(dev, "DelayLine_PingPong/Manual") == "true":
            bits.append("ping-pong")
        if fb is not None:
            bits.append(f"{_pct(fb)} feedback")
        if mix is not None:
            bits.append(f"{_pct(mix)} mix")
    elif tag == "Redux2":
        sr, bd, mix = _f(dev, "SampleRate/Manual"), _f(dev, "BitDepth/Manual"), _f(dev, "DryWet/Manual")
        if sr:
            bits.append(f"down to {sr / 1000:.1f} kHz")
        if bd and bd < 16:
            bits.append(f"{bd:.0f}-bit")
        if mix is not None and mix < 0.99:
            bits.append(f"{_pct(mix)} mix")
    elif tag in ("Compressor2", "GlueCompressor"):
        ratio, thr = _f(dev, "Ratio/Manual"), _db(_f(dev, "Threshold/Manual"))
        if ratio:
            bits.append(f"{ratio:g}:1")
        if thr is not None:
            bits.append("barely touching" if thr > -3 else f"threshold {thr:.0f} dB")
    elif tag == "StereoGain":
        if val(dev, "Mono/Manual") == "true":
            bits.append("mono")
        width = _f(dev, "StereoWidth/Manual")
        if width is not None and abs(width - 1) > 0.01 and val(dev, "Mono/Manual") != "true":
            bits.append(f"width {_pct(width)}")
        gain = _db(_f(dev, "Gain/Manual"))
        if gain is not None and abs(gain) > 0.5:
            bits.append(f"{gain:+.1f} dB")
    elif tag in ("PhaserNew", "Chorus2", "Saturator", "Overdrive", "AutoFilter"):
        mix = _f(dev, "DryWet/Manual")
        if mix is not None and mix < 0.99:
            bits.append(f"{_pct(mix)} mix")
    return name + (f" ({', '.join(bits)})" if bits else "")


# ---------- chains ----------

def _rack_branches(dev):
    out = []
    for br in dev.find("Branches") if dev.find("Branches") is not None else []:
        chain = br.find("DeviceChain")
        devs = chain[0].find("Devices") if chain is not None and len(chain) else None
        out.append((val(br, "Name/EffectiveName") or "", list(devs) if devs is not None else []))
    return out


def loaded_preset(dev):
    """Name of the preset file the device or rack was loaded from, if Live recorded one."""
    ref = dev.find("LastPresetRef/Value")
    if ref is None or not len(ref) or ref[0].tag == "AbletonDefaultPresetRef":
        return None
    for tag in ("FileRef/Path", "FileRef/RelativePath"):
        p = val(ref[0], tag)
        if p:
            return Path(p.replace("\\", "/")).stem
    return None


def describe_device(dev):
    """(text, is_instrument, plugin kind or None)"""
    text, is_inst, kind = _describe_device(dev)
    preset = loaded_preset(dev)
    if preset and preset not in text:
        text += f' [preset "{preset}"]'
    return text, is_inst, kind


def _describe_device(dev):
    if dev.tag in ("PluginDevice", "AuPluginDevice"):
        name = plugin_name(dev)
        kind = plugin_kind(name)
        text = name
        if kind == "synth" and name.lower().startswith("serum 2"):
            patch = serum2.summary(_plugin_state(dev))
            if patch:
                text += f" — {patch}"
        elif kind == "synth" and "serum" in name.lower():
            patch, author = serum_patch(dev)
            if patch:
                text += " — built from scratch (Init)" if patch.lower().startswith("init") else \
                    f' — patch "{patch}"' + (f" by {author}" if author else "")
        elif kind:
            text += f" ({kind})"
        return text, kind in SYNTH_KINDS, kind
    if dev.tag in RACK_TAGS:
        branches = _rack_branches(dev)
        inner = sum(len(d) for _, d in branches)
        user = val(dev, "UserName")
        label = FRIENDLY.get(dev.tag, dev.tag) + (f' "{user}"' if user else "")
        return f"{label} ({len(branches)} chain{'s' * (len(branches) != 1)}, {inner} devices)", \
            dev.tag in INSTRUMENT_TAGS, None
    if dev.tag == "OriginalSimpler" or dev.tag == "MultiSampler":
        sample = next((Path(fr.find("Path").get("Value")).name for fr in dev.iter("FileRef")
                       if fr.find("Path") is not None and fr.find("Path").get("Value")), None)
        return f"{FRIENDLY[dev.tag]}" + (f' playing "{sample}"' if sample else ""), True, None
    return describe_native(dev), dev.tag in INSTRUMENT_TAGS, None


def device_on(dev):
    return val(dev, "On/Manual") != "false"


# ---------- tracks ----------

def _clips(tr):
    arr = tr.findall(".//ArrangerAutomation/Events/MidiClip") + tr.findall(".//ArrangerAutomation/Events/AudioClip")
    sess = tr.findall(".//ClipSlot//MidiClip") + tr.findall(".//ClipSlot//AudioClip")
    return arr, sess


def _clip_beats(clips):
    return sum(_f(c, "CurrentEnd", 0) - _f(c, "CurrentStart", 0) for c in clips)


def guess_role(track_name, kind, synth, notes, sample_names, plugin_kinds=(), sampler=False):
    low = " ".join([track_name] + sample_names).lower()
    if kind == "GroupTrack":
        return "group bus"
    if kind == "ReturnTrack":
        return "return (send effect)"
    if kind == "MainTrack":
        return "master"
    if any(w in low for w in VOX_WORDS) or any(k in VOCAL_KINDS for k in plugin_kinds):
        return "vocal"
    if any(w in low for w in FX_WORDS):
        return "FX hit"
    if any(w in low for w in DRUM_WORDS):
        return "drums / percussion"
    if sampler:
        return "bass" if "bass" in low else "sample"
    if notes:
        avg = sum(notes) / len(notes)
        if "bass" in low or avg < 48:
            return "bass"
        return "lead / chords" if avg >= 60 else "synth (mid range)"
    if "bass" in low:
        return "bass"
    if kind == "AudioTrack":
        return "audio"
    return "instrument" if synth else "unknown"


def describe_track(tr, song_beats):
    kind = tr.tag
    name = val(tr, "Name/EffectiveName") or kind
    devices = list(tr.find("DeviceChain/DeviceChain/Devices"))
    arr, sess = _clips(tr)
    beats = _clip_beats(arr)
    notes = [int(k.find("MidiKey").get("Value")) for k in tr.iter("KeyTrack")]
    clip_names = sorted({val(c, "Name") for c in arr + sess if val(c, "Name") and val(c, "Name") != "MIDI"})
    muted = val(tr, "DeviceChain/Mixer/Speaker/Manual") == "false"

    steps, sources, active_fx, plugin_kinds, chain = [], [], 0, [], []
    for dev in devices:
        text, is_inst, pkind = describe_device(dev)
        on = device_on(dev)
        if pkind:
            plugin_kinds.append(pkind)
        if is_inst:
            sources.append(text)
        elif on and dev.tag in RACK_TAGS:
            active_fx += max(1, sum(device_on(d) for _, ds in _rack_branches(dev) for d in ds))
        elif on and dev.tag not in ("SpectrumAnalyzer", "Tuner"):
            active_fx += 1
        steps.append(text if on else f"[off] {text}")
        label, detail = split_label(text)
        chain.append({"name": label, "detail": detail, "on": on,
                      "type": "source" if is_inst else "rack" if dev.tag in RACK_TAGS
                      else "plugin" if dev.tag in ("PluginDevice", "AuPluginDevice") else "native"})
    # Guess the role from names only: device descriptions mention FX, chorus etc.
    sample_names = [Path(fr.find("Path").get("Value")).name
                    for dev in devices if dev.tag in ("OriginalSimpler", "MultiSampler")
                    for fr in dev.iter("FileRef") if fr.find("Path") is not None and fr.find("Path").get("Value")]
    sample_names += clip_names
    sampler = any(d.tag in ("OriginalSimpler", "MultiSampler") for d in devices)
    role = guess_role(name, kind, any(sources), notes, sample_names, plugin_kinds, sampler)

    usage = []
    if kind in ("AudioTrack", "MidiTrack"):
        if beats:
            share = f" of {song_beats / 4:.0f}" if song_beats else ""
            bars = round(beats / 4)
            usage.append(("plays under 1 bar" if beats < 4 else f"plays {bars} bar{'s' * (bars != 1)}") + share)
        elif sess:
            usage.append(f"{len(sess)} session clip{'s' * (len(sess) != 1)} only")
        else:
            usage.append("no clips (unused)")
    if notes:
        usage.append(f"notes {_note(min(notes))}–{_note(max(notes))}")
    if muted:
        usage.append("muted")

    # Suggestion: is there a sound worth keeping here?
    plays = beats > 0 or kind in ("GroupTrack", "ReturnTrack", "MainTrack", "MasterTrack")
    if not devices or (active_fx == 0 and not sources):
        verdict = ("skip", "no active devices")
    elif not plays:
        verdict = ("skip", "not used in the song")
    elif any(k in SYNTH_KINDS for k in plugin_kinds) and active_fx >= 2:
        verdict = ("grab", f"synth patch + {active_fx} effects shaping it")
    elif any("FX: " in s for s in sources):
        verdict = ("grab", "designed synth patch with its own FX")
    elif active_fx >= 3:
        verdict = ("grab", f"{active_fx} active effects shaping the sound")
    elif active_fx == 2 or any(k in SYNTH_KINDS for k in plugin_kinds):
        verdict = ("maybe", "small chain")
    else:
        verdict = ("skip", "only one or two simple devices")

    return {"track": name, "kind": kind, "role": role, "sources": sources, "steps": steps, "chain_key": " > ".join(steps),
            "chain": chain, "segments": _segments(arr), "muted": muted,
            "usage": usage, "clip_names": clip_names[:4], "verdict": verdict}


def _segments(clips):
    """Where the track plays, as merged [start bar, end bar] spans (4/4 assumed)."""
    spans = sorted((_f(c, "CurrentStart", 0) / 4, _f(c, "CurrentEnd", 0) / 4) for c in clips)
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def split_label(text):
    """'Delay (ping-pong, 50% mix)' -> ('Delay', 'ping-pong, 50% mix')."""
    cuts = [i for i in (text.find(" ("), text.find(" — "), text.find(" ["), text.find(" playing ")) if i > 0]
    if not cuts:
        return text, ""
    i = min(cuts)
    detail = text[i:].strip()
    if detail.startswith("— "):
        detail = detail[2:]
    if detail.startswith("(") and detail.endswith(")") and detail.count("(") == 1:
        detail = detail[1:-1]
    return text[:i], detail


NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _note(midi):
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 2}"


def describe_song(als_path):
    with gzip.open(als_path, "rb") as f:
        root = ET.parse(f).getroot()
    live = root.find("LiveSet")
    tracks = [t for t in live.find("Tracks") if t.tag in TRACK_TAGS]
    song_beats = max((_f(c, "CurrentEnd", 0) for t in tracks for c in _clips(t)[0]), default=0)
    out = [describe_track(t, song_beats) for t in tracks]
    first_with = {}
    for n, d in enumerate(out, 1):
        if d["verdict"][0] == "skip":
            continue
        if d["chain_key"] in first_with:
            d["same_as"] = first_with[d["chain_key"]]
        else:
            first_with[d["chain_key"]] = n
    for tag in ("MainTrack", "MasterTrack"):
        m = live.find(tag)
        if m is not None:
            d = describe_track(m, song_beats)
            d["track"], d["kind"], d["role"] = "Main", "MainTrack", "master"
            out.append(d)
            break
    return {"creator": root.get("Creator"), "bars": song_beats / 4, "tracks": out}


# ---------- choosing the set ----------

def resolve_song(path):
    """Accept a .als, an exported audio file next to one, or a project folder.
    Returns (als path, reason)."""
    p = Path(path)
    if p.suffix.lower() == ".als":
        return p, "as given"
    if p.is_file():
        match = p.with_suffix(".als")
        if match.is_file():
            return match, f"matches {p.name}"
        p = p.parent
    if p.is_dir():
        sets = [a for a in p.glob("*.als") if is_live_set(a)]
        if not sets:
            sets = [a for a in p.rglob("*.als") if is_live_set(a)]
        if sets:
            newest = max(sets, key=lambda a: a.stat().st_mtime)
            others = len(sets) - 1
            return newest, "newest saved set" + (f"; {others} other version{'s' * (others != 1)} here" if others else "")
    raise FileNotFoundError(f"no Live set found for {path}")
