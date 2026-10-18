"""Turn one track's device chain from an .als into an Audio Effect Rack (.adg).

spec.json (relative paths resolve from the spec file's folder):
{
  "als": "path/to/song.als",
  "track": 6,                    # track number as `rackdigger show` lists it, or its exact name
  "rack_name": "Lo-Fi Radio Sample",
  "category": "FX",              # folder under User Library/Rack Digger/
  "out": "optional/explicit/path.adg",   # overrides category placement
  "template": "optional/rack.adg",       # defaults to the bundled template
  "effects_only": false,         # instrument tracks: keep only the effects after the instrument
  "macros": [                     # up to 16; macro sits at "start" (0-127)
    {"name": "Crush", "start": 0, "targets": [
        {"device": 4, "param": "SampleRate", "min": 20440, "max": 3000}]}
  ]
}
Plugins (VST2/VST3) keep their full saved state; nested Audio Effect Racks keep
their branches, branch mixers and own macros.
"device" is the 0-based position in the track's chain; "param" is the XML tag
(nested params use a slash, e.g. "Bands.0/ParameterA/Gain").
"""
import copy
import gzip
import json
import xml.etree.ElementTree as ET
from importlib import resources
from pathlib import Path

from .library import find_user_library, output_root
from .scan import TRACK_TAGS

class BuildError(Exception):
    """A spec that can't be turned into a rack; the message says why."""


ID_TAGS = {"AutomationTarget", "ModulationTarget", "Pointee"}
RACK_TAGS = ("AudioEffectGroupDevice", "InstrumentGroupDevice", "DrumGroupDevice", "MidiEffectGroupDevice")
AUDIO_RACK, INSTRUMENT_RACK = "AudioEffectGroupDevice", "InstrumentGroupDevice"
TEMPLATE_FILES = {AUDIO_RACK: "audio_effect_rack.xml", INSTRUMENT_RACK: "instrument_rack.xml"}
UNSUPPORTED_RACKS = {"DrumGroupDevice": "Drum Racks", "MidiEffectGroupDevice": "MIDI Effect Racks"}


def load_gz(path):
    with gzip.open(path, "rb") as f:
        return ET.parse(f).getroot()


def load_template(path=None, kind=AUDIO_RACK):
    if path:
        return load_gz(path)
    xml = resources.files("rackdigger").joinpath("templates", TEMPLATE_FILES[kind]).read_bytes()
    return ET.fromstring(xml)


def rack_kind_for(track):
    """MIDI tracks become Instrument Racks (MIDI effects + instrument + effects); audio tracks effect racks."""
    return INSTRUMENT_RACK if track.tag == "MidiTrack" else AUDIO_RACK


def find_track(als_root, track):
    """A track by its number (as `rackdigger show` numbers them, from 1) or by its exact name.
    A name shared by several tracks is refused rather than guessed."""
    tracks = [t for t in als_root.find("LiveSet/Tracks") if t.tag in TRACK_TAGS]
    if isinstance(track, int) or str(track).isdigit():
        n = int(track)
        if not 1 <= n <= len(tracks):
            raise BuildError(f"there's no track {n}; this song has tracks 1-{len(tracks)}")
        return tracks[n - 1]
    hits = [(i, t) for i, t in enumerate(tracks, 1)
            if t.find("Name/EffectiveName") is not None and t.find("Name/EffectiveName").get("Value") == track]
    if not hits:
        raise BuildError(f"track {track!r} not found")
    if len(hits) > 1:
        raise BuildError(f"{len(hits)} tracks are named {track!r} (tracks {', '.join(str(i) for i, _ in hits)}); "
                         "use the track number instead")
    return hits[0][1]


def is_midi_effect(dev):
    return dev.tag.startswith("Midi") or dev.tag == "MxDeviceMidiEffect"


def find_track_devices(als_root, track_name, effects_only=False):
    """(rack kind, devices, offset). With effects_only, an instrument track's MIDI effects and
    instrument are dropped and the effects after them become an Audio Effect Rack; offset is how
    many devices were dropped, so spec device numbers can keep matching `rackdigger params`."""
    tr = find_track(als_root, track_name)
    devices = list(tr.find("DeviceChain/DeviceChain/Devices"))
    kind, offset = rack_kind_for(tr), 0
    if effects_only:
        if kind != INSTRUMENT_RACK:
            raise BuildError(f"{track_name!r} is an audio track; effects_only is for instrument tracks")
        while offset < len(devices) and is_midi_effect(devices[offset]):
            offset += 1
        offset += 1  # the instrument itself
        devices = devices[offset:]
        if not devices:
            raise BuildError(f"{track_name!r} has no effects after its instrument")
        kind = AUDIO_RACK
    for d in devices:
        for el in d.iter():
            if el.tag in UNSUPPORTED_RACKS:
                raise BuildError(f"{track_name!r} contains a {UNSUPPORTED_RACKS[el.tag][:-1]}; "
                                 f"{UNSUPPORTED_RACKS[el.tag]} aren't supported yet")
    return kind, devices, offset


