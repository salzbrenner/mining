from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services import ignore_list

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.post("/ignored-words")
async def add_ignored_word(request: Request):
    form = await request.form()
    word = form.get("word", "").strip()
    if word:
        ignore_list.add_ignored(word)
    # Empty response -- the scan preview row targeting this swaps its own
    # outerHTML to nothing, visually confirming the row was removed.
    return HTMLResponse("")


@router.get("/ignored-words")
async def ignored_words_page(request: Request):
    words = sorted(ignore_list.load_ignored())
    return templates.TemplateResponse(
        request, "ignored_words.html", {"active": "ignored", "words": words}
    )


@router.post("/ignored-words/remove")
async def remove_ignored_word(request: Request):
    form = await request.form()
    word = form.get("word", "").strip()
    if word:
        ignore_list.remove_ignored(word)
    words = sorted(ignore_list.load_ignored())
    return templates.TemplateResponse(
        request, "_ignored_words_list.html", {"words": words}
    )
