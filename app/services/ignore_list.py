"""Persisted list of headwords permanently excluded from every future scan
(SPEC.md §4, "Ignore list"). A flat YAML file, not a database -- it's a
set of strings checked for membership, nothing more; see the file's own
comment and the discussion in SPEC.md §3 on avoiding infra this tool
doesn't need.
"""

import yaml

from app.config import IGNORED_WORDS_PATH


def load_ignored() -> set[str]:
    if not IGNORED_WORDS_PATH.exists():
        return set()
    with open(IGNORED_WORDS_PATH) as f:
        data = yaml.safe_load(f) or {}
    return set(data.get("ignored_words", []))


def _save(words: set[str]) -> None:
    with open(IGNORED_WORDS_PATH, "w") as f:
        yaml.safe_dump(
            {"ignored_words": sorted(words)}, f, allow_unicode=True
        )


def add_ignored(word: str) -> None:
    words = load_ignored()
    words.add(word)
    _save(words)


def remove_ignored(word: str) -> None:
    words = load_ignored()
    words.discard(word)
    _save(words)
