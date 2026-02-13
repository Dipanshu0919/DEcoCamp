import os
import json
import random
import datetime
import time
import threading
import zoneinfo
import httpx
import asyncio
import sqlitecloud as sq
import csv
import io
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, Form, Depends, Response, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
import socketio
from dotenv import load_dotenv
from googletrans import Translator

# Import modules
from modules import sendlog, sendmail, sendmailthread, del_event, detailsformat
from modules import add_event as add_event_mod
from modules import delete_event as delete_event_mod

load_dotenv()

ist = zoneinfo.ZoneInfo("Asia/Kolkata")
translations_lock = threading.Lock()
active_events = 0

all_translations = {}
non_file_translations = {}

# --- In-Memory Stores ---
rate_limit_store: dict[str, float] = {}  # {ip: timestamp}

# --- Thread Pool for Translation (capped at 4 workers) ---
_translation_executor = ThreadPoolExecutor(max_workers=4)

# --- Campaigns Cache ---
_campaigns_cache: dict = {"data": None, "ts": 0}
CAMPAIGNS_CACHE_TTL = 30  # seconds

# --- Helper Functions ---

def load_translations():
    global all_translations
    try:
        if os.path.exists("translations.json"):
            with open("translations.json", "r", encoding="utf-8") as f:
                all_translations = json.load(f)
                print("Translations loaded successfully.")
                sendlog(f"Translations file loaded successfully with {len(all_translations)} texts.")
    except Exception as e:
        print(f"Translation file error: {e}")
        sendlog(f"Translation file error: {e}")

def save_translations():
    global all_translations
    try:
        with open("translations.json", "w", encoding="utf-8") as f:
            json.dump(all_translations, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving translation file: {e}")
        sendlog(f"Error saving translation file: {e}")

def translation_file_thread():
    while True:
        time.sleep(60)
        with translations_lock:
            save_translations()
            try:
                with open("translations_backup.json", "w", encoding="utf-8") as f:
                    json.dump(all_translations, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

def translate_thread(text, lang, save_file):
    global all_translations
    global non_file_translations
    try:
        t = Translator()
        translated = t.translate(text, dest=lang).text
        print(f"Translated '{text}' to '{translated}' in language '{lang}'")
    except Exception as e:
        print(f"Translation error: {e}")
        translated = text

    with translations_lock:
        translate_dict = non_file_translations if not save_file else all_translations
        existing = translate_dict.get(text, {})
        existing[lang] = translated
        translate_dict[text] = existing

def checkevent():
    while True:
        time.sleep(30 + random.randint(0, 10))
        try:
            pass
        except Exception as e:
            print(f"Check event loop error: {e}")
            time.sleep(60)

# --- Rate Limiter Helper ---
def check_rate_limit(ip: str, window: int = 30) -> tuple[bool, int]:
    """
    Returns (is_allowed, wait_seconds).
    Also prunes stale entries to prevent memory leak.
    """
    now = time.time()
    # Prune entries older than 2x the window
    expired = [k for k, v in rate_limit_store.items() if now - v > window * 2]
    for k in expired:
        del rate_limit_store[k]

    if ip in rate_limit_store:
        elapsed = now - rate_limit_store[ip]
        if elapsed < window:
            return False, int(window - elapsed)

    rate_limit_store[ip] = now
    return True, 0

# --- FastAPI Setup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    load_translations()
    threading.Thread(target=checkevent, name="CheckEventExist", daemon=True).start()
    threading.Thread(target=translation_file_thread, name="TranslationFileThread", daemon=True).start()
    yield
    # Shutdown
    _translation_executor.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)

# Session Middleware
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("FLASK_SECRET", "supersecretkey"))

# SocketIO Setup — single mount only
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Database Helpers ---
# SQLiteCloud is synchronous, so we wrap DB calls in run_in_executor
# to avoid blocking the async event loop.

def _sync_get_db_conn():
    """Opens a synchronous SQLiteCloud connection."""
    db = sq.connect(os.environ.get("SQLITECLOUD"))
    db.row_factory = sq.Row
    return db

