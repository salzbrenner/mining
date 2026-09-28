"""Thin async wrapper around the AnkiConnect HTTP API.

No caching here (see SPEC.md §3) — every call goes straight to
AnkiConnect, which requires Anki desktop to be running with the AnkiConnect
add-on installed.
"""

import httpx

from app.config import ANKI_CONNECT_URL, ANKI_CONNECT_VERSION

NOTES_INFO_BATCH_SIZE = 500


class AnkiConnectError(Exception):
    """Raised for both transport failures and AnkiConnect-reported errors."""


async def invoke(action: str, **params):
    payload = {"action": action, "version": ANKI_CONNECT_VERSION}
    if params:
        payload["params"] = params
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(ANKI_CONNECT_URL, json=payload)
    except httpx.ConnectError as exc:
        raise AnkiConnectError(
            "Can't reach AnkiConnect at "
            f"{ANKI_CONNECT_URL}. Is Anki running with the AnkiConnect add-on?"
        ) from exc
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or set(data.keys()) != {"result", "error"}:
        raise AnkiConnectError(f"Unexpected AnkiConnect response shape: {data!r}")
    if data["error"] is not None:
        raise AnkiConnectError(data["error"])
    return data["result"]


async def deck_names() -> list[str]:
    return await invoke("deckNames")


async def create_deck(name: str) -> int:
    return await invoke("createDeck", deck=name)


async def model_names() -> list[str]:
    return await invoke("modelNames")


async def model_field_names(model_name: str) -> list[str]:
    return await invoke("modelFieldNames", modelName=model_name)


async def find_notes(query: str) -> list[int]:
    return await invoke("findNotes", query=query)


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def notes_info(note_ids: list[int]) -> list[dict]:
    """notesInfo, chunked to avoid one giant request for large decks.

    Note: AnkiConnect always returns every field's full value (no partial
    field selection), so this doesn't reduce payload size per note — only
    the number of notes per request, to keep individual calls bounded.
    """
    results: list[dict] = []
    for chunk in _chunks(note_ids, NOTES_INFO_BATCH_SIZE):
        results.extend(await invoke("notesInfo", notes=chunk))
    return results


async def add_note(
    deck_name: str,
    model_name: str,
    fields: dict[str, str],
    tags: list[str] | None = None,
    allow_duplicate: bool = False,
) -> int | None:
    note = {
        "deckName": deck_name,
        "modelName": model_name,
        "fields": fields,
        "tags": tags or [],
        "options": {"allowDuplicate": allow_duplicate},
    }
    return await invoke("addNote", note=note)


async def add_notes(
    deck_name: str,
    model_name: str,
    notes: list[dict],
    allow_duplicate: bool = False,
) -> list[int | None]:
    """Batch note creation. `notes` is a list of {"fields": ..., "tags": ...}."""
    payload = []
    for n in notes:
        payload.append(
            {
                "deckName": deck_name,
                "modelName": model_name,
                "fields": n["fields"],
                "tags": n.get("tags", []),
                "options": {"allowDuplicate": allow_duplicate},
            }
        )
    return await invoke("addNotes", notes=payload)


async def update_note_fields(note_id: int, fields: dict[str, str]) -> None:
    await invoke("updateNoteFields", note={"id": note_id, "fields": fields})


async def delete_notes(note_ids: list[int]) -> None:
    for chunk in _chunks(note_ids, NOTES_INFO_BATCH_SIZE):
        await invoke("deleteNotes", notes=chunk)


async def export_package(deck_name: str, path: str, include_sched: bool = True) -> None:
    """Exports a deck to a self-contained .apkg (notes, media, and --
    with include_sched=True -- full scheduling/review history), the same
    format Anki itself uses for backups and File > Import."""
    await invoke(
        "exportPackage", deck=deck_name, path=path, includeSched=include_sched
    )


async def store_media_file(filename: str, data_b64: str) -> str:
    return await invoke("storeMediaFile", filename=filename, data=data_b64)


async def gui_browse(query: str) -> list[int]:
    return await invoke("guiBrowse", query=query)


async def is_connected() -> bool:
    try:
        await invoke("version")
        return True
    except AnkiConnectError:
        return False
