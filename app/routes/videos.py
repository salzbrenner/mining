import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from app.config import AUDIO_CLIP_PADDING_MS, AUDIO_CLIP_PADDING_MS_AUTO
from app.services import clip as clip_service
from app.services import dictionaries as dictionaries_service
from app.services import scan as scan_service
from app.services import srt as srt_service
from app.services import youtube as youtube_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/videos")
async def videos_page(request: Request):
    videos = youtube_service.list_downloaded()
    return templates.TemplateResponse(
        request, "videos.html", {"active": "videos", "videos": videos}
    )


@router.post("/videos/add")
async def videos_add(request: Request):
    form = await request.form()
    url = form.get("url", "").strip()
    if not url:
        return templates.TemplateResponse(
            request,
            "_videos_add_result.html",
            {"error": "Enter a YouTube URL."},
        )
    try:
        result = youtube_service.download(url)
    except youtube_service.DownloadError as exc:
        return templates.TemplateResponse(
            request, "_videos_add_result.html", {"error": str(exc)}
        )
    return templates.TemplateResponse(
        request, "_videos_add_result.html", {"result": result}
    )


@router.get("/videos/{video_id}")
async def video_detail(request: Request, video_id: str):
    if not youtube_service.is_valid_video_id(video_id):
        return Response(status_code=404)
    meta = youtube_service.get_meta(video_id)
    if meta is None:
        return templates.TemplateResponse(
            request,
            "video_detail.html",
            {"active": "videos", "meta": None},
        )
    srt_path = youtube_service.video_dir(video_id) / meta["srt_filename"]
    lines = srt_service.parse(srt_path) if srt_path.exists() else []
    return templates.TemplateResponse(
        request,
        "video_detail.html",
        {
            "active": "videos",
            "meta": meta,
            "lines": lines,
            "dictionaries_ready": dictionaries_service.dictionaries_ready(),
        },
    )


@router.get("/videos/{video_id}/clip")
async def video_clip(video_id: str, start_ms: int, end_ms: int):
    """On-the-fly audio clip for the scan preview's play button -- not
    stored anywhere, just generated and streamed back for this one request.
    """
    if not youtube_service.is_valid_video_id(video_id):
        return Response(status_code=404)
    meta = youtube_service.get_meta(video_id)
    if meta is None:
        return Response(status_code=404)
    audio_path = youtube_service.video_dir(video_id) / meta["audio_filename"]
    padding_ms = (
        AUDIO_CLIP_PADDING_MS_AUTO
        if meta["subtitle_kind"] == "auto"
        else AUDIO_CLIP_PADDING_MS
    )
    with tempfile.NamedTemporaryFile(suffix=".mp3") as tmp:
        try:
            clip_service.clip_audio(
                audio_path, start_ms, end_ms, Path(tmp.name), padding_ms=padding_ms
            )
        except clip_service.ClipError:
            return Response(status_code=500)
        data = Path(tmp.name).read_bytes()
    return Response(content=data, media_type="audio/mpeg")


def _candidate_to_dict(c) -> dict:
    return {
        "headword": c.headword,
        "reading": c.reading,
        "pos": c.pos,
        "frequency": c.frequency,
        "sentence": c.sentence,
        "start_ms": c.start_ms,
        "end_ms": c.end_ms,
        "timestamp_seconds": c.timestamp_seconds,
        "timestamp_label": c.timestamp_label,
    }


@router.post("/videos/{video_id}/scan")
async def video_scan(request: Request, video_id: str):
    """Dry-run only -- never writes to Anki. See SPEC.md §4 (Scan)."""
    if not youtube_service.is_valid_video_id(video_id):
        return Response(status_code=404)
    result = await scan_service.preview_video(video_id)
    candidates_json = json.dumps([_candidate_to_dict(c) for c in result.candidates])
    return templates.TemplateResponse(
        request,
        "_scan_preview.html",
        {"video_id": video_id, "result": result, "candidates_json": candidates_json},
    )


@router.post("/videos/{video_id}/scan/commit")
async def video_scan_commit(request: Request, video_id: str):
    if not youtube_service.is_valid_video_id(video_id):
        return Response(status_code=404)
    # A large scan can have hundreds of checkboxes; the candidate data
    # itself travels as one JSON blob (see below) so the field count here
    # stays small (one per checked row), but max_fields is still bumped as
    # a defensive margin.
    form = await request.form(max_fields=5000)
    candidates = json.loads(form["candidates_json"])
    indices = sorted(
        int(k[len("select__") :]) for k in form if k.startswith("select__")
    )
    selections = [
        scan_service.PreviewCandidate(**candidates[i], low_confidence=False)
        for i in indices
    ]
    result = await scan_service.commit_selections(video_id, selections)
    return templates.TemplateResponse(
        request, "_scan_commit_result.html", {"result": result}
    )
