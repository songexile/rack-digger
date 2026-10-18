"""Find a song by name: look for '<name> Project' folders under the user's song folders."""
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .library import library_cfgs
from .scan import is_live_set

# Folders that never hold projects worth descending into.
SKIP_DIRS = {"Backup", "Samples", "Ableton Project Info", "Recorded", "Processed", "Imported", "Consolidated",
             "Freeze", ".git", "node_modules", "$RECYCLE.BIN", "System Volume Information"}


def config_path():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "rackdigger" / "config.json"


def load_config():
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_song_folders(folders):
    cfg = load_config()
    cfg["songs"] = [str(Path(f).resolve()) for f in folders]
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(cfg, indent=1), encoding="utf-8")


def places_folders():
    """Folders added under Places in Live's browser (Live keeps them in Library.cfg)."""
    for cfg in library_cfgs():
        try:
            root = ET.parse(cfg).getroot()
        except ET.ParseError:
            continue
        folders = [Path(f.get("Path")) for f in root.iter("UserFolderInfo") if f.get("Path")]
        return [f for f in folders if f.is_dir()]
    return []


def song_folders():
    """(folders to search, where they came from)."""
    saved = [Path(f) for f in load_config().get("songs", []) if Path(f).is_dir()]
    if saved:
        return saved, "your saved song folders"
    places = places_folders()
    if places:
        return places, "your Places folders in Live's browser"
    return [], "nothing set"


def _norm(s):
    return re.sub(r"[\s_\-.]+", "", s.lower())


def find_projects(name, folders=None):
    """Project folders whose name contains `name` (ignoring case, spaces, _ and -), best match first.
    Each result: (project folder, newest .als, number of saved versions)."""
    folders = folders if folders is not None else song_folders()[0]
    # Don't walk a folder twice when it sits inside another one we're already walking.
    resolved = [Path(f).resolve() for f in folders]
    folders = [f for f in resolved if not any(o != f and o in f.parents for o in resolved)]
    want = _norm(name.removesuffix(" Project"))
    hits, seen = [], set()
    for root in folders:
        for dirpath, dirnames, _ in os.walk(root):
            keep = []
            for d in dirnames:
                if d in SKIP_DIRS or d.startswith("."):
                    continue
                if d.endswith(" Project"):
                    project = Path(dirpath, d)
                    key = _norm(d.removesuffix(" Project"))
                    if want in key and project not in seen:
                        seen.add(project)
                        sets = [a for a in project.glob("*.als") if is_live_set(a)]
                        if sets:
                            newest = max(sets, key=lambda a: a.stat().st_mtime)
                            hits.append((0 if key == want else 1, -newest.stat().st_mtime, project, newest, len(sets)))
                    continue  # never descend into a project
                keep.append(d)
            dirnames[:] = keep
    hits.sort(key=lambda h: (h[0], h[1]))
    return [(p, als, n) for _, _, p, als, n in hits]