async def run_query(query: str, params: tuple = (), fetchmode: str = "all"):
    """
    Run a single SELECT query asynchronously using run_in_executor.
    fetchmode: "all", "one", or "none" (for INSERT/UPDATE/DELETE)
    """
    loop = asyncio.get_event_loop()

    def _execute():
        db = _sync_get_db_conn()
        c = db.cursor()
        try:
            c.execute(query, params)
            if fetchmode == "all":
                result = c.fetchall()
            elif fetchmode == "one":
                result = c.fetchone()
            else:
                result = None
            db.commit()
            return result
        finally:
            db.close()

    return await loop.run_in_executor(None, _execute)

async def run_queries_parallel(*queries):
    """
    Run multiple (query, params, fetchmode) tuples in parallel.
    Returns results in the same order.
    """
    tasks = [run_query(q, p, f) for q, p, f in queries]
    return await asyncio.gather(*tasks)

# --- Synchronous DB for non-async contexts (SocketIO, background tasks) ---
def get_socket_db():
    db = _sync_get_db_conn()
    c = db.cursor()
    return db, c

# --- FastAPI DB Dependency (async-safe) ---
class AsyncDB:
    """Async-compatible DB wrapper for use in route handlers."""
    def __init__(self):
        self._db = _sync_get_db_conn()
        self._c = self._db.cursor()
        self._loop = asyncio.get_event_loop()

    def _run(self, fn):
        return self._loop.run_in_executor(None, fn)

    async def execute(self, query, params=()):
        def _do():
            self._c.execute(query, params)
            return self._c
        await self._run(_do)
        return self

    async def fetchone(self):
        def _do():
            return self._c.fetchone()
        return await self._run(_do)

    async def fetchall(self):
        def _do():
            return self._c.fetchall()
        return await self._run(_do)

    async def commit(self):
        def _do():
            self._db.commit()
        await self._run(_do)

    def close(self):
        self._db.close()

async def get_db():
    adb = AsyncDB()
    try:
        yield adb
        await adb.commit()
    finally:
        adb.close()

# --- Template Filters & Globals ---

def datetimeformat(value):
    if isinstance(value, str):
        try:
            return datetime.datetime.strptime(value, "%Y-%m-%d").strftime("%d %B %Y")
        except Exception:
            return value
    return value

templates.env.filters["datetimeformat"] = datetimeformat

def translate_text(text, lang=None, save_file=True):
    global all_translations
    global non_file_translations
    if not lang or lang == "en":
        return text
    combined_translations = {**all_translations, **non_file_translations}
    if not combined_translations.get(text) or not combined_translations.get(text).get(lang):
        # Use thread pool instead of spawning raw threads
        _translation_executor.submit(translate_thread, text, lang, save_file)
    translationss = all_translations if save_file else non_file_translations
    return translationss.get(text, {}).get(lang, text)

# --- Exception Handlers ---

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request, exc):
    return templates.TemplateResponse("error.html", {
        "request": request,
        "status_code": exc.status_code,
        "detail": exc.detail
    }, status_code=exc.status_code)

@app.exception_handler(500)
async def internal_exception_handler(request, exc):
    return templates.TemplateResponse("error.html", {
        "request": request,
        "status_code": 500,
        "detail": "Internal Server Error"
    }, status_code=500)

# --- Routes ---