def scrub_ids(dev):
    """Presets store zeroed ids; Live assigns fresh ones on load."""
    dev.set("Id", "0")
    for el in dev.iter():
        if el.tag in ID_TAGS and "Id" in el.attrib:
            el.set("Id", "0")
        if el.tag == "LomId" or el.tag == "LomIdView":
            el.set("Value", "0")


def map_param(dev, param_path, macro_idx, lo, hi):
    if dev.tag in PLUGIN_TAGS:
        raise BuildError("mapping macros to plugin parameters isn't supported; map a built-in device instead")
    p = dev.find(param_path)
    if p is None or p.find("Manual") is None:
        raise BuildError(f"{dev.tag}: no parameter {param_path!r}")
    old = p.find("KeyMidi")
    if old is not None:
        p.remove(old)
    km = ET.Element("KeyMidi")
    for tag, v in (("PersistentKeyString", ""), ("IsNote", "false"), ("Channel", "16"),
                   ("NoteOrController", str(macro_idx)), ("LowerRangeNote", "-1"),
                   ("UpperRangeNote", "-1"), ("ControllerMapMode", "0")):
        ET.SubElement(km, tag, Value=v)
    children = list(p)
    pos = children.index(p.find("LomId")) + 1 if p.find("LomId") is not None else 0
    p.insert(pos, km)
    # Continuous params have a value range; on/off switches have macro-position thresholds (0-127).
    rng = p.find("MidiControllerRange")
    if rng is None:
        rng = p.find("MidiCCOnOffThresholds")
    rng.find("Min").set("Value", str(lo))
    rng.find("Max").set("Value", str(hi))


PLUGIN_TAGS = ("PluginDevice", "AuPluginDevice")


class RackParts:
    """Preset wrappers for one kind of rack, copied from a Live-saved rack."""

    def __init__(self, gdp):
        branch = gdp.find("BranchPresets")[0]
        self.protect = copy.deepcopy(gdp.find("OverwriteProtectionNumber"))
        self.rack_presetref = copy.deepcopy(gdp.find("PresetRef"))
        self.device = copy.deepcopy(next(x for x in branch.find("DevicePresets") if x.tag == "AbletonDevicePreset"))
        self.branch = copy.deepcopy(branch)


class Templates:
    """Rack parts for every supported kind; the outer rack's own template wins for its kind."""

    def __init__(self, outer_kind, outer_gdp):
        self.parts = {kind: RackParts(load_template(kind=kind).find("GroupDevicePreset")) for kind in TEMPLATE_FILES}
        self.parts[outer_kind] = RackParts(outer_gdp)
        self.device = self.parts[outer_kind].device

    def for_rack(self, kind):
        if kind not in self.parts:
            raise BuildError(f"{UNSUPPORTED_RACKS.get(kind, kind)} inside a chain aren't supported yet")
        return self.parts[kind]


def wrap_ableton(dev, i, tpls):
    w = copy.deepcopy(tpls.device)
    w.set("Id", str(i))
    slot = w.find("Device")
    for x in list(slot):
        slot.remove(x)
    dev.set("Id", "0")
    slot.append(dev)
    w.find("PresetRef/AbletonDefaultPresetRef/DeviceId").set("Name", dev.tag)
    return w


def plugin_preset(dev, i):
    """The .als keeps the plugin's full saved state as a ready-made preset element."""
    preset = dev.find("PluginDesc")[0].find("Preset")[0]
    p = copy.deepcopy(preset)
    p.set("Id", str(i))
    p.find("IsOn").set("Value", "true" if dev.find("On/Manual").get("Value") != "false" else "false")
    return p


def branch_preset(br, j, parts, tpls):
    b = copy.deepcopy(parts.branch)
    b.set("Id", str(j))
    b.find("Name").set("Value", br.find("Name/UserName").get("Value"))
    b.find("IsSoloed").set("Value", br.find("IsSoloed").get("Value"))
    chain = br.find("DeviceChain")[0].find("Devices")
    fill_device_presets(b.find("DevicePresets"), list(chain), tpls)
    mixer = copy.deepcopy(br.find("MixerDevice"))
    mixer.tag = "AudioBranchMixerDevice"
    slot = b.find("MixerPreset/AbletonDevicePreset/Device")
    for x in list(slot):
        slot.remove(x)
    slot.append(mixer)
    b.remove(b.find("BranchSelectorRange"))
    b.insert(4, copy.deepcopy(br.find("BranchSelectorRange")))
    b.find("DocumentColorIndex").set("Value", br.find("Color").get("Value"))
    b.find("AutoColored").set("Value", br.find("AutoColored").get("Value"))
    # Instrument Rack chains also carry key/velocity zones.
    if br.find("ZoneSettings") is not None and b.find("ZoneSettings") is not None:
        b.remove(b.find("ZoneSettings"))
        b.append(copy.deepcopy(br.find("ZoneSettings")))
    return b


