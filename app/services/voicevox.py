"""Client for a local VOICEVOX engine (https://voicevox.hiroshiba.jp/).

Generates `ExpressionAudio`: a clean, isolated TTS pronunciation of the
headword, as distinct from `SentenceAudio` (clipped from the source video,
see clip.py) which is naturally co-articulated with surrounding speech.

VOICEVOX must be installed and *running* (the app itself, not just
installed) for its local HTTP API to respond -- same relationship Anki has
with AnkiConnect.
"""

import httpx

from app.config import VOICEVOX_SPEAKER, VOICEVOX_URL


class VoicevoxError(Exception):
    pass


async def is_connected() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{VOICEVOX_URL}/version")
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


async def list_speakers() -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{VOICEVOX_URL}/speakers")
    resp.raise_for_status()
    return resp.json()


async def list_speaker_ids() -> list[int]:
    """Every installed (character, style) id, flattened -- e.g. both
    四国めたん's ノーマル and ツンツン styles are distinct ids here."""
    speakers = await list_speakers()
    return [style["id"] for sp in speakers for style in sp["styles"]]


async def synthesize(text: str, speaker: int = VOICEVOX_SPEAKER) -> bytes:
    """Returns WAV audio bytes for `text` spoken by `speaker`."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            query_resp = await client.post(
                f"{VOICEVOX_URL}/audio_query",
                params={"text": text, "speaker": speaker},
            )
            query_resp.raise_for_status()
            synth_resp = await client.post(
                f"{VOICEVOX_URL}/synthesis",
                params={"speaker": speaker},
                json=query_resp.json(),
            )
            synth_resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise VoicevoxError(
            f"VOICEVOX request failed for {text!r}: {exc}. Is the VOICEVOX "
            f"app running (not just installed)?"
        ) from exc
    return synth_resp.content
