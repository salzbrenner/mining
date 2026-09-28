from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import anki
from app.config import SOURCE_DECK, TARGET_DECK
from app.services import importer as importer_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/import")
async def import_page(request: Request):
    connected = await anki.is_connected()
    decks = []
    if connected:
        all_decks = await anki.deck_names()
        decks = sorted(d for d in all_decks if d not in (SOURCE_DECK, TARGET_DECK))
    return templates.TemplateResponse(
        request,
        "import.html",
        {"active": "import", "connected": connected, "decks": decks},
    )


@router.get("/import/fields")
async def import_fields(request: Request, deck: str):
    try:
        info = await importer_service.get_source_deck_info(deck)
    except importer_service.InvalidDeckError:
        return templates.TemplateResponse(
            request,
            "_import_fields.html",
            {"info": None, "target_fields": [], "error": "Not a real deck."},
        )
    target_fields = await importer_service.get_target_fields()
    return templates.TemplateResponse(
        request,
        "_import_fields.html",
        {"info": info, "target_fields": target_fields},
    )


@router.post("/import/run")
async def import_run(request: Request):
    form = await request.form()
    deck_name = form["deck_name"]
    model_name = form["model_name"]
    field_map = {}
    for key, value in form.items():
        if key.startswith("map__") and value:
            source_field = key[len("map__") :]
            field_map[source_field] = value

    try:
        result = await importer_service.run_import(deck_name, model_name, field_map)
    except importer_service.InvalidDeckError:
        return templates.TemplateResponse(
            request, "_import_result.html", {"result": None, "error": "Not a real deck."}
        )
    return templates.TemplateResponse(
        request, "_import_result.html", {"result": result}
    )
