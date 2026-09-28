from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import anki
from app.services import audio_backfill as audio_backfill_service
from app.services import audit as audit_service
from app.services import voicevox as voicevox_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/audit")
async def audit_page(request: Request):
    connected = await anki.is_connected()
    report = await audit_service.run_audit() if connected else None
    voicevox_connected = await voicevox_service.is_connected()
    missing_audio = await audio_backfill_service.count_missing() if connected else None
    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            "active": "audit",
            "connected": connected,
            "report": report,
            "voicevox_connected": voicevox_connected,
            "missing_audio": missing_audio,
        },
    )


@router.post("/audit/refresh")
async def audit_refresh(request: Request):
    report = await audit_service.run_audit()
    return templates.TemplateResponse(
        request, "_audit_report.html", {"report": report}
    )


@router.post("/audit/open/{note_id}")
async def audit_open(note_id: int):
    await anki.gui_browse(f"nid:{note_id}")
    return {"ok": True}


@router.post("/audit/backfill-audio")
async def audit_backfill_audio(request: Request):
    result = await audio_backfill_service.run_backfill(limit=30)
    return templates.TemplateResponse(
        request, "_backfill_section.html", {"result": result}
    )
