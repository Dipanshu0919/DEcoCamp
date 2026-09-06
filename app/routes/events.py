"""
SahyogSutra Event Routes.
Handles campaign browsing, event creation, approval, deletion, calendar ICS, and CSV export.
"""

import csv
import datetime
import io
import json
import logging
import os
import time
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Form, Depends, Response, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.config import IST
from app.database import AsyncDB, get_db, run_queries_parallel
from app.security import get_current_user, require_authenticated_user, require_admin_user
from app.services.event_service import (
    create_event_request,
    approve_event_request,
    delete_event_by_id
)
from app.services.translation_service import (
    sync_translate_text,
    get_ui_translation_dict,
    translate_event_data,
    translate_events_batch
)
from app.utils import datetimeformat

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.filters["datetimeformat"] = datetimeformat

# Bounded Campaigns & Event Count Cache
_campaigns_cache = {"data": None, "ts": 0}
CAMPAIGNS_CACHE_TTL = 60  # seconds
_events_count_cache = {"count": 0, "ts": 0}
COUNT_CACHE_TTL = 120  # seconds

def invalidate_campaigns_cache():
    global _campaigns_cache, _events_count_cache
    _campaigns_cache["ts"] = 0
    _events_count_cache["ts"] = 0

async def _async_refresh_event_count():
    """Background task to refresh event count cache without blocking visitor requests."""
    global _events_count_cache
    try:
        from app.database import run_query
        cnt_res = await run_query("SELECT COUNT(*) as count FROM eventdetail", fetchmode="one")
        if cnt_res and "count" in cnt_res:
            _events_count_cache = {"count": cnt_res["count"], "ts": time.time()}
    except Exception as e:
        logger.debug("Failed background event count refresh: %s", e)

async def prewarm_event_count(db: AsyncDB):
    """Pre-warms the active event count cache during startup to avoid query delay on first visitor."""
    global _events_count_cache
    try:
        cnt_res = await db.fetchone("SELECT COUNT(*) as count FROM eventdetail")
        count = cnt_res["count"] if cnt_res else 0
        _events_count_cache = {"count": count, "ts": time.time()}
        logger.info("Event count cache pre-warmed: %d active events", count)
    except Exception as e:
        logger.warning("Failed to prewarm event count: %s", e)


@router.get("/")
async def home_page(
    request: Request,
    preview: bool = False,
    db: AsyncDB = Depends(get_db)
):
    global _events_count_cache, _campaigns_cache
    session = request.session
    user_lang = session.get("lang")

    if not user_lang and not preview:
        return templates.TemplateResponse(request, "selectlanguage.html")

    user = await get_current_user(request, db)
    current_uname = user["username"] if user else "None"
    current_name = user["name"] if user else "User"
    is_admin = (user.get("role") == "admin") if user else False

    admin_stats = {}
    if is_admin:
        import threading
        results = await run_queries_parallel(
            ("SELECT COUNT(*) as count FROM userdetails", (), "one"),
            ("SELECT COUNT(*) as count FROM eventreq", (), "one"),
            ("SELECT COUNT(*) as count FROM eventdetail", (), "one"),
        )
        admin_stats = {
            "total_users": results[0]["count"] if results[0] else 0,
            "pending_requests": results[1]["count"] if results[1] else 0,
            "active_threads": threading.active_count(),
            "total_events": results[2]["count"] if results[2] else 0
        }

    active_events_length = 0
    if is_admin and admin_stats.get("total_events"):
        active_events_length = admin_stats["total_events"]
    elif _campaigns_cache["data"] and (time.time() - _campaigns_cache["ts"] < CAMPAIGNS_CACHE_TTL):
        active_events_length = len(_campaigns_cache["data"].get("edetailslist", []))
    elif _events_count_cache["ts"]:
        active_events_length = _events_count_cache["count"]
        # Trigger background refresh if TTL elapsed without blocking the HTTP response
        if time.time() - _events_count_cache["ts"] >= COUNT_CACHE_TTL:
            import asyncio
            asyncio.create_task(_async_refresh_event_count())
    else:
        cnt_res = await db.fetchone("SELECT COUNT(*) as count FROM eventdetail")
        active_events_length = cnt_res["count"] if cnt_res else 0
        _events_count_cache = {"count": active_events_length, "ts": time.time()}

    template_name = session.get("template", "index.html")
    lang_to_use = user_lang or "en"

    bound_translate = lambda text, *args, **kwargs: (text or "")

    return templates.TemplateResponse(request, template_name, {
        "active_events_length": active_events_length,
        "fullname": current_name,
        "c_user": current_uname,
        "isadmin": is_admin,
        "userdetails": user or {},
        "translate": bound_translate,
        "lang": lang_to_use,
        "user_language": lang_to_use,
        "fvalues": {},
        "top_organizers": [],  # Fetched client-side via /api/leaderboard
        "admin_stats": admin_stats,
        "is_preview": preview
    })


