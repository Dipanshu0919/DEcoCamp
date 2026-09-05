"""
SahyogSutra API Routes.
Provides SQL-aggregated leaderboard, calendar API data, language selection,
AI description generation, and bounded async translations.
"""

import logging
import time
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, Depends, Response
from fastapi.responses import JSONResponse

from app.database import AsyncDB, get_db
from app.security import get_current_user
from app.services.ai_service import generate_campaign_descriptions
from app.services.translation_service import translate_dict_fields
from app.utils import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter()

# Leaderboard bounded cache
_leaderboard_cache = {"data": None, "ts": 0}
LEADERBOARD_CACHE_TTL = 60  # seconds


@router.get("/api/leaderboard")
async def handle_api_leaderboard(db: AsyncDB = Depends(get_db)):
    """
    Returns top 5 event organizers using pure SQL aggregation.
    Cached for 60 seconds to eliminate repeated queries.
    """
    global _leaderboard_cache
    now = time.time()
    if _leaderboard_cache["data"] and (now - _leaderboard_cache["ts"] < LEADERBOARD_CACHE_TTL):
        return JSONResponse(content=_leaderboard_cache["data"])

    # SQL aggregation: avoid loading all users and parsing in Python memory
    query = """
        SELECT COALESCE(u.name, e.username) as name, e.username, COUNT(e.eventid) as count
        FROM eventdetail e
        LEFT JOIN userdetails u ON e.username = u.username
        WHERE e.username IS NOT NULL AND e.username != ''
        GROUP BY e.username
        ORDER BY count DESC
        LIMIT 5
    """
    rows = await db.fetchall(query)
    top5 = [dict(r) for r in rows]

    _leaderboard_cache = {"data": top5, "ts": now}
    return JSONResponse(content=top5)


@router.get("/api")
async def handle_api(request: Request, db: AsyncDB = Depends(get_db)):
    """Returns active event details for calendar rendering."""
    events = await db.fetchall(
        "SELECT eventid, eventname, location, category, eventstartdate, eventstarttime, description FROM eventdetail"
    )
    user = await get_current_user(request, db)
    return JSONResponse(content={
        "active events": events,
        "current user": user or "No user logged in"
    })


@router.post("/setlanguage/{lang}")
async def handle_set_language(request: Request, lang: str):
    clean_lang = lang.strip().lower()[:10]
    request.session["lang"] = clean_lang
    return Response(content="Language Set", media_type="text/plain")


@router.get("/changetemplate")
async def handle_change_template(request: Request):
    ct = request.session.get("template", "index.html")
    request.session["template"] = "index2.html" if ct == "index.html" else "index.html"
    return Response(content="Template Changed", media_type="text/plain")


@router.post("/save_draft")
async def handle_save_draft(request: Request):
    form_data = await request.form()
    field = str(form_data.get("field") or "")[:50]
    value = str(form_data.get("value") or "")[:500]
    # Allow saving only whitelisted event creation fields in draft session
    allowed_fields = {
        "eventname", "location", "category", "description",
        "eventstartdate", "eventenddate", "eventstarttime", "eventendtime"
    }
    if field in allowed_fields and value.strip():
        request.session[f"draft_{field}"] = value.strip()
    return Response(content="DRAFT", media_type="text/plain")


@router.post("/generate_ai_description")
async def handle_generate_ai_description(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    allowed, wait = check_rate_limit(f"ai_{client_ip}", window_seconds=60)
    if not allowed:
        return JSONResponse(content={"wait": wait}, status_code=429)

    try:
        form_data = dict(await request.form())
        results = await generate_campaign_descriptions(form_data)
        return JSONResponse(content=results)
    except Exception as e:
        logger.error("AI Description Error: %s", e)
        return Response(content="Error generating description. Please try again later.", media_type="text/plain", status_code=500)


@router.post("/translate_event")
async def handle_translate_event(request: Request):
    data = await request.json()
    lang = request.session.get("lang", "en")
    output = await translate_dict_fields(data, lang)
    return JSONResponse(content=output)

