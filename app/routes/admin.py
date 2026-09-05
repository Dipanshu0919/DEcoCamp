"""
SahyogSutra Admin Routes.
Handles pending event approvals/declines and administrative controls.
Strictly enforced by authoritative database role checks.
"""

import json
import logging
import os
from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.database import AsyncDB, get_db, _idle_pool, _open_connections, DB_POOL_MAX
from app.security import require_admin_user
from app.services.event_service import decline_event_request

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/show_pending_events")
async def handle_show_pending_events(
    request: Request,
    db: AsyncDB = Depends(get_db)
):
    admin_user = await require_admin_user(request, db)

    rows = await db.fetchall("SELECT * FROM eventreq ORDER BY eventid DESC")
    pending = [dict(r) for r in rows]

    categories = {}
    if os.path.exists("events.json"):
        try:
            with open("events.json", "r", encoding="utf-8") as f:
                categories = json.load(f)
        except Exception:
            pass

    return templates.TemplateResponse(request, "pendingevents.html", {
        "pendingevents": pending,
        "categories": categories,
        "isadmin": True
    })


@router.post("/decline_event/{eventid}")
async def handle_decline_event_post(
    eventid: int,
    request: Request,
    db: AsyncDB = Depends(get_db)
):
    admin_user = await require_admin_user(request, db)

    # Accept either JSON body or Form data
    reason = "Declined by administrator"
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
            reason = body.get("reason", reason)
        else:
            form = await request.form()
            reason = form.get("reason", reason)
    except Exception:
        pass

    ok, msg = await decline_event_request(
        event_id=eventid,
        reason=reason,
        admin_username=admin_user["username"],
        db=db
    )
    return Response(content=msg, media_type="text/plain")


@router.get("/decline_event/{eventid}/{reason}")
async def handle_decline_event_get_compat(
    eventid: int,
    reason: str,
    request: Request,
    db: AsyncDB = Depends(get_db)
):
    admin_user = await require_admin_user(request, db)

    await decline_event_request(
        event_id=eventid,
        reason=reason,
        admin_username=admin_user["username"],
        db=db
    )
    return RedirectResponse(url="/#pending", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/pool/status")
async def handle_pool_status(
    request: Request,
    db: AsyncDB = Depends(get_db)
):
    await require_admin_user(request, db)

    return JSONResponse({
        "pool_idle": _idle_pool.qsize(),
        "pool_open_total": _open_connections,
        "pool_max": DB_POOL_MAX,
        "status": "active"
    })