@router.get("/show_campaigns")
async def show_campaigns(
    request: Request,
    user: Optional[str] = None,
    db: AsyncDB = Depends(get_db)
):
    global _campaigns_cache
    current_user_obj = await get_current_user(request, db)
    current_uname = current_user_obj["username"] if current_user_obj else "None"
    is_admin = (current_user_obj.get("role") == "admin") if current_user_obj else False
    user_lang = request.session.get("lang", "en")

    now = time.time()
    if _campaigns_cache["data"] and (now - _campaigns_cache["ts"] < CAMPAIGNS_CACHE_TTL):
        cached = _campaigns_cache["data"]
        edetailslist = cached["edetailslist"]
        trending_events = cached["trending_events"]
        allevents = cached["allevents"]
    else:
        rows = await db.fetchall(
            """
            SELECT eventid, eventname, email, eventstarttime, eventendtime,
                   eventstartdate, eventenddate, location, category, description,
                   username, likes
            FROM eventdetail
            """
        )
        edetailslist = [dict(r) for r in rows]
        trending_events = sorted(edetailslist, key=lambda x: x.get("likes") or 0, reverse=True)[:4]

        allevents = {}
        for x in edetailslist:
            cat = x.get("category") or "General"
            allevents.setdefault(cat, []).append(x)

        _campaigns_cache = {
            "data": {
                "edetailslist": edetailslist,
                "trending_events": trending_events,
                "allevents": allevents,
            },
            "ts": now
        }

    session_user = request.session.pop("vieweventusername", None)
    session_viewyourevents = request.session.pop("viewyourevents", False)

    target_user = (user if user is not None else session_user) or ""
    target_user_clean = target_user.strip()

    if user is not None:
        viewyourevents = bool(target_user_clean and target_user_clean.lower() not in ("none", "all"))
        viewuserevent = target_user_clean if viewyourevents else ""
    else:
        viewyourevents = bool(session_viewyourevents and target_user_clean and target_user_clean.lower() != "none")
        viewuserevent = target_user_clean if viewyourevents else (current_uname if current_uname != "None" else "")

    user_event_count = 0
    if viewyourevents and viewuserevent:
        u_target = viewuserevent.strip().lower()
        for x in edetailslist:
            if (x.get("username") or "").strip().lower() == u_target:
                user_event_count += 1

    sortby = request.session.get("sortby", "eventstartdate")

    if user_lang == "en":
        bound_translate = lambda text, *args, **kwargs: text
    else:
        _page_dict = get_ui_translation_dict(user_lang)
        def bound_translate(text: str, *args, **kwargs) -> str:
            clean = text.strip()
            return _page_dict.get(clean, text)

    response = templates.TemplateResponse(request, "campaigns.html", {
        "allevents": allevents,
        "userdetails": current_user_obj or {},
        "viewyourevents": viewyourevents,
        "sortby": sortby,
        "isadmin": is_admin,
        "c_user": current_uname,
        "viewuserevent": viewuserevent,
        "total_active_events": len(edetailslist),
        "user_event_count": user_event_count,
        "translate": bound_translate,
        "trending_events": trending_events,
        "lang": user_lang,
        "user_language": user_lang
    })
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@router.get("/event/{eventid}")
async def event_detail_page(
    request: Request,
    eventid: int,
    db: AsyncDB = Depends(get_db)
):
    event = await db.fetchone("SELECT * FROM eventdetail WHERE eventid = ?", (eventid,))
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    user = await get_current_user(request, db)
    current_uname = user["username"] if user else "None"
    is_admin = (user.get("role") == "admin") if user else False
    user_lang = request.session.get("lang", "en")

    if user_lang == "en":
        bound_translate = lambda text, *args, **kwargs: text
    else:
        _page_dict = get_ui_translation_dict(user_lang)
        def bound_translate(text: str, *args, **kwargs) -> str:
            clean = text.strip()
            return _page_dict.get(clean, text)

    return templates.TemplateResponse(request, "viewevent.html", {
        "isadmin": is_admin,
        "c_user": current_uname,
        "eventdetails": event,
        "translate": bound_translate,
        "lang": user_lang,
        "user_language": user_lang,
        "userdetails": user or {}
    })