def group_preset(dev, i, tpls):
    parts = tpls.for_rack(dev.tag)
    g = ET.Element("GroupDevicePreset", Id=str(i))
    g.append(copy.deepcopy(parts.protect))
    rack = copy.deepcopy(dev)
    rack.set("Id", "0")
    rack.find("Branches").clear()
    ET.SubElement(g, "Device").append(rack)
    g.append(copy.deepcopy(parts.rack_presetref))
    bp = ET.SubElement(g, "BranchPresets")
    for j, br in enumerate(dev.find("Branches")):
        bp.append(branch_preset(br, j, parts, tpls))
    ET.SubElement(g, "ReturnBranchPresets")
    return g


def fill_device_presets(dp, devices, tpls):
    for x in list(dp):
        dp.remove(x)
    for i, d in enumerate(devices):
        if d.tag in PLUGIN_TAGS:
            dp.append(plugin_preset(d, i))
        elif d.tag in RACK_TAGS:
            dp.append(group_preset(d, i, tpls))
        else:
            dp.append(wrap_ableton(d, i, tpls))


def indent(elem, level=0):
    pad = "\n" + "\t" * level
    if len(elem):
        if not (elem.text or "").strip():
            elem.text = pad + "\t"
        for child in elem:
            indent(child, level + 1)
        if not (child.tail or "").strip():
            child.tail = pad
    if level and not (elem.tail or "").strip():
        elem.tail = pad


INVALID_NAME_CHARS = '<>:"/\\|?*'


def resolve_out(spec, base):
    if spec.get("out"):
        return base / spec["out"]
    lib, _ = find_user_library()
    if lib is None:
        raise BuildError('couldn\'t find your Ableton User Library; set "out" in the spec '
                         "or the RACKDIGGER_USER_LIBRARY environment variable")
    safe = "".join(c for c in spec["rack_name"] if c not in INVALID_NAME_CHARS).strip()
    return output_root(lib) / spec.get("category", "Unsorted") / f"{safe}.adg"


def build(spec_path, overwrite=False):
    """Build the rack a spec describes. Returns (output path, device tags, macro count)."""
    spec_path = Path(spec_path)
    try:
        # utf-8-sig: Notepad and PowerShell save JSON with a BOM.
        spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise BuildError("spec file not found") from None
    except json.JSONDecodeError as e:
        raise BuildError(f"spec isn't valid JSON ({e})") from None
    missing = [k for k in ("als", "track", "rack_name") if not spec.get(k)]
    if missing:
        raise BuildError(f"spec is missing {', '.join(missing)}")
    base = spec_path.resolve().parent
    if not (base / spec["als"]).is_file():
        raise BuildError(f"Live set not found: {base / spec['als']}")
    out = resolve_out(spec, base)
    if out.exists() and not overwrite:
        raise BuildError(f"{out} already exists; pick another rack_name or pass --overwrite")

    kind, found, offset = find_track_devices(load_gz(base / spec["als"]), spec["track"],
                                             bool(spec.get("effects_only")))
    devices = [copy.deepcopy(d) for d in found]
    for d in devices:
        scrub_ids(d)

    tpl = load_template(base / spec["template"] if spec.get("template") else None, kind)
    gdp = tpl.find("GroupDevicePreset")
    rack = gdp.find(f"Device/{kind}")
    if rack is None:
        label = "an Instrument Rack" if kind == INSTRUMENT_RACK else "an Audio Effect Rack"
        raise BuildError(f"this track needs {label} template")
    rack.find("UserName").set("Value", spec["rack_name"])

    macros = spec.get("macros", [])
    if len(macros) > 16:
        raise BuildError("a rack has at most 16 macros")
    for i, m in enumerate(macros):
        rack.find(f"MacroDisplayNames.{i}").set("Value", m["name"])
        rack.find(f"MacroControls.{i}/Manual").set("Value", str(m.get("start", 0)))
        for t in m["targets"]:
            # Device numbers are the track's own (as `rackdigger params` shows them).
            at = t["device"] - offset
            if not 0 <= at < len(devices):
                raise BuildError(f"macro {m['name']!r}: device {t['device']} isn't in the rack "
                                 f"(devices {offset}-{offset + len(devices) - 1})")
            map_param(devices[at], t["param"], i, t["min"], t["max"])
    if macros:
        rack.find("NumVisibleMacroControls").set("Value", "8" if len(macros) <= 8 else "16")
        rack.find("AreMacroControlsVisible").set("Value", "true")

    # One branch holding the whole chain; reuse the template's preset wrappers.
    branch = gdp.find("BranchPresets")[0]
    for extra in list(gdp.find("BranchPresets"))[1:]:
        gdp.find("BranchPresets").remove(extra)
    branch.find("Name").set("Value", spec["rack_name"])
    tpls = Templates(kind, gdp)
    fill_device_presets(branch.find("DevicePresets"), devices, tpls)

    indent(tpl)
    data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(tpl, encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wb") as f:
        f.write(data)
    return out, kind, [d.tag for d in devices], len(macros)
