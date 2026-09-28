"""SRT -> preview candidates -> (optional) commit to Mining
(SPEC.md §4, "Scan"). Dry-run by default -- `preview_video` never
touches Anki; only `commit_selections` writes notes, and only for whatever
was explicitly selected.

On commit, also generates ExpressionAudio (VOICEVOX TTS -- the word only
ever appears embedded in continuous natural speech in the source, so a
clean isolated pronunciation has to be synthesized, not clipped) and
SentenceAudio (clipped from the video's locally-downloaded audio.mp3 at the
SRT timestamps). Either can fail independently (e.g. VOICEVOX not running)
without blocking note creation -- the note is still created with that field
left blank, and the failure is counted in CommitResult.
"""

import base64
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app import anki
from app.config import (
    AUDIO_CLIP_PADDING_MS,
    AUDIO_CLIP_PADDING_MS_AUTO,
    NOTE_TYPE,
    TARGET_DECK,
    YOUTUBE_IMPORT_TAG,
)
from app.services import clip as clip_service
from app.services import dictionaries as dictionaries_service
from app.services import furigana as furigana_service
from app.services import ignore_list
from app.services import matcher, srt as srt_service
from app.services import voicevox as voicevox_service
from app.services import youtube as youtube_service


@dataclass
class PreviewCandidate:
    headword: str
    reading: str
    pos: str
    frequency: int | None
    sentence: str
    start_ms: int
    end_ms: int
    timestamp_seconds: int
    timestamp_label: str
    low_confidence: bool


@dataclass
class PreviewResult:
    video_id: str
    candidates: list[PreviewCandidate]
    tokens_seen: int
    tokens_filtered: int
    rare_filtered: int


async def preview_video(video_id: str) -> PreviewResult:
    meta = youtube_service.get_meta(video_id)
    srt_path = youtube_service.video_dir(video_id) / meta["srt_filename"]
    lines = srt_service.parse(srt_path)

    target_ids = await anki.find_notes(f'deck:"{TARGET_DECK}"')
    target_notes = await anki.notes_info(target_ids)
    existing_headwords = {
        n["fields"]["Expression"]["value"]
        for n in target_notes
        if "Expression" in n["fields"]
    }
    ignored = ignore_list.load_ignored()

    seen_this_scan: set[str] = set()
    candidates: list[PreviewCandidate] = []
    tokens_seen = 0
    tokens_matched = 0
    rare_filtered = 0

    for line in lines:
        result = matcher.scan_line(line.text)
        tokens_seen += result.token_count
        tokens_matched += len(result.candidates)
        rare_filtered += result.rare_filtered
        for c in result.candidates:
            if (
                c.headword in existing_headwords
                or c.headword in seen_this_scan
                or c.headword in ignored
            ):
                continue
            seen_this_scan.add(c.headword)
            candidates.append(
                PreviewCandidate(
                    headword=c.headword,
                    reading=c.reading,
                    pos=c.pos,
                    frequency=c.frequency,
                    sentence=line.text,
                    start_ms=line.start_ms,
                    end_ms=line.end_ms,
                    timestamp_seconds=line.start_seconds,
                    timestamp_label=line.timestamp_label,
                    low_confidence=c.low_confidence,
                )
            )

    return PreviewResult(
        video_id=video_id,
        candidates=candidates,
        tokens_seen=tokens_seen,
        tokens_filtered=tokens_seen - tokens_matched - rare_filtered,
        rare_filtered=rare_filtered,
    )


def _expression_audio_filename(headword: str) -> str:
    # Hashed rather than the raw word: filesystem/Anki-media-safe, and
    # doubles as free caching -- mining the same word again later (from any
    # video) reuses the identical filename/content.
    digest = hashlib.md5(headword.encode("utf-8")).hexdigest()[:12]
    return f"mining2_expr_{digest}.wav"


def _sentence_audio_filename(video_id: str, start_ms: int, end_ms: int) -> str:
    return f"mining2_sentence_{video_id}_{start_ms}_{end_ms}.mp3"


