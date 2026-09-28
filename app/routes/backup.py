from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import anki
from app.services import backup as backup_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/backup")
async def backup_page(request: Request):
    connected = await anki.is_connected()
    backups = backup_service.list_backups()
    return templates.TemplateResponse(
        request,
        "backup.html",
        {"active": "backup", "connected": connected, "backups": backups},
    )


@router.post("/backup/run")
async def backup_run(request: Request):
    info = await backup_service.backup_mining()
    backups = backup_service.list_backups()
    return templates.TemplateResponse(
        request,
        "_backup_section.html",
        {"info": info, "backups": backups},
    )
