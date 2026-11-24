"""Server-side edits to the APK's game configs.

The server reads the edited configs itself, and `loading` reports a new version for each
edited one, so the client downloads it through `all_config` (game_resources_download2
startCfg) and both sides apply the same rules without reinstalling the APK.

The only edit opens the whole normal campaign: every normal (not elite) chapter and city
opens at player level 1. The world map (map_world_scene) hides a chapter and greys out a
city by comparing the player level with `open_level`, so the edit has to reach the client.
"""

import hashlib
import json

OPEN_LEVEL = 1


def _normal_chapters(chapter: dict) -> set:
    return {key for key, row in chapter.items()
            if isinstance(row, dict) and row.get("is_hard") == 0}


def _open_rows(rows: dict, is_normal) -> dict:
    return {key: {**row, "open_level": OPEN_LEVEL}
            if isinstance(row, dict) and is_normal(row) else row
            for key, row in rows.items()}


def _chapter(raw: dict, get) -> dict:
    """Normal chapters first, in number order. The chapter picker (game_chapter_pop) draws
    cell i from the sorted normal list but its tap handler reads chapter:getNodeAt(i), the
    i-th key of the file ("1", "10", "101", ...), so any other order opens the wrong chapter
    or none."""
    normal = sorted(_normal_chapters(raw), key=int)
    ordered = {key: raw[key] for key in normal} | {k: v for k, v in raw.items() if k not in normal}
    return _open_rows(ordered, lambda row: row.get("is_hard") == 0)


def _map_main_story(raw: dict, get) -> dict:
    normal = _normal_chapters(get("chapter"))
    return _open_rows(raw, lambda row: str(row.get("chapter")) in normal)


# config name -> (raw config, get(name) for other configs) -> edited config
EDITS = {"chapter": _chapter, "map_main_story": _map_main_story}


def apply(name: str, raw: dict, get) -> dict:
    edit = EDITS.get(name)
    return edit(raw, get) if edit else raw


def version(document: dict) -> str:
    """A version for an edited config; any value other than the APK's makes the client
    download it."""
    # Key order is part of the content: the client reads some configs by position.
    canonical = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def version_map(apk_versions: dict, configs) -> dict:
    """The APK's version map with a new version for every config an edit changed."""
    versions = dict(apk_versions)
    for name in EDITS:
        if name in versions and configs.get(name) != configs.raw(name):
            versions[name] = version(configs.get(name))
    return versions
