"""Clips `SentenceAudio` out of a video's locally-downloaded audio.mp3 at
the SRT line's timestamps, padded slightly so speech at a subtitle's edge
isn't cut off.
"""

import subprocess
from pathlib import Path

from app.config import AUDIO_CLIP_PADDING_MS


class ClipError(Exception):
    pass


def clip_audio(
    source_path: Path,
    start_ms: int,
    end_ms: int,
    out_path: Path,
    padding_ms: int = AUDIO_CLIP_PADDING_MS,
) -> None:
    start_sec = max(0, start_ms - padding_ms) / 1000
    end_sec = (end_ms + padding_ms) / 1000
    duration = end_sec - start_sec

    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{start_sec:.3f}",
            "-i",
            str(source_path),
            "-t",
            f"{duration:.3f}",
            "-acodec",
            "libmp3lame",
            "-q:a",
            "4",
            str(out_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ClipError(f"ffmpeg failed clipping {source_path}: {result.stderr}")