@app.get("/")
async def home(request: Request, db: AsyncDB = Depends(get_db)):
    session = request.session
    currentuser = session.get("name", "User")
    currentuname = session.get("username")

    global active_events

    isadmin = False
    userdetails = {}
    top_organizers = []
    admin_stats = {}

    if currentuname:
        await db.execute("SELECT * FROM userdetails WHERE username=?", (currentuname,))
        ud = await db.fetchone()
        if ud:
            if ud["role"] == "admin":
                isadmin = True
                # Run all admin stat queries in parallel
                results = await run_queries_parallel(
                    ("SELECT COUNT(*) as count FROM userdetails", (), "one"),
                    ("SELECT COUNT(*) as count FROM eventreq", (), "one"),
                    ("SELECT COUNT(*) as count FROM eventdetail", (), "one"),
                )
                admin_stats = {
                    "total_users": results[0]["count"],
                    "pending_requests": results[1]["count"],
                    "active_threads": threading.active_count(),
                    "total_events": results[2]["count"]
                }
            userdetails = dict(ud)

    # Leaderboard Logic (Top 5 Organizers)
    await db.execute("SELECT name, username, events FROM userdetails")
    all_users = await db.fetchall()
    organizers = []
    for u in all_users:
        event_count = len(u["events"].split(",")) if u["events"] else 0
        if event_count > 0:
            organizers.append({"name": u["name"], "username": u["username"], "count": event_count})

    organizers.sort(key=lambda x: x["count"], reverse=True)
    top_organizers = organizers[:5]

    template_name = session.get("template", "index.html")
    user_lang = session.get("lang", "en")

    def bound_translate(text, save_file=True):
        return translate_text(text, lang=user_lang, save_file=save_file)

    return templates.TemplateResponse(request, template_name, {
        "active_events_length": active_events,
        "fullname": currentuser,
        "c_user": str(currentuname).strip(),
        "isadmin": bool(isadmin),
        "userdetails": userdetails,
        "translate": bound_translate,
        "user_language": user_lang,
        "fvalues": {},
        "top_organizers": top_organizers,
        "admin_stats": admin_stats
    })

@app.post("/sendsignupotp")
async def sendotp(request: Request, email: str = Form(...), db: AsyncDB = Depends(get_db)):
    client_ip = request.client.host
    allowed, wait = check_rate_limit(client_ip, window=30)
    if not allowed:
        return Response(
            content=f"Please wait {wait} seconds before requesting another OTP.",
            media_type="text/plain",
            status_code=429
        )

    otp = random.randint(1111, 9999)
    request.session["signupotp"] = otp

    await db.execute("SELECT * FROM userdetails WHERE email=?", (email,))
    checkexists = await db.fetchone()
    if checkexists:
        return Response(content="Email already exists! Please try different email.", media_type="text/plain")

    sendmailthread(email, "Signup OTP", f"Your signup OTP is {otp}.\nUse it to sign up in DEcoCamp\n\nThankyou :)")
    return Response(content=f"OTP Sent to {email}! Please check spam folder if can't find it.", media_type="text/plain")

@app.post("/setlanguage/{lang}")
async def setlanguage(request: Request, lang: str):
    request.session["lang"] = lang
    return Response(content="Language Set", media_type="text/plain")

@app.post("/generate_ai_description")
async def generate_ai_description(request: Request):
    client_ip = request.client.host
    allowed, wait = check_rate_limit(client_ip, window=10)
    if not allowed:
        return Response(content="Please wait a moment before generating again.", media_type="text/plain", status_code=429)

    try:
        form_data = await request.form()
        field = ["eventname", "starttime", "endtime", "eventstartdate", "enddate", "location", "category"]
        values = [[x, form_data.get(x)] for x in field if form_data.get(x)]
        u_lang = request.session.get("lang", "en")
        current_month = datetime.datetime.now().strftime("%B")

        content = f"""Generate a description based on following details in pure '{u_lang}' language.
        Context: The current month is {current_month}, so mention appropriate weather/preparations if needed.
        Details of event: {values}
        Generate total 4x descriptions (max 500 words each). Include hashtags. Reply strictly in JSON:
        {{"desc1": "Formal tone", "desc2": "Informal tone", "desc3": "Promotional tone", "desc4": "Entertaining/Fun tone"}}"""

        # Use httpx async client instead of blocking requests
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY')}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "nvidia/nemotron-nano-9b-v2:free",
                    "messages": [{"role": "user", "content": content}]
                }
            )

        data = response.json()
        output = data["choices"][0]["message"]["content"]

        # Clean up markdown code fences if present
        if "```json" in output:
            output = output.replace("```json", "").replace("```", "")

        to_json = json.loads(output.strip())
        return JSONResponse(content=to_json)

    except Exception as e:
        print(f"AI Description Generation Error: {e}")
        return Response(content="Error generating description. Please try again later.", media_type="text/plain", status_code=500)

