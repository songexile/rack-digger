"""Find the user's Ableton Live User Library."""
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ENV_VAR = "RACKDIGGER_USER_LIBRARY"
OUTPUT_FOLDER = "Rack Digger"


def _version_key(path):
    """'Live 12.1.5' -> (12, 1, 5) so the newest install sorts last."""
    return tuple(int(n) for n in re.findall(r"\d+", path.parent.parent.name))


def library_cfgs():
    """Every Library.cfg Live has written, newest Live version first."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    cfgs = Path(appdata, "Ableton").glob("Live */Preferences/Library.cfg")
    return sorted(cfgs, key=_version_key, reverse=True)


def user_library_from_cfg(cfg):
    node = ET.parse(cfg).getroot().find("ContentLibrary/UserLibrary/LibraryProject/ProjectPath")
    if node is None or not node.get("Value"):
        return None
    return Path(node.get("Value")) / "User Library"


def find_user_library():
    """Return (path, how it was found). Path is None if nothing exists."""
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override), f"from the {ENV_VAR} environment variable"
    for cfg in library_cfgs():
        try:
            lib = user_library_from_cfg(cfg)
        except ET.ParseError:
            continue
        if lib and lib.is_dir():
            return lib, f"from {cfg}"
    default = Path.home() / "Documents" / "Ableton" / "User Library"
    if default.is_dir():
        return default, "Live's default location"
    return None, "not found"


def output_root(user_library):
    return Path(user_library) / OUTPUT_FOLDER
