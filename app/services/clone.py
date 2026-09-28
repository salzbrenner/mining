"""Phase 0 — clone Mining -> Mining 2 (SPEC.md §5 Phase 0)."""

from dataclasses import dataclass, field

from app import anki
from app.config import NOTE_TYPE, SOURCE_DECK, TARGET_DECK


@dataclass
class CloneStatus:
    source_count: int
    target_count: int
    target_deck_exists: bool


async def get_status() -> CloneStatus:
    decks = await anki.deck_names()
    target_exists = TARGET_DECK in decks
    source_ids = await anki.find_notes(f'deck:"{SOURCE_DECK}"')
    target_ids = await anki.find_notes(f'deck:"{TARGET_DECK}"') if target_exists else []
    return CloneStatus(
        source_count=len(source_ids),
        target_count=len(target_ids),
        target_deck_exists=target_exists,
    )


@dataclass
class CloneResult:
    cloned: int
    skipped_existing: int
    failed: int
    failed_expressions: list[str] = field(default_factory=list)


async def _clone_between(
    source_deck: str, target_deck: str, allow_duplicate: bool
) -> CloneResult:
    source_ids = await anki.find_notes(f'deck:"{source_deck}"')
    source_notes = await anki.notes_info(source_ids)

    target_ids = await anki.find_notes(f'deck:"{target_deck}"')
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
        expr = note["fields"].get("Expression", {}).get("value", "")
        if expr in existing_expressions:
            skipped += 1
            continue
        fields = {name: f["value"] for name, f in note["fields"].items()}
        to_create.append({"fields": fields, "tags": note.get("tags", [])})
        source_expressions.append(expr)

    if not to_create:
        return CloneResult(cloned=0, skipped_existing=skipped, failed=0)

    result_ids = await anki.add_notes(
        target_deck, NOTE_TYPE, to_create, allow_duplicate=allow_duplicate
    )
    cloned = sum(1 for r in result_ids if r is not None)
    failed_expressions = [
        source_expressions[i] for i, r in enumerate(result_ids) if r is None
    ]
    return CloneResult(
        cloned=cloned,
        skipped_existing=skipped,
        failed=len(failed_expressions),
        failed_expressions=failed_expressions,
    )


async def run_clone() -> CloneResult:
    """Copy every note from Mining into Mining 2.

    Idempotent by Expression: notes whose Expression value already exists in
    Mining 2 are skipped, so re-running after adding new cards to the
    original Mining deck only clones what's new. Uses allowDuplicate=True
    because every clone is an intentional duplicate by design (see
    SPEC.md §5 Phase 0) -- this is the only place in the app that does.
    """
    await anki.create_deck(TARGET_DECK)
    return await _clone_between(SOURCE_DECK, TARGET_DECK, allow_duplicate=True)


@dataclass
class PromoteResult:
    added: int
    updated: int
    unchanged: int
    failed: int
    failed_expressions: list[str] = field(default_factory=list)


async def run_reverse_clone() -> PromoteResult:
    """"Promote" Mining 2 into Mining:

    - Notes whose Expression doesn't exist in Mining yet get added as new
      cards (newly-developed cards -- SRT scans, imports, etc. -- becoming
      real study material).
    - Notes that *do* already exist get gap-filled: any field that's empty
      on the Mining note but populated on the Mining 2 note is copied over
      (e.g. audio/definitions/furigana backfilled onto Mining 2's copy of
      an originally-cloned note). Fields Mining already has content for are
      never touched or overwritten -- same safety principle as the audio
      backfill: only ever fill gaps, never clobber existing content.

    Mining 2 is left untouched either way -- it keeps serving as a running
    record of everything ever added, not a one-shot staging buffer.

    allowDuplicate=True for the add path, same reasoning as the forward
    clone despite the direction being different: Anki's own duplicate check
    is scoped by note type across the *whole collection*, not by deck --
    found the hard way, addNotes threw a hard error (not a graceful per-note
    null) the moment any note being promoted still existed in Mining 2, its
    source, which is every single one by design. Our own Expression-based
    logic here is the real dedup/merge logic; Anki's blanket check is
    fundamentally incompatible with any intentional cross-deck copy of the
    same note type and has to be bypassed.
    """
    source_ids = await anki.find_notes(f'deck:"{TARGET_DECK}"')
    source_notes = await anki.notes_info(source_ids)

    target_ids = await anki.find_notes(f'deck:"{SOURCE_DECK}"')
    target_notes = await anki.notes_info(target_ids)
    target_by_expression = {
        n["fields"]["Expression"]["value"]: n
        for n in target_notes
        if "Expression" in n["fields"]
    }

    to_create = []
    create_expressions = []
    updated = 0
    unchanged = 0
    for note in source_notes:
        expr = note["fields"].get("Expression", {}).get("value", "")
        if not expr:
            continue
        existing = target_by_expression.get(expr)
        if existing is None:
            fields = {name: f["value"] for name, f in note["fields"].items()}
            to_create.append({"fields": fields, "tags": note.get("tags", [])})
            create_expressions.append(expr)
            continue

        gap_fields = {
            name: f["value"]
            for name, f in note["fields"].items()
            if f["value"] and not existing["fields"].get(name, {}).get("value", "").strip()
        }
        if gap_fields:
            await anki.update_note_fields(existing["noteId"], gap_fields)
            updated += 1
        else:
            unchanged += 1

    added = 0
    failed_expressions = []
    if to_create:
        result_ids = await anki.add_notes(
            SOURCE_DECK, NOTE_TYPE, to_create, allow_duplicate=True
        )
        added = sum(1 for r in result_ids if r is not None)
        failed_expressions = [
            create_expressions[i] for i, r in enumerate(result_ids) if r is None
        ]

    return PromoteResult(
        added=added,
        updated=updated,
        unchanged=unchanged,
        failed=len(failed_expressions),
        failed_expressions=failed_expressions,
    )


@dataclass
class ClearAndRecloneResult:
    deleted: int
    clone_result: CloneResult


async def clear_and_reclone() -> ClearAndRecloneResult:
    """Deletes every note in Mining 2, then re-clones fresh from Mining.

    Mining itself is never touched -- this only resets Mining 2. Local tool
    preferences (ignored_words.yaml, required_fields.yaml) are left alone;
    those are preferences about the tool, not deck content.
    """
    target_ids = await anki.find_notes(f'deck:"{TARGET_DECK}"')
    if target_ids:
        await anki.delete_notes(target_ids)
    clone_result = await run_clone()
    return ClearAndRecloneResult(deleted=len(target_ids), clone_result=clone_result)