@app.get("/group-chat/from-event/{eventid}")
async def group_chat_from_event(request: Request, eventid: int, db: AsyncDB = Depends(get_db)):
    currentuname = request.session.get("username", "anonymous")

    await db.execute("SELECT * FROM eventdetail WHERE eventid=?", (eventid,))
    eventdetail = await db.fetchone()
    if not eventdetail:
        return Response(content="No such event found.", media_type="text/plain")

    await db.execute("SELECT * FROM messages WHERE eventid=? ORDER BY time ASC", (eventid,))
    all_msgs = await db.fetchall()

    messages = [(x["username"], x["message"], x["time"]) for x in all_msgs] if all_msgs else []

    return templates.TemplateResponse(request, "groupchat.html", {
        "messages": messages,
        "eventid": eventid,
        "currentuname": currentuname,
        "eventname": eventdetail["eventname"]
    })

@app.get("/user/{username}")
async def user_profile(request: Request, username: str, db: AsyncDB = Depends(get_db)):
    await db.execute("SELECT * FROM userdetails WHERE username=?", (username,))
    userfulldetails = await db.fetchone()
    if not userfulldetails:
        raise HTTPException(status_code=404, detail="User not found")

    user_lang = request.session.get("lang", "en")

    def bound_translate(text, save_file=True):
        return translate_text(text, lang=user_lang, save_file=save_file)

    current_user = request.session.get("username")
    is_own_profile = (current_user == username)

    return templates.TemplateResponse(request, "userprofile.html", {
        "userdetails": dict(userfulldetails),
        "translate": bound_translate,
        "is_own_profile": is_own_profile
    })

@app.get("/changetemplate")
async def changetemplate(request: Request):
    ct = request.session.get("template", "index.html")
    request.session["template"] = "index2.html" if ct == "index.html" else "index.html"
    return Response(content="Template Changed", media_type="text/plain")

@app.get("/show_add_form")
async def show_add_form(request: Request):
    fi = ["eventname", "email", "starttime", "endtime", "eventstartdate", "enddate", "location", "category", "description"]
    fv = {x: request.session.get(x, "") for x in fi}

    user_lang = request.session.get("lang", "en")
    def bound_translate(text, save_file=True):
        return translate_text(text, lang=user_lang, save_file=save_file)

    categories = {}
    with open("events.json", "r") as f:
        categories = json.load(f)

    return templates.TemplateResponse(request, "addevent.html", {
        "fvalues": fv,
        "translate": bound_translate,
        "categories": categories
    })

@app.get("/show_campaigns")
async def show_campaigns(request: Request, db: AsyncDB = Depends(get_db)):
    global _campaigns_cache, active_events
    currentuname = request.session.get("username")
    user_lang = request.session.get("lang", "en")

    # Serve from cache if fresh
    if _campaigns_cache["data"] and time.time() - _campaigns_cache["ts"] < CAMPAIGNS_CACHE_TTL:
        cached = _campaigns_cache["data"]
        edetailslist = cached["edetailslist"]
        trending_events = cached["trending_events"]
        allevents = cached["allevents"]
        alleventscat = cached["alleventscat"]
        active_events = cached["active_events"]
    else:
        await db.execute("SELECT * FROM eventdetail")
        edetailslist = [dict(row) for row in await db.fetchall()]

        trending_events = sorted(edetailslist, key=lambda x: x['likes'], reverse=True)[:4]

        alleventscat = list({x["category"] for x in edetailslist})
        allevents = {}
        for x in edetailslist:
            allevents.setdefault(x["category"], []).append(x)

        active_events = sum(len(v) for v in allevents.values())

        _campaigns_cache = {
            "data": {
                "edetailslist": edetailslist,
                "trending_events": trending_events,
                "allevents": allevents,
                "alleventscat": alleventscat,
                "active_events": active_events,
            },
            "ts": time.time()
        }

    isadmin = False
    userdetails = {}
    if currentuname:
        await db.execute("SELECT * FROM userdetails WHERE username=?", (currentuname,))
        ud = await db.fetchone()
        if ud and ud["role"] == "admin":
            isadmin = True
        userdetails = dict(ud) if ud else {}

    viewuserevent = request.session.pop("vieweventusername", str(currentuname))
    ve = request.session.pop("viewyourevents", False)
    sortby = request.session.get("sortby", "eventstartdate")

    def bound_translate(text, save_file=True):
        return translate_text(text, lang=user_lang, save_file=save_file)

    return templates.TemplateResponse(request, "campaigns.html", {
        "allevents": allevents,
        "userdetails": userdetails,
        "viewyourevents": ve,
        "sortby": sortby,
        "isadmin": bool(isadmin),
        "c_user": str(currentuname).strip(),
        "viewuserevent": viewuserevent,
        "translate": bound_translate,
        "trending_events": trending_events
    })

