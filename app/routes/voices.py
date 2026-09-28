from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services import voice_exclusions
from app.services import voicevox as voicevox_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _find_speaker_style(speaker_id: int):
    speakers = await voicevox_service.list_speakers()
    for sp in speakers:
        for style in sp["styles"]:
            if style["id"] == speaker_id:
                return sp, style
    return None, None


@router.get("/voices")
async def voices_page(request: Request):
    connected = await voicevox_service.is_connected()
    speakers = await voicevox_service.list_speakers() if connected else []
    excluded = voice_exclusions.load_excluded()
    return templates.TemplateResponse(
        request,
        "voices.html",
        {
            "active": "voices",
            "connected": connected,
            "speakers": speakers,
            "excluded": excluded,
        },
    )


@router.post("/voices/exclude")
async def voices_exclude(request: Request):
    form = await request.form()
    speaker_id = int(form["speaker_id"])
    voice_exclusions.add_excluded(speaker_id)
    sp, style = await _find_speaker_style(speaker_id)
    return templates.TemplateResponse(
        request,
        "_voice_row.html",
        {"sp": sp, "style": style, "excluded": voice_exclusions.load_excluded()},
    )


@router.post("/voices/include")
async def voices_include(request: Request):
    form = await request.form()
    speaker_id = int(form["speaker_id"])
    voice_exclusions.remove_excluded(speaker_id)
    sp, style = await _find_speaker_style(speaker_id)
    return templates.TemplateResponse(
        request,
        "_voice_row.html",
        {"sp": sp, "style": style, "excluded": voice_exclusions.load_excluded()},
    )
