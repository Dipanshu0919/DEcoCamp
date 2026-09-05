"""
SahyogSutra Authentication Routes.
Handles user registration, login, logout, OTP requests, and password reset.
"""

import logging
from fastapi import APIRouter, Request, Form, Depends, Response, status
from fastapi.responses import RedirectResponse

from app.database import AsyncDB, get_db
from app.services.auth_service import (
    authenticate_user_credentials,
    create_and_send_otp,
    register_new_user,
    reset_user_password
)
from app.services.email_service import sendlog
from app.utils import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/signup")
async def handle_signup(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    cpassword: str = Form(...),
    nameofuser: str = Form(...),
    email: str = Form(...),
    signupotp: str = Form(...),
    db: AsyncDB = Depends(get_db)
):
    ok, msg = await register_new_user(
        username=username,
        password=password,
        cpassword=cpassword,
        name=nameofuser,
        email=email,
        otp=signupotp,
        db=db
    )
    if not ok:
        return Response(content=msg, media_type="text/plain")

    # Store strictly minimal authenticated identifier in session
    request.session["username"] = username.strip().lower()
    return Response(content=msg, media_type="text/plain")


@router.post("/login")
async def handle_login(
    request: Request,
    loginusername: str = Form(...),
    loginpassword: str = Form(...),
    db: AsyncDB = Depends(get_db)
):
    client_ip = request.client.host if request.client else "unknown"
    allowed, wait = check_rate_limit(f"login_{client_ip}", window_seconds=2)
    if not allowed:
        return Response(content=f"Too many attempts. Please wait {wait}s.", media_type="text/plain", status_code=429)

    ok, msg, user_info = await authenticate_user_credentials(loginusername, loginpassword, db)
    if not ok or not user_info:
        return Response(content=msg, media_type="text/plain")

    # Session minimization: Store only authenticated username and necessary UI settings
    request.session["username"] = user_info["username"]

    sendlog(f"User Login: {user_info['name']} ({user_info['username']})")
    return Response(content=msg, media_type="text/plain")


@router.get("/logout")
async def handle_logout(request: Request):
    username = request.session.pop("username", None)
    if username:
        sendlog(f"User Logout: {username}")
    request.session.clear()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/clearsession")
async def handle_clear_session(request: Request):
    request.session.clear()
    sendlog("Session Cleared")
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sendsignupotp")
async def handle_send_signup_otp(
    request: Request,
    email: str = Form(...),
    db: AsyncDB = Depends(get_db)
):
    client_ip = request.client.host if request.client else "unknown"
    allowed, wait = check_rate_limit(f"otp_{client_ip}", window_seconds=60)
    if not allowed:
        return Response(
            content=f"Please wait {wait} seconds before requesting another OTP.",
            media_type="text/plain",
            status_code=429
        )

    clean_email = email.strip().lower()
    existing = await db.fetchone(
        "SELECT username FROM userdetails WHERE email = ?",
        (clean_email,)
    )
    if existing:
        return Response(content="Email already exists! Please try a different email.", media_type="text/plain")

    ok, msg = await create_and_send_otp(
        email=clean_email,
        purpose="signup",
        db=db,
        subject="Signup OTP For SahyogSutra"
    )
    return Response(content=msg, media_type="text/plain")


@router.post("/sendforgetotp")
async def handle_send_forget_otp(
    request: Request,
    email: str = Form(...),
    db: AsyncDB = Depends(get_db)
):
    client_ip = request.client.host if request.client else "unknown"
    allowed, wait = check_rate_limit(f"otp_{client_ip}", window_seconds=60)
    if not allowed:
        return Response(
            content=f"Please wait {wait} seconds before requesting another OTP.",
            media_type="text/plain",
            status_code=429
        )

    clean_ident = email.strip().lower()
    user = await db.fetchone(
        "SELECT email FROM userdetails WHERE email = ? OR username = ?",
        (clean_ident, clean_ident)
    )
    if not user:
        return Response(content="Email/Username does not exist! Please try a different email.", media_type="text/plain")

    target_email = user["email"]
    ok, msg = await create_and_send_otp(
        email=target_email,
        purpose="reset",
        db=db,
        subject="Reset Password OTP For SahyogSutra"
    )
    return Response(content=msg, media_type="text/plain")


@router.post("/forgetpassword")
async def handle_forget_password(
    request: Request,
    forgetemail: str = Form(...),
    forgetotp: str = Form(...),
    newpassword: str = Form(...),
    confirmnewpassword: str = Form(...),
    db: AsyncDB = Depends(get_db)
):
    ok, msg = await reset_user_password(
        identifier=forgetemail,
        new_password=newpassword,
        confirm_password=confirmnewpassword,
        otp=forgetotp,
        db=db
    )
    return Response(content=msg, media_type="text/plain")

