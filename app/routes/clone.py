from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import anki
from app.services import backup as backup_service
from app.services import clone as clone_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/clone")
async def clone_page(request: Request):
    connected = await anki.is_connected()
    status = await clone_service.get_status() if connected else None
    backups = backup_service.list_backups()
    return templates.TemplateResponse(
        request,
        "clone.html",
        {"active": "clone", "connected": connected, "status": status, "backups": backups},
    )


@router.post("/clone/run")
async def clone_run(request: Request):
    result = await clone_service.run_clone()
    status = await clone_service.get_status()
    return templates.TemplateResponse(
        request,
        "_clone_result.html",
        {"result": result, "status": status},
    )


@router.post("/clone/clear-and-reclone")
async def clone_clear_and_reclone(request: Request):
    clear_result = await clone_service.clear_and_reclone()
    status = await clone_service.get_status()
    return templates.TemplateResponse(
        request,
        "_clone_result.html",
        {
            "result": clear_result.clone_result,
            "status": status,
            "cleared": clear_result.deleted,
        },
    )


@router.post("/clone/promote")
async def clone_promote(request: Request):
    result = await clone_service.run_reverse_clone()
    status = await clone_service.get_status()
    return templates.TemplateResponse(
        request,
        "_promote_result.html",
        {"result": result, "status": status},
    )


@router.post("/clone/backup")
async def clone_backup(request: Request):
    info = await backup_service.backup_mining()
    backups = backup_service.list_backups()
    return templates.TemplateResponse(
        request,
        "_backup_section.html",
        {"info": info, "backups": backups},
    )
