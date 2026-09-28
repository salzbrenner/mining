"""Missing-field audit (SPEC.md §4, "Audit")."""

from dataclasses import dataclass, field

import yaml

from app import anki
from app.config import REQUIRED_FIELDS_PATH, TARGET_DECK


def load_required_fields() -> list[str]:
    with open(REQUIRED_FIELDS_PATH) as f:
        data = yaml.safe_load(f) or {}
    return data.get("required_fields", [])


def save_required_fields(fields: list[str]) -> None:
    with open(REQUIRED_FIELDS_PATH, "w") as f:
        yaml.safe_dump({"required_fields": fields}, f, allow_unicode=True)


@dataclass
class IncompleteNote:
    note_id: int
    expression: str
    missing: list[str]


@dataclass
class AuditReport:
    total_notes: int
    complete: int
    incomplete: int
    required_fields: list[str]
    per_field_counts: dict[str, int]
    notes: list[IncompleteNote] = field(default_factory=list)


async def run_audit() -> AuditReport:
    required = load_required_fields()
    note_ids = await anki.find_notes(f'deck:"{TARGET_DECK}"')
    notes = await anki.notes_info(note_ids)

    per_field_counts = {f: 0 for f in required}
    incomplete: list[IncompleteNote] = []

    for note in notes:
        missing = [
            f
            for f in required
            if not note["fields"].get(f, {}).get("value", "").strip()
        ]
        if missing:
            expr = note["fields"].get("Expression", {}).get("value", "")
            incomplete.append(
                IncompleteNote(note_id=note["noteId"], expression=expr, missing=missing)
            )
            for f in missing:
                per_field_counts[f] += 1

    return AuditReport(
        total_notes=len(notes),
        complete=len(notes) - len(incomplete),
        incomplete=len(incomplete),
        required_fields=required,
        per_field_counts=per_field_counts,
        notes=incomplete,
    )