@app.post("/viewyourevents/{username}")
async def viewyourevents(request: Request, username: str):
    request.session["viewyourevents"] = True
    request.session["vieweventusername"] = username
    return Response(content="OK", media_type="text/plain")

@app.post("/setsortby/{sortby}")
async def setsortby(request: Request, sortby: str):
    request.session["sortby"] = sortby
    return Response(content="Sort by set", media_type="text/plain")

@app.post("/signup")
async def signup(request: Request, db: AsyncDB = Depends(get_db)):
    form_data = await request.form()
    username = form_data.get("username").lower()
    password = form_data.get("password")
    cpassword = form_data.get("cpassword")
    name = form_data.get("nameofuser")
    email = form_data.get("email")
    otp = form_data.get("signupotp")

    # Run both existence checks in parallel
    results = await run_queries_parallel(
        ("SELECT username FROM userdetails WHERE username=?", (username,), "one"),
        ("SELECT email FROM userdetails WHERE email=?", (email,), "one"),
    )
    if results[0]:
        return Response(content="Username Already Exists", media_type="text/plain")
    if results[1]:
        return Response(content="Email Already Exists", media_type="text/plain")

    if str(request.session.get("signupotp")) != str(otp).strip():
        return Response(content="Wrong Signup OTP", media_type="text/plain")
    elif password != cpassword:
        return Response(content="Wrong Confirm Password", media_type="text/plain")
    elif len(password) < 8:
        return Response(content="Password must be at least 8 characters long", media_type="text/plain")
    else:
        await db.execute(
            "INSERT INTO userdetails(username, password, name, email) VALUES(?, ?, ?, ?)",
            (username, password, name, email)
        )
        request.session["username"] = username
        request.session["name"] = name
        request.session["email"] = email
        request.session.pop("signupotp", None)
        sendlog(f"New Signup: {name} ({username})")
        return Response(content="Signup Success ✅", media_type="text/plain")

@app.post("/login")
async def login(request: Request, db: AsyncDB = Depends(get_db)):
    form_data = await request.form()
    username = form_data.get("loginusername").lower()
    password = form_data.get("loginpassword")

    await db.execute(
        "SELECT * FROM userdetails WHERE username=? OR email=?",
        (username, username)
    )
    fetched = await db.fetchone()
    if not fetched:
        return Response(content="No username found", media_type="text/plain")
    elif password != fetched["password"]:
        return Response(content="Wrong Password", media_type="text/plain")
    else:
        request.session["username"] = fetched["username"]
        request.session["name"] = fetched["name"]
        request.session["email"] = fetched["email"]
        sendlog(f"User Login: {fetched['name']} ({fetched['username']})")
        return Response(content="Login Success ✅", media_type="text/plain")

