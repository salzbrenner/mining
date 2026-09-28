"""Persisted list of VOICEVOX speaker/style ids permanently excluded from
the random-voice picker used during audio backfill -- a flat YAML file,
same pattern as ignore_list.py (a set of ids, not a database).
"""

import yaml

from app.config import EXCLUDED_VOICES_PATH


def load_excluded() -> set[int]:
    if not EXCLUDED_VOICES_PATH.exists():
        return set()
    with open(EXCLUDED_VOICES_PATH) as f:
        data = yaml.safe_load(f) or {}
    return set(data.get("excluded_speaker_ids", []))


def _save(ids: set[int]) -> None:
    with open(EXCLUDED_VOICES_PATH, "w") as f:
        yaml.safe_dump({"excluded_speaker_ids": sorted(ids)}, f)


def add_excluded(speaker_id: int) -> None:
    ids = load_excluded()
    ids.add(speaker_id)
    _save(ids)


def remove_excluded(speaker_id: int) -> None:
    ids = load_excluded()
    ids.discard(speaker_id)
    _save(ids)
