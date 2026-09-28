"""Field-mapped importer from any deck into Mining (SPEC.md §4, "Import").

Dedup here is a simple exact-match on the mapped Expression value against
Mining's existing Expression set -- a known inconsistency with the
dictionary-headword matcher (SPEC.md §5) the SRT scanner uses; see
SPEC.md §8.2.
"""

from dataclasses import dataclass, field as dc_field

from app import anki
from app.config import NOTE_TYPE, TARGET_DECK


class InvalidDeckError(Exception):
    """deck_name isn't one of Anki's real deck names.

    The UI's dropdown only ever offers real deck names, but the HTTP
    endpoints behind it accept deck_name as a plain client-submitted
    string with no server-side check -- and it gets interpolated directly
    into an AnkiConnect search query (f'deck:"{deck_name}"') with no
    escaping. A deck_name containing a literal quote can break out of the
    intended deck: term and inject arbitrary Anki search syntax (e.g.
    'Mining" OR deck:*' matches every deck, not just the one selected).
    Validating against the real deck list closes that off.
    """


async def _validate_deck_name(deck_name: str) -> None:
    real_decks = await anki.deck_names()
    if deck_name not in real_decks:
        raise InvalidDeckError(f"{deck_name!r} is not a real Anki deck.")


@dataclass
class SourceDeckInfo:
    deck_name: str
    model_name: str | None
    fields: list[str]
    note_count: int
    mixed_note_types: bool = False


async def get_source_deck_info(deck_name: str) -> SourceDeckInfo:
    await _validate_deck_name(deck_name)
    note_ids = await anki.find_notes(f'deck:"{deck_name}"')
    if not note_ids:
        return SourceDeckInfo(
            deck_name=deck_name, model_name=None, fields=[], note_count=0
        )
    sample = await anki.notes_info(note_ids[:50])
    model_names = {n["modelName"] for n in sample}
    model_name = sample[0]["modelName"]
    fields = await anki.model_field_names(model_name)
    return SourceDeckInfo(
        deck_name=deck_name,
        model_name=model_name,
        fields=fields,
        note_count=len(note_ids),
        mixed_note_types=len(model_names) > 1,
    )


async def get_target_fields() -> list[str]:
    return await anki.model_field_names(NOTE_TYPE)


@dataclass
class ImportResult:
    imported: int
    skipped_existing: int
    failed: int
    failed_expressions: list[str] = dc_field(default_factory=list)


async def run_import(
    deck_name: str, model_name: str, field_map: dict[str, str]
) -> ImportResult:
    """field_map: source_field -> target Lapis field, empty/missing = skip."""
    await _validate_deck_name(deck_name)
    note_ids = await anki.find_notes(f'deck:"{deck_name}"')
    source_notes = await anki.notes_info(note_ids)
    source_notes = [n for n in source_notes if n["modelName"] == model_name]

    target_ids = await anki.find_notes(f'deck:"{TARGET_DECK}"')
    target_notes = await anki.notes_info(target_ids)
    existing_expressions = {
        n["fields"]["Expression"]["value"]
        for n in target_notes
        if "Expression" in n["fields"]
    }

    to_create = []
    source_expressions = []
    skipped = 0
    for note in source_notes:
        fields = {}
        for src_field, tgt_field in field_map.items():
            if not tgt_field:
                continue
            fields[tgt_field] = note["fields"].get(src_field, {}).get("value", "")
        expr = fields.get("Expression", "")
        if not expr or expr in existing_expressions:
            skipped += 1
            continue
        to_create.append({"fields": fields, "tags": note.get("tags", [])})
        source_expressions.append(expr)
        existing_expressions.add(expr)  # dedup within this batch too

    if not to_create:
        return ImportResult(imported=0, skipped_existing=skipped, failed=0)

    # allowDuplicate stays False here (unlike the Phase 0 clone) -- normal
    # imports keep AnkiConnect's own duplicate check on as a safety net.
    result_ids = await anki.add_notes(
        TARGET_DECK, NOTE_TYPE, to_create, allow_duplicate=False
    )
    imported = sum(1 for r in result_ids if r is not None)
    failed_expressions = [
        source_expressions[i] for i, r in enumerate(result_ids) if r is None
    ]
    return ImportResult(
        imported=imported,
        skipped_existing=skipped,
        failed=len(failed_expressions),
        failed_expressions=failed_expressions,
    )