@app.post("/addevent")
async def addnewevent(request: Request, db: AsyncDB = Depends(get_db)):
    form_data = await request.form()
    session_username = request.session.get("username")
    target_username = session_username

    if session_username:
        await db.execute("SELECT role FROM userdetails WHERE username=?", (session_username,))
        user_row = await db.fetchone()
        if user_row and user_row["role"] == "admin":
            if form_data.get("username"):
                target_username = form_data.get("username")
                try:
                    await db.execute(
                        "DELETE FROM eventreq WHERE eventname=? AND username=?",
                        (form_data.get("eventname"), target_username)
                    )
                except Exception as e:
                    print(f"Error cleaning up eventreq: {e}")

    # Module still uses sync cursor — wrap in executor
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None,
        lambda: add_event_mod.addevent(db._c, dict(form_data), target_username)
    )
    return Response(content=res, media_type="text/plain")

@app.post("/addeventreq")
async def addeventreq(request: Request, db: AsyncDB = Depends(get_db)):
    form_data = await request.form()
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None,
        lambda: add_event_mod.addeventrequest(db._c, dict(form_data), request.session)
    )
    return Response(content=res, media_type="text/plain")

@app.get("/show_pending_events")
async def pendingevents(request: Request, db: AsyncDB = Depends(get_db)):
    uname = request.session.get("username")
    if not uname:
        return Response(content="Login First", media_type="text/plain")

    await db.execute("SELECT * FROM userdetails WHERE username=?", (uname,))
    f = await db.fetchone()
    if f["role"] == "admin":
        await db.execute("SELECT * FROM eventreq")
        pe = [dict(row) for row in await db.fetchall()]

        categories = {}
        with open("events.json", "r") as f:
            categories = json.load(f)

        return templates.TemplateResponse(request, "pendingevents.html", {"pendingevents": pe, "categories": categories})
    else:
        return RedirectResponse(url="/", status_code=303)

@app.get("/deleteevent/{eventid}")
async def deleteevent(request: Request, eventid: int, db: AsyncDB = Depends(get_db)):
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None,
        lambda: delete_event_mod.delete_eventfromid(db._c, eventid, request.session)
    )
    # Invalidate campaigns cache on delete
    _campaigns_cache["ts"] = 0
    if res == "REDIRECT_HOME":
        return RedirectResponse(url="/", status_code=303)
    return Response(content=res, media_type="text/plain")

@app.get("/logout")
async def logout(request: Request):
    u = request.session.pop('username', None)
    n = request.session.pop('name', None)
    e = request.session.pop('email', None)
    sendlog(f"User Logout: {n} ({u}) {e}")
    return RedirectResponse(url="/", status_code=303)

@app.post("/save_draft")
async def save_draft(request: Request):
    form_data = await request.form()
    field = form_data.get("field")
    value = form_data.get("value")
    if value and value.strip():
        request.session[field] = value.strip()
    return Response(content="DRAFT", media_type="text/plain")

@app.get("/decline_event/{eventid}/{reason}")
async def decline_event(request: Request, eventid: int, reason: str, db: AsyncDB = Depends(get_db)):
    u = request.session.get("username")
    if u:
        await db.execute("SELECT * FROM userdetails WHERE username=?", (u,))
        f = await db.fetchone()
        if f["role"] == "admin":
            await db.execute("SELECT * FROM eventreq WHERE eventid=?", (eventid,))
            email_row = await db.fetchone()

            await db.execute("DELETE FROM eventreq WHERE eventid=?", (eventid,))

            await db.execute("SELECT * FROM sqlite_sequence WHERE name=?", ("eventreq",))
            seq = await db.fetchone()
            await db.execute(
                "UPDATE sqlite_sequence SET seq=? WHERE name=?",
                (seq["seq"], "eventdetail")
            )

            details = detailsformat(dict(email_row))
            sendmail(email_row['email'], "Event Declined",
                     f"We sorry to inform to you that your event was declined for following reason:\n{reason}.\n\nEvent Details:\n\n{details}\n\nThank You!")
            sendlog(f"#EventDecline \nEvent Declined by {u}\nReason: {reason}.\nEvent Details:\n\n{details}")

    await db.execute("SELECT eventid FROM eventreq")
    remaining = await db.fetchone()
    if remaining:
        return RedirectResponse(url="/#pending", status_code=303)
    else:
        return RedirectResponse(url="/", status_code=303)

