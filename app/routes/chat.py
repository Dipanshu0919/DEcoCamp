"""
SahyogSutra Chat & Real-Time Socket.IO Module.
Handles group chat rendering with relational pagination, secure handshake authentication,
server-enforced author identity, room-based isolation, and like synchronization.
"""

import datetime
import logging
from typing import Optional
from fastapi import APIRouter, Request, Depends, Response
from fastapi.templating import Jinja2Templates
import socketio

from app.config import IST, SESSION_COOKIE_NAME
from app.database import AsyncDB, get_db, run_query
from app.security import decode_session_cookie, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Async Socket.IO server
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")


@router.get("/group-chat/from-event/{eventid}")
async def group_chat_page(
    request: Request,
    eventid: int,
    db: AsyncDB = Depends(get_db)
):
    """Renders the event group chat with paginated messages from the relational messages table."""
    user = await get_current_user(request, db)
    current_uname = user["username"] if user else "anonymous"

    event = await db.fetchone(
        "SELECT eventname FROM eventdetail WHERE eventid = ?",
        (eventid,)
    )
    if not event:
        return Response(content="No such event found.", media_type="text/plain")

    # Paginated query: Fetch last 50 messages ordered by srno
    rows = await db.fetchall(
        """
        SELECT username, message, time
        FROM messages
        WHERE eventid = ?
        ORDER BY srno DESC
        LIMIT 50
        """,
        (eventid,)
    )
    # Reverse so oldest of the 50 is displayed first
    messages = [(r["username"], r["message"], r["time"]) for r in reversed(rows)]

    return templates.TemplateResponse(request, "groupchat.html", {
        "messages": messages,
        "eventid": eventid,
        "currentuname": current_uname,
        "eventname": event["eventname"]
    })


# --- Socket.IO Event Handlers ---

@sio.event
async def connect(sid, environ, auth=None):
    """
    Authenticates Socket.IO connection using the signed session cookie.
    Associates the socket ID strictly with the authenticated user ID.
    """
    # Extract cookies from environ
    cookie_header = environ.get("HTTP_COOKIE", "")
    if not cookie_header and "asgi.scope" in environ:
        headers = dict(environ["asgi.scope"].get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode("utf-8")

    username = None
    if cookie_header:
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith(f"{SESSION_COOKIE_NAME}="):
                cookie_val = part[len(SESSION_COOKIE_NAME) + 1:]
                session_data = decode_session_cookie(cookie_val)
                if session_data and session_data.get("username"):
                    username = session_data["username"]
                break

    await sio.save_session(sid, {"username": username})
    logger.debug("Socket connected: %s (User: %s)", sid, username)


@sio.event
async def disconnect(sid):
    logger.debug("Socket disconnected: %s", sid)


@sio.on("join_chat")
async def handle_join_chat(sid, data):
    """Joins client to a specific event room."""
    eventid = data.get("eventid")
    if eventid:
        room_name = f"event_{eventid}"
        await sio.enter_room(sid, room_name)


@sio.on("add_grp_msg")
async def handle_add_group_message(sid, data):
    """
    Handles new group message.
    Strictly enforces author identity from authenticated socket session.
    Rejects spoofed usernames in data payload.
    """
    session = await sio.get_session(sid)
    author_username = session.get("username") if session else None

    if not author_username or author_username == "anonymous":
        await sio.emit("error", {"message": "You must be logged in to send messages."}, to=sid)
        return

    try:
        eventid = int(data.get("eventid"))
    except (TypeError, ValueError):
        return

    raw_message = str(data.get("message") or "").strip()
    if not raw_message or len(raw_message) > 2000:
        return

    # Check that event exists
    event = await run_query("SELECT eventid FROM eventdetail WHERE eventid = ?", (eventid,), fetchmode="one")
    if not event:
        return

    msg_time = datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    # Insert individual message row into relational table
    await run_query(
        "INSERT INTO messages (eventid, username, message, time) VALUES (?, ?, ?, ?)",
        (eventid, author_username, raw_message, msg_time),
        fetchmode=None
    )

    payload = {
        "eventid": eventid,
        "username": author_username,
        "message": raw_message,
        "time": msg_time
    }

    # Ensure sender is in room
    room_name = f"event_{eventid}"
    await sio.enter_room(sid, room_name)

    # Broadcast to event room and to sender
    await sio.emit("new_message", payload, room=room_name)


@sio.on("addeventlike")
async def handle_add_like(sid, data):
    """
    Toggles like for an event.
    Enforces user identity from authenticated socket session.
    """
    session = await sio.get_session(sid)
    username = session.get("username") if session else None

    if not username:
        return

    try:
        eventid = int(data.get("eventid"))
        like_type = data.get("type")
    except (TypeError, ValueError):
        return

    ud = await run_query(
        "SELECT likes FROM userdetails WHERE username = ?",
        (username,),
        fetchmode="one"
    )
    if not ud:
        return

    liked_events = ud["likes"].split(",") if ud.get("likes") else []
    event_str = str(eventid)

    if like_type == "add":
        if event_str not in liked_events:
            liked_events.append(event_str)
            await run_query("UPDATE eventdetail SET likes = likes + 1 WHERE eventid = ?", (eventid,), fetchmode=None)
    else:
        if event_str in liked_events:
            liked_events.remove(event_str)
            await run_query("UPDATE eventdetail SET likes = MAX(0, likes - 1) WHERE eventid = ?", (eventid,), fetchmode=None)

    new_likes_str = ",".join(liked_events) if liked_events else None
    await run_query("UPDATE userdetails SET likes = ? WHERE username = ?", (new_likes_str, username), fetchmode=None)

    # Fetch updated count
    ev_row = await run_query("SELECT likes FROM eventdetail WHERE eventid = ?", (eventid,), fetchmode="one")
    new_likes_count = ev_row["likes"] if ev_row else 0

    # Broadcast updated like count to all clients viewing the event
    await sio.emit("update_like", {"eventid": eventid, "likes": new_likes_count})