@router.get("/show_add_form")
async def show_add_form(request: Request):
    user_lang = request.session.get("lang", "en")
    categories = {}
    if os.path.exists("events.json"):
        try:
            with open("events.json", "r", encoding="utf-8") as f:
                categories = json.load(f)
        except Exception:
            pass

    fi = ["eventname", "email", "starttime", "endtime", "eventstartdate", "enddate", "location", "category", "description"]
    fv = {x: request.session.get(f"draft_{x}", request.session.get(x, "")) for x in fi}

    if user_lang == "en":
        bound_translate = lambda text, *args, **kwargs: text
    else:
        _page_dict = get_ui_translation_dict(user_lang)
        def bound_translate(text: str, *args, **kwargs) -> str:
            clean = text.strip()
            return _page_dict.get(clean, text)

    return templates.TemplateResponse(request, "addevent.html", {
        "fvalues": fv,
        "translate": bound_translate,
        "lang": user_lang,
        "categories": categories
    })


@router.get("/dummyevent")
async def handle_dummy_event(request: Request):
    import random
    request.session["draft_eventname"] = random.choice([
        "Community Tree Plantation",
        "Neighborhood Blood Donation Camp",
        "Local Cleanliness Drive"
    ])
    request.session["draft_description"] = "Join us for a community tree plantation drive to make our neighborhood greener and healthier!"
    request.session["draft_location"] = random.choice([
        "Central Park", "Community Center", "City Hall", "Riverside Park", "Downtown Square"
    ])
    request.session["draft_category"] = random.choice([
        "Tree Plantation", "Blood Donation", "Cleanliness Drive"
    ])
    request.session["draft_eventstartdate"] = f"{random.randint(2026, 2028)}-{random.randint(10, 12):02d}-{random.randint(10, 28):02d}"
    request.session["draft_enddate"] = f"{random.randint(2026, 2028)}-{random.randint(10, 12):02d}-{random.randint(10, 28):02d}"
    request.session["draft_starttime"] = f"{random.randint(10, 12)}:{random.randint(10, 59)}"
    request.session["draft_endtime"] = f"{random.randint(10, 12)}:{random.randint(10, 59)}"
    return RedirectResponse(url="/#add", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/addeventreq")
async def handle_add_event_request(
    request: Request,
    db: AsyncDB = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return Response(content="Please Login First To Add Event.", media_type="text/plain")

    form_data = dict(await request.form())
    ok, msg = await create_event_request(
        form_data=form_data,
        username=user["username"],
        email=user["email"],
        db=db
    )
    return Response(content=msg, media_type="text/plain")


@router.post("/addevent")
async def handle_approve_event(
    request: Request,
    db: AsyncDB = Depends(get_db)
):
    admin_user = await require_admin_user(request, db)
    form_data = dict(await request.form())

    ok, msg = await approve_event_request(
        form_data=form_data,
        admin_username=admin_user["username"],
        db=db
    )
    invalidate_campaigns_cache()
    return Response(content=msg, media_type="text/plain")


@router.post("/deleteevent/{eventid}")
async def handle_delete_event(
    eventid: int,
    request: Request,
    db: AsyncDB = Depends(get_db)
):
    user = await require_authenticated_user(request, db)
    is_admin = (user.get("role") == "admin")
    ok, msg = await delete_event_by_id(
        event_id=eventid,
        requester_username=user["username"],
        is_admin=is_admin,
        db=db
    )
    invalidate_campaigns_cache()
    if msg == "REDIRECT_HOME":
        return Response(content="REDIRECT_HOME", media_type="text/plain")
    return Response(content=msg, media_type="text/plain")


# Support backward compatibility for delete event link
@router.get("/deleteevent/{eventid}")
async def handle_delete_event_get(
    eventid: int,
    request: Request,
    db: AsyncDB = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    is_admin = (user.get("role") == "admin")
    ok, msg = await delete_event_by_id(
        event_id=eventid,
        requester_username=user["username"],
        is_admin=is_admin,
        db=db
    )
    invalidate_campaigns_cache()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/viewyourevents")
@router.post("/viewyourevents/")
@router.post("/viewyourevents/{username}")
async def handle_view_your_events(request: Request, username: str = "", db: AsyncDB = Depends(get_db)):
    clean_u = (username or "").strip()
    if clean_u.lower() == "all":
        request.session["viewyourevents"] = False
        request.session.pop("vieweventusername", None)
    elif not clean_u or clean_u.lower() == "none":
        user = await get_current_user(request, db)
        if user:
            request.session["viewyourevents"] = True
            request.session["vieweventusername"] = user["username"]
        else:
            request.session["viewyourevents"] = False
            request.session.pop("vieweventusername", None)
    else:
        request.session["viewyourevents"] = True
        request.session["vieweventusername"] = clean_u
    return Response(content="OK", media_type="text/plain")


@router.post("/setsortby/{sortby}")
async def handle_set_sort_by(request: Request, sortby: str):
    request.session["sortby"] = sortby
    return Response(content="Sort by set", media_type="text/plain")


@router.get("/download_ics/{eventid}")
async def handle_download_ics(eventid: int, db: AsyncDB = Depends(get_db)):
    event = await db.fetchone("SELECT * FROM eventdetail WHERE eventid = ?", (eventid,))
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    try:
        start_date = str(event.get("eventstartdate") or "").replace("-", "")
        start_time = str(event.get("eventstarttime") or "").replace(":", "")
        start_dt = f"{start_date}T{start_time}00" if start_date else datetime.datetime.now().strftime("%Y%m%dT%H%M%S")

        end_date = str(event.get("eventenddate") or "").replace("-", "")
        end_time = str(event.get("eventendtime") or "").replace(":", "")
        end_dt = f"{end_date}T{end_time}00" if end_date else start_dt
    except Exception:
        start_dt = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        end_dt = start_dt

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//SahyogSutra//Events//EN
BEGIN:VEVENT
UID:SahyogSutra-{eventid}
DTSTAMP:{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}
DTSTART:{start_dt}
DTEND:{end_dt}
SUMMARY:{event.get('eventname', '')}
DESCRIPTION:{event.get('description', '')}
LOCATION:{event.get('location', '')}
END:VEVENT
END:VCALENDAR"""

    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": f"attachment; filename=event_{eventid}.ics"}
    )


@router.get("/export_data")
async def handle_export_data(request: Request, db: AsyncDB = Depends(get_db)):
    user = await require_authenticated_user(request, db)
    username = user["username"]

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["--- USER PROFILE ---"])
    writer.writerow(["Name", "Username", "Email", "Role"])
    writer.writerow([user.get("name"), user.get("username"), user.get("email"), user.get("role")])

    writer.writerow([])
    writer.writerow(["--- CREATED EVENTS ---"])
    writer.writerow(["Event ID", "Name", "Location", "Category", "Date", "Description"])

    events = await db.fetchall(
        "SELECT eventid, eventname, location, category, eventstartdate, description FROM eventdetail WHERE username = ?",
        (username,)
    )
    for ev in events:
        writer.writerow([
            ev["eventid"],
            ev["eventname"],
            ev["location"],
            ev["category"],
            ev["eventstartdate"],
            ev["description"]
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=SahyogSutra_data_{username}.csv"}
    )


@router.get("/user/{username}")
async def handle_user_profile(
    request: Request,
    username: str,
    db: AsyncDB = Depends(get_db)
):
    target_user = await db.fetchone(
        "SELECT username, name, email, role, events, likes FROM userdetails WHERE username = ?",
        (username.strip().lower(),)
    )
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    auth_user = await get_current_user(request, db)
    is_own_profile = (auth_user and auth_user["username"] == target_user["username"])
    user_lang = request.session.get("lang", "en")

    if user_lang == "en":
        bound_translate = lambda text, *args, **kwargs: text
    else:
        _page_dict = get_ui_translation_dict(user_lang)
        def bound_translate(text: str, *args, **kwargs) -> str:
            clean = text.strip()
            return _page_dict.get(clean, text)

    return templates.TemplateResponse(request, "userprofile.html", {
        "userdetails": dict(target_user),
        "translate": bound_translate,
        "lang": user_lang,
        "user_language": user_lang,
        "is_own_profile": bool(is_own_profile)
    })

