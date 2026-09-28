"""Bulk-populates missing `ExpressionAudio`/`SentenceAudio` via VOICEVOX TTS
for existing Mining notes -- the "field population method" for those two
fields specifically (SPEC.md §4, "Audit"). Unlike the SRT scanner's
per-video SentenceAudio (clipped from the real source audio), this always
synthesizes straight from the note's own Expression/Sentence text, since a
note reached via the audit may have no associated source video at all
(notes that predate this tool, the field-mapped importer, etc.).

A random VOICEVOX voice is picked per note (used for both fields on that
note, so the "speaker" is at least consistent within one card) for variety
across the deck, rather than always the one fixed default voice.

Only ever touches fields that are genuinely empty -- never overwrites real
audio a note already has (e.g. the original Mining notes' Yomitan-sourced
recordings).

Processed in caller-controlled batches (see `limit`), not all at once: with
potentially hundreds of notes missing these fields, one VOICEVOX call per
field per note adds up to longer than a single request should reasonably
block on with no progress feedback.
"""

import base64
import random
import re
from dataclasses import dataclass

from app import anki
from app.config import TARGET_DECK
from app.services import voice_exclusions
from app.services import voicevox as voicevox_service

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Field values can contain real HTML (e.g. `<b>` around the target
    word in Sentence, for on-card display) -- found the hard way: sent
    straight to VOICEVOX, it tries to pronounce the literal tag text.
    """
    return _TAG_RE.sub("", text)


@dataclass
class MissingAudioCounts:
    missing_expression_audio: int
    missing_sentence_audio: int


async def count_missing() -> MissingAudioCounts:
    note_ids = await anki.find_notes(f'deck:"{TARGET_DECK}"')
    notes = await anki.notes_info(note_ids)
    missing_expr = sum(
        1
        for n in notes
        if not n["fields"].get("ExpressionAudio", {}).get("value", "").strip()
        and n["fields"].get("Expression", {}).get("value", "").strip()
    )
    missing_sentence = sum(
        1
        for n in notes
        if not n["fields"].get("SentenceAudio", {}).get("value", "").strip()
        and n["fields"].get("Sentence", {}).get("value", "").strip()
    )
    return MissingAudioCounts(
        missing_expression_audio=missing_expr, missing_sentence_audio=missing_sentence
    )


async def _synthesize_and_store(text: str, speaker: int, filename: str) -> str | None:
    try:
        wav_bytes = await voicevox_service.synthesize(text, speaker=speaker)
    except voicevox_service.VoicevoxError:
        return None
    await anki.store_media_file(filename, base64.b64encode(wav_bytes).decode("ascii"))
    return filename


@dataclass
class BackfillResult:
    expression_audio_added: int
    sentence_audio_added: int
    failed: int
    remaining: MissingAudioCounts


async def run_backfill(limit: int = 30) -> BackfillResult:
    note_ids = await anki.find_notes(f'deck:"{TARGET_DECK}"')
    notes = await anki.notes_info(note_ids)
    excluded = voice_exclusions.load_excluded()
    speaker_ids = [
        s for s in await voicevox_service.list_speaker_ids() if s not in excluded
    ]
    if not speaker_ids:
        # Everything got excluded somehow -- fall back to the full list
        # rather than crash the whole batch on random.choice([]).
        speaker_ids = await voicevox_service.list_speaker_ids()

    expr_added = 0
    sentence_added = 0
    failed = 0
    processed = 0

    for note in notes:
        if processed >= limit:
            break

        expression = _strip_html(
            note["fields"].get("Expression", {}).get("value", "")
        ).strip()
        sentence = _strip_html(
            note["fields"].get("Sentence", {}).get("value", "")
        ).strip()
        needs_expr = (
            expression
            and not note["fields"].get("ExpressionAudio", {}).get("value", "").strip()
        )
        needs_sentence = (
            sentence
            and not note["fields"].get("SentenceAudio", {}).get("value", "").strip()
        )
        if not needs_expr and not needs_sentence:
            continue

        note_id = note["noteId"]
        speaker = random.choice(speaker_ids)
        updates = {}

        if needs_expr:
            filename = await _synthesize_and_store(
                expression, speaker, f"mining2_expr_bf_{note_id}.wav"
            )
            if filename:
                updates["ExpressionAudio"] = f"[sound:{filename}]"
                expr_added += 1
            else:
                failed += 1

        if needs_sentence:
            filename = await _synthesize_and_store(
                sentence, speaker, f"mining2_sentence_bf_{note_id}.wav"
            )
            if filename:
                updates["SentenceAudio"] = f"[sound:{filename}]"
                sentence_added += 1
            else:
                failed += 1

        if updates:
            await anki.update_note_fields(note_id, updates)
        processed += 1

    remaining = await count_missing()
    return BackfillResult(
        expression_audio_added=expr_added,
        sentence_audio_added=sentence_added,
        failed=failed,
        remaining=remaining,
    )
