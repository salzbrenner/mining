"""YouTube audio/subtitle ingestion (SPEC.md §4, "Videos").

No video is downloaded or stored. `SourceTimestamp` links straight back to
the moment on YouTube for rewatching, so a local video copy doesn't earn its
disk/bandwidth cost. A future screenshot-for-`Picture` feature (SPEC.md §9)
resolves a fresh direct stream URL on demand via yt-dlp and grabs a single
frame with ffmpeg, without ever storing the video. Audio *is* kept locally
(small, ~40-50MB/video) since `SentenceAudio` population processes many
notes from the same video in one pass.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from app.config import VIDEOS_DIR

# yt-dlp's `info["id"]` is used directly in filesystem paths (VIDEOS_DIR /
# video_id) and is also taken as a raw URL path parameter in several routes.
# For real YouTube URLs this is always a safe 11-char id, but yt-dlp
# supports thousands of other sites/extractors whose ids aren't necessarily
# filesystem-safe, and route path parameters are attacker-influenceable
# directly via the URL regardless of what any extractor would ever produce.
# Validating up front closes that off rather than trusting either source.
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_valid_video_id(video_id: str) -> bool:
    return bool(_VIDEO_ID_RE.match(video_id))


class DownloadError(Exception):
    pass


def video_dir(video_id: str) -> Path:
    if not is_valid_video_id(video_id):
        raise ValueError(f"Unsafe video id: {video_id!r}")
    return VIDEOS_DIR / video_id


def list_downloaded() -> list[dict]:
    videos = []
    if not VIDEOS_DIR.exists():
        return videos
    for d in sorted(VIDEOS_DIR.iterdir()):
        meta_path = d / "meta.json"
        if meta_path.exists():
            videos.append(json.loads(meta_path.read_text()))
    return videos


def get_meta(video_id: str) -> dict | None:
    meta_path = video_dir(video_id) / "meta.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def timestamp_url(video_id: str, seconds: int) -> str:
    """The clickable deep link stored in the SourceTimestamp field (SPEC.md §4)."""
    return f"https://youtu.be/{video_id}?t={seconds}s"


@dataclass
class DownloadResult:
    video_id: str
    meta: dict
    already_existed: bool


def download(url: str, prefer_manual_subs: bool = True) -> DownloadResult:
    """Download audio + Japanese subtitles for a YouTube URL (no video).

    Raises DownloadError if no Japanese subtitles (manual or auto-generated)
    are available at all -- there's nothing for Phase 3 to scan otherwise.
    """
    probe_opts = {"quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(probe_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    video_id = info["id"]
    if not is_valid_video_id(video_id):
        # Only possible via a non-YouTube extractor (yt-dlp supports
        # thousands of sites) reporting an id with unexpected characters --
        # real YouTube ids are always safe. Reject rather than let it reach
        # a filesystem path at all.
        raise DownloadError(f"Unsupported/unsafe video id from extractor: {video_id!r}")
    out_dir = video_dir(video_id)

    existing = get_meta(video_id)
    if existing is not None:
        return DownloadResult(video_id=video_id, meta=existing, already_existed=True)

    has_manual = "ja" in (info.get("subtitles") or {})
    has_auto = "ja" in (info.get("automatic_captions") or {})
    if not has_manual and not has_auto:
        raise DownloadError(f"No Japanese subtitles available for {url!r}.")

    use_manual = has_manual and prefer_manual_subs
    subtitle_kind = "manual" if use_manual else "auto"

    out_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "outtmpl": str(out_dir / "audio.%(ext)s"),
        "format": "ba/b",
        "writesubtitles": use_manual,
        "writeautomaticsub": not use_manual,
        "subtitleslangs": ["ja"],
        "subtitlesformat": "srt",
        "postprocessors": [
            {"key": "FFmpegSubtitlesConvertor", "format": "srt"},
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"},
        ],
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    srt_files = list(out_dir.glob("audio.ja.srt"))
    audio_files = list(out_dir.glob("audio.mp3"))

    if not srt_files:
        raise DownloadError(
            f"Expected a .ja.srt subtitle file after download but none was found "
            f"in {out_dir}."
        )
    if not audio_files:
        raise DownloadError(f"Expected audio.mp3 after download but none was found in {out_dir}.")

    srt_files[0].rename(out_dir / "ja.srt")

    meta = {
        "video_id": video_id,
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "source_url": url,
        "duration": info.get("duration"),
        "subtitle_kind": subtitle_kind,
        "audio_filename": "audio.mp3",
        "srt_filename": "ja.srt",
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    return DownloadResult(video_id=video_id, meta=meta, already_existed=False)
