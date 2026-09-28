from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

from app import anki
from app.routes import audit, backup, ignored, importer, videos, voices
from app.services import dictionaries as dictionaries_service
from app.services import voicevox as voicevox_service

app = FastAPI(title="Mining")
templates = Jinja2Templates(directory="app/templates")

app.include_router(backup.router)
app.include_router(audit.router)
app.include_router(importer.router)
app.include_router(videos.router)
app.include_router(ignored.router)
app.include_router(voices.router)


@app.get("/")
async def home(request: Request):
    connected = await anki.is_connected()
    voicevox_connected = await voicevox_service.is_connected()
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "active": "home",
            "connected": connected,
            "voicevox_connected": voicevox_connected,
            "dictionaries_ready": dictionaries_service.dictionaries_ready(),
        },
    )