@app.get("/clearsession")
async def clearsession(request: Request):
    request.session.clear()
    sendlog("Session Cleared")
    return RedirectResponse(url="/", status_code=303)

@app.get("/dummyevent")
async def dummyevent(request: Request):
    request.session["eventname"] = random.choice(["Community Tree Plantation", "Neighborhood Blood Donation Camp", "Local Cleanliness Drive"])
    request.session["description"] = "Join us for a community tree plantation drive to make our neighborhood greener and healthier!"
    request.session["location"] = random.choice(["Central Park", "Community Center", "City Hall", "Riverside Park", "Downtown Square"])
    request.session["category"] = random.choice(["Tree Plantation", "Blood Donation", "Cleanliness Drive"])
    request.session["eventstartdate"] = f"{random.randint(2025, 2028)}-{random.randint(10, 12):02d}-{random.randint(10, 28):02d}"
    request.session["enddate"] = f"{random.randint(2025, 2028)}-{random.randint(10, 12):02d}-{random.randint(10, 28):02d}"
    request.session["starttime"] = f"{random.randint(10, 12)}:{random.randint(10, 59)}"
    request.session["endtime"] = f"{random.randint(10, 12)}:{random.randint(10, 59)}"
    return RedirectResponse(url="/#add", status_code=303)

@app.get("/api")
async def api(request: Request, db: AsyncDB = Depends(get_db)):
    await db.execute("SELECT * FROM eventdetail")
    events = [dict(row) for row in await db.fetchall()]
    user = dict(request.session)
    user_details = "No user logged in"
    if user.get("username"):
        await db.execute("SELECT * FROM userdetails WHERE username=?", (user["username"],))
        ud = await db.fetchone()
        user_details = dict(ud) if ud else {}
    toreturn = {
        "active events": events,
        "current session including draft add event values": user,
        "current user": user_details
    }
    return JSONResponse(content=toreturn)