async def _make_expression_audio(headword: str) -> str | None:
    try:
        wav_bytes = await voicevox_service.synthesize(headword)
    except voicevox_service.VoicevoxError:
        return None
    filename = _expression_audio_filename(headword)
    await anki.store_media_file(filename, base64.b64encode(wav_bytes).decode("ascii"))
    return filename


async def _make_sentence_audio(
    video_id: str, audio_path: Path, start_ms: int, end_ms: int, padding_ms: int
) -> str | None:
    filename = _sentence_audio_filename(video_id, start_ms, end_ms)
    with tempfile.NamedTemporaryFile(suffix=".mp3") as tmp:
        try:
            clip_service.clip_audio(
                audio_path, start_ms, end_ms, Path(tmp.name), padding_ms=padding_ms
            )
        except clip_service.ClipError:
            return None
        data = Path(tmp.name).read_bytes()
    await anki.store_media_file(filename, base64.b64encode(data).decode("ascii"))
    return filename


@dataclass
class CommitResult:
    added: int
    skipped_existing: int
    failed: int
    expression_audio_failed: int = 0
    sentence_audio_failed: int = 0


async def commit_selections(
    video_id: str, selections: list[PreviewCandidate]
) -> CommitResult:
    meta = youtube_service.get_meta(video_id)
    audio_path = youtube_service.video_dir(video_id) / meta["audio_filename"]
    padding_ms = (
        AUDIO_CLIP_PADDING_MS_AUTO
        if meta["subtitle_kind"] == "auto"
        else AUDIO_CLIP_PADDING_MS
    )

    target_ids = await anki.find_notes(f'deck:"{TARGET_DECK}"')
    target_notes = await anki.notes_info(target_ids)
    existing_headwords = {
        n["fields"]["Expression"]["value"]
        for n in target_notes
        if "Expression" in n["fields"]
    }

    to_create = []
    skipped = 0
    expr_audio_failed = 0
    sentence_audio_failed = 0
    for c in selections:
        if c.headword in existing_headwords:
            skipped += 1
            continue

        fields = {
            "Expression": c.headword,
            "ExpressionReading": c.reading,
            "Sentence": c.sentence,
            "SentenceFurigana": furigana_service.sentence_to_furigana(c.sentence),
            "SourceVideo": meta["title"],
            "SourceTimestamp": (
                f'<a href="{youtube_service.timestamp_url(video_id, c.timestamp_seconds)}">'
                f"{c.timestamp_label}</a>"
            ),
        }
        main_definition = dictionaries_service.render_main_definition(c.headword)
        if main_definition:
            fields["MainDefinition"] = main_definition
        if c.frequency is not None:
            fields["Frequency"] = str(c.frequency)
            fields["FreqSort"] = str(c.frequency)

        expr_filename = await _make_expression_audio(c.headword)
        if expr_filename:
            fields["ExpressionAudio"] = f"[sound:{expr_filename}]"
        else:
            expr_audio_failed += 1

        sentence_filename = await _make_sentence_audio(
            video_id, audio_path, c.start_ms, c.end_ms, padding_ms
        )
        if sentence_filename:
            fields["SentenceAudio"] = f"[sound:{sentence_filename}]"
        else:
            sentence_audio_failed += 1

        to_create.append({"fields": fields, "tags": [YOUTUBE_IMPORT_TAG]})
        existing_headwords.add(c.headword)

    if not to_create:
        return CommitResult(added=0, skipped_existing=skipped, failed=0)

    result_ids = await anki.add_notes(
        TARGET_DECK, NOTE_TYPE, to_create, allow_duplicate=False
    )
    added = sum(1 for r in result_ids if r is not None)
    failed = sum(1 for r in result_ids if r is None)
    return CommitResult(
        added=added,
        skipped_existing=skipped,
        failed=failed,
        expression_audio_failed=expr_audio_failed,
        sentence_audio_failed=sentence_audio_failed,
    )
