"""Read what a Serum 2 patch is made of from its saved plugin state.

Serum 2 doesn't store the patch name in the project, but its state (a small JSON
header, then zstd-compressed CBOR) does hold the oscillators, wavetables, filter,
FX and voicing. zstd needs Python 3.14+; on older Pythons this returns None.
"""
import struct
from pathlib import PurePosixPath

try:
    from compression import zstd
except ImportError:  # Python < 3.14
    zstd = None

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
FX_NAMES = {"FXEQ": "EQ", "FXComp": "Compressor", "FXChorus": "Chorus", "FXReverb": "Reverb", "FXDelay": "Delay",
            "FXFilter": "Filter", "FXDistortion": "Distortion", "FXFlanger": "Flanger", "FXPhaser": "Phaser",
            "FXHyperDimension": "Hyper/Dimension", "FXMultiband": "Multiband", "FXBode": "Frequency Shifter",
            "FXConvolve": "Convolve", "FXConv": "Convolve", "FXUtility": "Utility", "FXSplitter": "Splitter"}
DEFAULT_TABLE = "Default Shapes"


def _cbor(b, i=0):
    """Minimal CBOR decoder: enough for Serum 2's state (no indefinite lengths, no tags)."""
    ib = b[i]
    mt, ai = ib >> 5, ib & 31
    i += 1
    if mt == 7:
        if ai == 25:
            return struct.unpack(">e", b[i:i + 2])[0], i + 2
        if ai == 26:
            return struct.unpack(">f", b[i:i + 4])[0], i + 4
        if ai == 27:
            return struct.unpack(">d", b[i:i + 8])[0], i + 8
        return {20: False, 21: True, 22: None}.get(ai), i
    if ai < 24:
        n = ai
    elif ai in (24, 25, 26, 27):
        size = 1 << (ai - 24)
        n = int.from_bytes(b[i:i + size], "big")
        i += size
    else:
        raise ValueError("unsupported CBOR item")
    if mt == 0:
        return n, i
    if mt == 1:
        return -1 - n, i
    if mt == 2:
        return b[i:i + n], i + n
    if mt == 3:
        return b[i:i + n].decode("utf-8", "replace"), i + n
    if mt == 4:
        out = []
        for _ in range(n):
            v, i = _cbor(b, i)
            out.append(v)
        return out, i
    if mt == 5:
        out = {}
        for _ in range(n):
            k, i = _cbor(b, i)
            out[k], i = _cbor(b, i)
        return out, i
    raise ValueError("unsupported CBOR type")


def load_state(raw):
    """Plugin state bytes -> dict, or None if this isn't readable Serum 2 state."""
    if zstd is None or not raw.startswith(b"XferJson"):
        return None
    at = raw.find(ZSTD_MAGIC)
    if at < 0:
        return None
    try:
        data, _ = _cbor(zstd.decompress(raw[at:]))
    except (ValueError, IndexError, zstd.ZstdError):
        return None
    return data if isinstance(data, dict) else None


def _params(section):
    p = section.get("plainParams") if isinstance(section, dict) else None
    return p if isinstance(p, dict) else {}


def summary(raw):
    """One line describing the patch, e.g.
    'poly wavetable · Osc A Basic_Cjw (x4 unison), Osc B BottleBlow · filter · FX: EQ, Compressor'."""
    d = load_state(raw)
    if d is None:
        return None
    parts = []
    tags = [t.lower() for t in d.get("tags", []) if isinstance(t, str)]
    if tags:
        parts.append(" ".join(reversed(tags)))

    oscs, from_scratch = [], True
    for n, letter in enumerate("ABC"):
        osc = d.get(f"Oscillator{n}", {})
        p = _params(osc)
        enabled = p.get("kParamEnable", 1.0 if n == 0 else 0.0) >= 0.5
        if not enabled:
            continue
        wt = osc.get(f"WTOsc{n}", {})
        table = PurePosixPath(str(wt.get("relativePathToWT", ""))).stem
        if not table:
            # Not a wavetable oscillator: name the engine that holds a sample, if any.
            engine = next((k[:-1] for k, v in osc.items() if k.endswith(str(n)) and isinstance(v, dict)
                           and any("Path" in kk for kk in v)), None)
            table = {"GranularOsc": "granular", "SampleOsc": "sample", "MultiSampleOsc": "multisample",
                     "SpectralOsc": "spectral"}.get(engine, "non-wavetable")
        if table != DEFAULT_TABLE:
            from_scratch = False
        unison = int(p.get("kParamUnison", 1))
        oscs.append(f"Osc {letter} {table}" + (f" (x{unison} unison)" if unison > 1 else ""))
    for n, label in ((3, "noise"), (4, "sub")):
        if _params(d.get(f"Oscillator{n}", {})).get("kParamEnable", 0) >= 0.5:
            oscs.append(label)
    if oscs:
        parts.append(", ".join(oscs))

    if _params(d.get("VoiceFilter0", {})).get("kParamEnable", 0) >= 0.5:
        parts.append("filter")
    fx = []
    for r in range(3):
        for slot in d.get(f"FXRack{r}", {}).get("FX", []) or []:
            for key in slot:
                if key.startswith("FX"):
                    fx.append(FX_NAMES.get(key, key[2:]))
    if fx:
        parts.append("FX: " + ", ".join(fx))
        from_scratch = False
    if _params(d.get("Global0", {})).get("kParamPortamentoTime", 0) > 0.001:
        parts.append("glide")
    if from_scratch:
        parts.append("default wavetables, likely built from Init")
    return " · ".join(parts)
