"""Loads the Yomitan-format dictionary zips (SPEC.md §5) into memory.

Parsed once per process and cached -- this is static reference data (the
JMdict term bank and the CC-100 frequency bank), not live Anki state, so
there's no staleness concern the way there would be for note data (see
SPEC.md §3 on why there's no cache for that).
"""

import html as html_lib
import json
import zipfile
from functools import lru_cache

from app.config import DICTIONARIES_DIR


def _zip_kind(zip_path) -> str | None:
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if any(n.startswith("term_bank_") for n in names):
            return "term"
        if any(n.startswith("term_meta_bank_") for n in names):
            return "freq"
    return None


def _dictionary_zips() -> list:
    if not DICTIONARIES_DIR.exists():
        return []
    return sorted(DICTIONARIES_DIR.glob("*.zip"))


def dictionaries_ready() -> bool:
    """Ready once at least one JMdict-style term dictionary and one
    frequency dictionary are both present."""
    kinds = {_zip_kind(p) for p in _dictionary_zips()}
    return "term" in kinds and "freq" in kinds


@lru_cache(maxsize=1)
def _load_term_data() -> tuple[set[str], dict[str, list]]:
    """One pass over the JMdict term bank producing both the headword set
    (§7's longest-match scan) and each term's raw glossary blocks (one per
    JMdict sense, used by render_main_definition below) -- built together
    to avoid parsing the ~180MB term bank twice.
    """
    headwords: set[str] = set()
    glossaries: dict[str, list] = {}
    for zip_path in _dictionary_zips():
        if _zip_kind(zip_path) != "term":
            continue
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if not name.startswith("term_bank_"):
                    continue
                for entry in json.load(z.open(name)):
                    term, glossary = entry[0], entry[5]
                    headwords.add(term)
                    glossaries.setdefault(term, []).append(glossary)
    return headwords, glossaries


def load_term_headwords() -> set[str]:
    """The set of real JMdict headwords -- used by §7's longest-match scan
    to decide whether a candidate span is a real dictionary entry. Readings
    are *not* taken from here (see matcher.py) since JMdict often has
    multiple entries sharing a term with different readings/meanings, and
    picking "whichever came first in the file" produced wrong readings in
    testing (e.g. 僕 -> しもべ instead of ぼく) -- SudachiPy's own contextual
    reading_form() is used instead.
    """
    return _load_term_data()[0]


def _render_node(node) -> str:
    if isinstance(node, str):
        return html_lib.escape(node)
    if isinstance(node, list):
        return "".join(_render_node(n) for n in node)
    if isinstance(node, dict):
        # Skip JMdict's own example-sentence blocks -- Sentence already
        # holds a real, video-sourced example; a second one here is just
        # clutter, not missing information.
        if node.get("data", {}).get("content") == "examples":
            return ""
        tag = node.get("tag")
        inner = _render_node(node.get("content", ""))
        if not tag:
            return inner
        if tag == "a" and "href" in node:
            return f'<a href="{html_lib.escape(node["href"])}">{inner}</a>'
        return f"<{tag}>{inner}</{tag}>"
    return ""


def render_main_definition(term: str) -> str:
    """Renders every JMdict sense for `term` into HTML for MainDefinition,
    e.g. 起きる's 3 real senses (get up/rise, wake up/be awake, occur/happen)
    each become one <li> of an ordered list.
    """
    _, glossaries = _load_term_data()
    items = []
    for glossary in glossaries.get(term, []):
        rendered = _render_node(glossary)
        if rendered:
            items.append(f"<li>{rendered}</li>")
    if not items:
        return ""
    return f"<ol>{''.join(items)}</ol>"


@lru_cache(maxsize=1)
def load_frequencies() -> dict[str, int]:
    """Term -> best (lowest/most common) CC-100 frequency rank."""
    freqs: dict[str, int] = {}
    for zip_path in _dictionary_zips():
        if _zip_kind(zip_path) != "freq":
            continue
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if not name.startswith("term_meta_bank_"):
                    continue
                for term, mode, data in json.load(z.open(name)):
                    if mode != "freq":
                        continue
                    value = data["frequency"] if isinstance(data, dict) else data
                    if not isinstance(value, int):
                        continue
                    if term not in freqs or value < freqs[term]:
                        freqs[term] = value
    return freqs
