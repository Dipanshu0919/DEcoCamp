"""
SahyogSutra Email & Notification Service.
Provides asynchronous email delivery via Resend and activity logging via Telegram.
Uses httpx without spawning raw threads per request.
"""

import asyncio
import datetime
import logging
from typing import Optional
import httpx

from app.config import IST, RESEND_API_KEY, TGBOTTOKEN

logger = logging.getLogger(__name__)

# Shared async client for non-blocking notifications
_http_client: Optional[httpx.AsyncClient] = None

def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=10.0)
    return _http_client

async def close_http_client():
    global _http_client
    if _http_client is not None:
        client = _http_client
        _http_client = None
        try:
            if not client.is_closed:
                await client.aclose()
        except Exception:
            pass


def detailsformat(details: dict) -> str:
    """Formats event dictionary for notifications."""
    if not details:
        return ""
    return (
        f"Event ID: {details.get('eventid', '')}\n"
        f"Event Name: {details.get('eventname', '')}\n"
        f"Email: {details.get('email', '')}\n"
        f"Start Time: {details.get('eventstarttime', '')}\n"
        f"End Time: {details.get('eventendtime', '')}\n"
        f"Event Date: {details.get('eventstartdate', '')}\n"
        f"End Date: {details.get('eventenddate', '')}\n"
        f"Location: {details.get('location', '')}\n"
        f"Category: {details.get('category', '')}\n"
        f"Description: {details.get('description', '')}\n"
        f"Username: {details.get('username', '')}"
    )


def get_otp_email_html(otp: str) -> str:
    """Returns responsive HTML email template containing the OTP."""
    return f"""
    <div style="font-family: Arial, sans-serif; background-color:#f4f6f8; padding:40px;">
        <div style="max-width:500px; margin:auto; background:white; border-radius:10px; padding:30px; text-align:center; box-shadow:0 4px 10px rgba(0,0,0,0.08);">
            <h2 style="color:#2c3e50; margin-bottom:10px;">
                SahyogSutra Verification
            </h2>
            <p style="font-size:16px; color:#555;">
                Use the one-time verification code below to verify your action.
            </p>
            <div style="
                margin:25px 0;
                padding:15px;
                font-size:32px;
                font-weight:bold;
                letter-spacing:6px;
                background:#f1f3f5;
                border-radius:8px;
                color:#2c3e50;
            ">
                {otp}
            </div>
            <p style="color:#777; font-size:14px;">
                This OTP is valid for 5 minutes and can only be used once.
            </p>
            <hr style="margin:25px 0; border:none; border-top:1px solid #eee;">
            <p style="font-size:13px; color:#999;">
                If you did not request this verification, please ignore this email.
            </p>
            <p style="font-size:14px; color:#2c3e50;">
                <strong>Team SahyogSutra</strong>
            </p>
        </div>
    </div>
    """


async def send_mail_async(receiver: str, subject: str, message: str, mail_type: str = "text"):
    """Sends an email asynchronously via Resend API."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY is not configured. Email to %s skipped.", receiver)
        return

    payload = {
        "from": "SahyogSutra Support <support@sahyogsutra.run.place>",
        "to": [str(receiver)],
        "subject": str(subject),
    }
    if mail_type == "html":
        payload["html"] = message
    else:
        payload["text"] = message

    try:
        client = get_http_client()
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json=payload
        )
        if resp.status_code >= 400:
            logger.error("Resend API error (%d): %s", resp.status_code, resp.text)
    except Exception as e:
        logger.error("Failed to send email to %s: %s", receiver, e)


async def send_log_async(message: str):
    """Sends activity log asynchronously to Telegram channel."""
    if not TGBOTTOKEN:
        logger.info("[LOG]: %s", message)
        return

    timestamp = datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    text = f"[{timestamp}]\n{message}"
    link = f"https://api.telegram.org/bot{TGBOTTOKEN}/sendMessage"
    params = {"chat_id": "-1002945250812", "text": text}

    try:
        client = get_http_client()
        resp = await client.get(link, params=params)
        if resp.status_code >= 400:
            logger.warning("Telegram log failed (%d): %s", resp.status_code, resp.text)
    except Exception as e:
        logger.warning("Telegram log error: %s", e)


def fire_and_forget(coro):
    """Schedules a coroutine to run in the current event loop without waiting."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        # If no running event loop, run once in new loop or ignore
        pass


def sendmail(receiver: str, subject: str, message: str, mail_type: str = "text"):
    """Compatibility wrapper that schedules email asynchronously without thread creation."""
    fire_and_forget(send_mail_async(receiver, subject, message, mail_type))


def sendlog(message: str):
    """Compatibility wrapper that schedules Telegram log asynchronously without thread creation."""
    fire_and_forget(send_log_async(message))