@app.get("/checkeventloop")
async def checkeventloop(db: AsyncDB = Depends(get_db)):
    try:
        await db.execute("SELECT * FROM eventdetail")
        ch = await db.fetchall()
        loop = asyncio.get_event_loop()
        for x in ch:
            try:
                etime = datetime.datetime.strptime(
                    f"{x['enddate']} {x['endtime']}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=ist)
                if etime <= datetime.datetime.now(ist):
                    await loop.run_in_executor(None, lambda: del_event(db._c, x["eventid"]))
                    details = detailsformat(dict(x))
                    sendmail(x["email"], "Event Ended",
                             f"Hey there your event was ended, so it has been deleted!\n\nEvent Details:\n\n{details}\n\nThank You!")
                    sendlog(f"#EventEnd \nEvent Ended at {etime.strftime('%Y-%m-%d %H:%M:%S')}.\nEvent Details:\n\n{details}")
                    # Invalidate campaigns cache
                    _campaigns_cache["ts"] = 0
            except Exception as e:
                print(f"Date parse error for event {x['eventid']}: {e}")

        return Response(content="<h1>CHECK EVENT LOOP COMPLETED</h1>", media_type="text/html")
    except Exception as e:
        text = f"Check event loop error: {e}"
        sendlog(text)
        return Response(content=text, media_type="text/plain")

@app.get("/download_ics/{eventid}")
async def download_ics(eventid: int, db: AsyncDB = Depends(get_db)):
    await db.execute("SELECT * FROM eventdetail WHERE eventid=?", (eventid,))
    event = await db.fetchone()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    try:
        start_dt = f"{event['eventstartdate'].replace('-', '')}T{event['starttime'].replace(':', '')}00"
        end_dt = f"{event['enddate'].replace('-', '')}T{event['endtime'].replace(':', '')}00"
    except Exception:
        start_dt = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        end_dt = start_dt

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//DEcoCamp//Events//EN
BEGIN:VEVENT
UID:decocamp-{eventid}
DTSTAMP:{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}
DTSTART:{start_dt}
DTEND:{end_dt}
SUMMARY:{event['eventname']}
DESCRIPTION:{event['description']}
LOCATION:{event['location']}
END:VEVENT
END:VCALENDAR"""

    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": f"attachment; filename=event_{eventid}.ics"}
    )

@app.get("/export_data")
async def export_data(request: Request, db: AsyncDB = Depends(get_db)):
    username = request.session.get("username")
    if not username:
        raise HTTPException(status_code=401, detail="Please login first")

    await db.execute("SELECT * FROM userdetails WHERE username=?", (username,))
    ud = await db.fetchone()
    if not ud:
        raise HTTPException(status_code=404, detail="User not found")

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["--- USER PROFILE ---"])
    writer.writerow(["Name", "Username", "Email", "Role", "Events IDs"])
    writer.writerow([ud["name"], ud["username"], ud["email"], ud["role"], ud["events"]])

    writer.writerow([])
    writer.writerow(["--- CREATED EVENTS ---"])
    if ud["events"]:
        event_ids = ud["events"].split(",")
        writer.writerow(["Event ID", "Name", "Location", "Category", "Date", "Description"])
        for eid in event_ids:
            await db.execute("SELECT * FROM eventdetail WHERE eventid=?", (eid,))
            ev = await db.fetchone()
            if ev:
                writer.writerow([ev["eventid"], ev["eventname"], ev["location"], ev["category"], ev["eventstartdate"], ev["description"]])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=decocamp_data_{username}.csv"}
    )

# --- SocketIO Events ---

@sio.on("add_grp_msg")
async def add_group_msg(sid, data):
    username = data["username"]
    message = data["message"]
    eventid = data["eventid"]
    msg_time = datetime.datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")

    loop = asyncio.get_event_loop()

    def _insert():
        db, c = get_socket_db()
        try:
            c.execute(
                "INSERT INTO messages(eventid, username, message, time) VALUES(?, ?, ?, ?)",
                (eventid, username, message, msg_time)
            )
            db.commit()
        finally:
            db.close()

    await loop.run_in_executor(None, _insert)
    await sio.emit("new_message", {
        "eventid": eventid,
        "username": username,
        "message": message,
        "time": msg_time
    })

@sio.on("addeventlike")
async def add_like(sid, data):
    eventid = data["eventid"]
    byuser = data["byuser"]
    like_type = data["type"]  # renamed from 'type' to avoid shadowing builtin

    loop = asyncio.get_event_loop()
    new_likes = 0

    def _update_like():
        nonlocal new_likes
        db, c = get_socket_db()
        try:
            ud = c.execute("SELECT * FROM userdetails WHERE username=?", (byuser,)).fetchone()
            liked_events = ud["likes"].split(",") if ud["likes"] else []

            if like_type == "add":
                if str(eventid) not in liked_events:
                    liked_events.append(str(eventid))
                    c.execute("UPDATE eventdetail SET likes = likes + 1 WHERE eventid=?", (eventid,))
            else:
                if str(eventid) in liked_events:
                    liked_events.remove(str(eventid))
                    c.execute("UPDATE eventdetail SET likes = likes - 1 WHERE eventid=?", (eventid,))

            new_likes_str = ",".join(liked_events)
            c.execute("UPDATE userdetails SET likes=? WHERE username=?", (new_likes_str, byuser))
            new_likes = c.execute("SELECT likes FROM eventdetail WHERE eventid=?", (eventid,)).fetchone()["likes"]
            db.commit()
        finally:
            db.close()

    await loop.run_in_executor(None, _update_like)
    await sio.emit("update_like", {"eventid": eventid, "likes": new_likes})

# --- Final ASGI App: Single SocketIO mount ---
app = socketio.ASGIApp(sio, app)

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))

    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
