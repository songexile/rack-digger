"""Sanity-check a built .adg: rack layout and macro mappings."""
from .build import TEMPLATE_FILES, load_gz, load_template

LABELS = {"AudioEffectGroupDevice": "Audio Effect Rack", "InstrumentGroupDevice": "Instrument Rack"}


def outline(root):
    g = root.find("GroupDevicePreset")
    b = g.find("BranchPresets")[0]
    return [c.tag for c in g], [c.tag for c in b]


def check(path):
    """Return (problems, report lines) for one rack file."""
    root = load_gz(path)
    device = root.find("GroupDevicePreset/Device")
    kind = device[0].tag if device is not None and len(device) else None
    if kind not in TEMPLATE_FILES:
        return [f"not a rack type Rack Digger builds ({kind or 'no rack'})"], []
    problems = []
    if outline(root) != outline(load_template(kind=kind)):
        problems.append(f"layout differs from Live's saved {LABELS[kind]} layout")

    rack = device[0]
    lines = [f"{LABELS[kind]}: {rack.find('UserName').get('Value')!r}"]
    dp = root.find("GroupDevicePreset/BranchPresets")[0].find("DevicePresets")
    for i, p in enumerate(dp):
        what = p.find("Device")[0].tag if p.find("Device") is not None else p.tag
        lines.append(f"  [{i}] {what}")

    # Only the outer rack's own mappings: nested racks keep their own macros.
    for p in dp:
        dev = p.find("Device")
        if dev is None or p.tag == "GroupDevicePreset":
            continue
        for param in dev[0].iter():
            km = param.find("KeyMidi")
            if km is None or km.find("Channel").get("Value") != "16":
                continue
            idx = int(km.find("NoteOrController").get("Value"))
            rng = param.find("MidiControllerRange")
            if rng is None:
                rng = param.find("MidiCCOnOffThresholds")
            name = rack.find(f"MacroDisplayNames.{idx}").get("Value")
            start = rack.find(f"MacroControls.{idx}/Manual").get("Value")
            lines.append(f"  macro {idx + 1} {name!r} (starts at {start}) -> {dev[0].tag}.{param.tag}: "
                         f"{rng.find('Min').get('Value')} .. {rng.find('Max').get('Value')}")
    return problems, lines
