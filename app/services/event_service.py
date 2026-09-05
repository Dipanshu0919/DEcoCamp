"""
SahyogSutra Event Service.
Handles event registration requests, approval, rejection, deletion,
and automated background processing of expired events.
"""

import datetime
import logging
from typing import Optional, Tuple, Dict, Any, List

from app.config import IST
from app.services.email_service import send_mail_async, sendlog, detailsformat

logger = logging.getLogger(__name__)

EVENT_FIELDS = [
    "eventname",
    "email",
    "eventstarttime",
    "eventendtime",
    "eventstartdate",
    "eventenddate",
    "location",
    "category",
    "description",
    "username"
]


async def create_event_request(
    form_data: dict,
    username: str,
    email: str,
    db
) -> Tuple[bool, str]:
    """Saves a new user event submission into eventreq for admin approval."""
    if not username:
        return False, "Please login first to submit an event."

    event_name = str(form_data.get("eventname") or "").strip()
    if not event_name:
        return False, "Event name is required."

    event_values = []
    for f in EVENT_FIELDS:
        if f == "username":
            event_values.append(username)
        elif f == "email":
            event_values.append(email)
        else:
            val = str(form_data.get(f) or "").strip()
            event_values.append(val)

    # Check for duplicate in approved events
    existing = await db.fetchone(
        "SELECT eventid FROM eventdetail WHERE eventname = ? AND eventstartdate = ? AND location = ?",
        (event_name, form_data.get("eventstartdate"), form_data.get("location"))
    )
    if existing:
        return False, "An identical event already exists in active campaigns."

    # Check for duplicate in pending requests
    pending = await db.fetchone(
        "SELECT eventid FROM eventreq WHERE eventname = ? AND username = ?",
        (event_name, username)
    )
    if pending:
        return False, "This event has already been submitted and is awaiting approval."

    fields_str = ", ".join(EVENT_FIELDS)
    placeholders = ", ".join(["?"] * len(EVENT_FIELDS))

    await db.execute(
        f"INSERT INTO eventreq ({fields_str}) VALUES ({placeholders})",
        tuple(event_values)
    )
    await db.commit()

    sendlog(f"#EventRequest\nNew Event Request: '{event_name}' by {username}")
    return True, "Event Registered. Kindly wait for approval!"


async def approve_event_request(
    form_data: dict,
    admin_username: str,
    db
) -> Tuple[bool, str]:
    """Approves a pending event, moving it to eventdetail and notifying the organizer."""
    target_username = form_data.get("username")
    event_id = form_data.get("eventid")

    event_values = []
    for f in EVENT_FIELDS:
        event_values.append(str(form_data.get(f) or "").strip())

    fields_str = ", ".join(EVENT_FIELDS)
    placeholders = ", ".join(["?"] * len(EVENT_FIELDS))

    try:
        await db.execute(
            f"INSERT INTO eventdetail ({fields_str}) VALUES ({placeholders})",
            tuple(event_values)
        )

        last_row = await db.fetchone(
            "SELECT eventid FROM eventdetail ORDER BY eventid DESC LIMIT 1"
        )
        new_event_id = last_row["eventid"] if last_row else None

        # Clean up matched request
        if event_id:
            await db.execute("DELETE FROM eventreq WHERE eventid = ?", (event_id,))
        else:
            await db.execute(
                "DELETE FROM eventreq WHERE eventname = ? AND username = ?",
                (form_data.get("eventname"), target_username)
            )

        # Update user's event list
        if target_username and new_event_id:
            user_row = await db.fetchone(
                "SELECT events FROM userdetails WHERE username = ?",
                (target_username,)
            )
            current_events = user_row["events"].split(",") if user_row and user_row["events"] else []
            if str(new_event_id) not in current_events:
                current_events.append(str(new_event_id))
            await db.execute(
                "UPDATE userdetails SET events = ? WHERE username = ?",
                (",".join(current_events), target_username)
            )

        await db.commit()

        # Send notifications
        event_details = await db.fetchone("SELECT * FROM eventdetail WHERE eventid = ?", (new_event_id,))
        details_txt = detailsformat(event_details or {})

        organizer_email = form_data.get("email")
        if organizer_email:
            await send_mail_async(
                organizer_email,
                "Event Approved - SahyogSutra",
                f"Congratulations!\n\nYour event has been approved and is now live.\n\nEvent Details:\n\n{details_txt}\n\nThank You!"
            )

        sendlog(f"#EventApprove\nEvent Approved by {admin_username}:\n{details_txt}")
        return True, "Event approved successfully!"

    except Exception as e:
        logger.error("Error approving event: %s", e)
        return False, f"Error approving event: {e}"


async def decline_event_request(
    event_id: int,
    reason: str,
    admin_username: str,
    db
) -> Tuple[bool, str]:
    """Declines a pending event and notifies the submitter."""
    row = await db.fetchone("SELECT * FROM eventreq WHERE eventid = ?", (event_id,))
    if not row:
        return False, "Pending event not found."

    await db.execute("DELETE FROM eventreq WHERE eventid = ?", (event_id,))
    await db.commit()

    details_txt = detailsformat(row)
    if row.get("email"):
        await send_mail_async(
            row["email"],
            "Event Submission Declined - SahyogSutra",
            f"We are sorry to inform you that your event submission was declined.\n\nReason: {reason}\n\nEvent Details:\n\n{details_txt}\n\nThank You!"
        )

    sendlog(f"#EventDecline\nEvent {event_id} declined by {admin_username}. Reason: {reason}")
    return True, "Event request declined."


async def delete_event_by_id(
    event_id: int,
    requester_username: str,
    is_admin: bool,
    db
) -> Tuple[bool, str]:
    """Deletes an active event, moves it to endedevent, and cleans up relations."""
    event = await db.fetchone("SELECT * FROM eventdetail WHERE eventid = ?", (event_id,))
    if not event:
        return False, "Event not found"

    # Authorization check
    if event["username"] != requester_username and not is_admin:
        return False, "Unauthorized: You do not own this event."

    try:
        # Move to endedevent table
        insert_ended = """
            INSERT INTO endedevent (eventid, eventname, email, eventstarttime, eventendtime,
                                   eventstartdate, eventenddate, location, category, description,
                                   username, likes)
            SELECT eventid, eventname, email, eventstarttime, eventendtime,
                   eventstartdate, eventenddate, location, category, description,
                   username, likes
            FROM eventdetail WHERE eventid = ?
        """
        await db.execute(insert_ended, (event_id,))
        await db.execute("DELETE FROM eventdetail WHERE eventid = ?", (event_id,))
        await db.execute("DELETE FROM messages WHERE eventid = ?", (event_id,))

        # Update user's events column
        owner_username = event["username"]
        ud = await db.fetchone("SELECT events, likes, email, name FROM userdetails WHERE username = ?", (owner_username,))
        if ud and ud.get("events"):
            ev_list = [x for x in ud["events"].split(",") if x != str(event_id)]
            new_events = ",".join(ev_list) if ev_list else None
            await db.execute("UPDATE userdetails SET events = ? WHERE username = ?", (new_events, owner_username))

        # Update user's likes column
        if ud and ud.get("likes"):
            likes_list = [x for x in ud["likes"].split(",") if x != str(event_id)]
            new_likes = ",".join(likes_list) if likes_list else None
            await db.execute("UPDATE userdetails SET likes = ? WHERE username = ?", (new_likes, owner_username))

        await db.commit()

        details_txt = detailsformat(event)
        if ud and ud.get("email") and requester_username != owner_username:
            await send_mail_async(
                ud["email"],
                "Event Deleted - SahyogSutra",
                f"Your event '{event['eventname']}' was removed by an administrator.\n\nDetails:\n{details_txt}"
            )

        sendlog(f"#EventDelete\nEvent {event_id} ('{event['eventname']}') deleted by {requester_username}")
        return True, "REDIRECT_HOME"

    except Exception as e:
        logger.error("Error deleting event %s: %s", event_id, e)
        return False, f"Error deleting event: {e}"


async def process_expired_events(db):
    """
    Direct asynchronous cleanup of expired events.
    Called periodically by a single background asyncio task.
    Eliminates internal HTTP loopback calls.
    """
    try:
        events = await db.fetchall("SELECT * FROM eventdetail")
        now_dt = datetime.datetime.now(IST)

        for ev in events:
            try:
                end_str = f"{ev['eventenddate']} {ev['eventendtime']}"
                etime = datetime.datetime.strptime(end_str, "%Y-%m-%d %H:%M").replace(tzinfo=IST)

                if etime <= now_dt:
                    logger.info("Auto-archiving expired event %s ('%s')", ev["eventid"], ev["eventname"])
                    await delete_event_by_id(ev["eventid"], "System-AutoExpire", is_admin=True, db=db)
                    details_txt = detailsformat(ev)
                    if ev.get("email"):
                        await send_mail_async(
                            ev["email"],
                            "Event Ended - SahyogSutra",
                            f"Your event has concluded and was moved to the archive.\n\nEvent Details:\n{details_txt}\n\nThank you!"
                        )
                    sendlog(f"#EventEnded\nEvent '{ev['eventname']}' concluded at {etime.strftime('%Y-%m-%d %H:%M')}.")
            except Exception as parse_err:
                logger.debug("Failed parsing end date for event %s: %s", ev.get("eventid"), parse_err)
    except Exception as e:
        logger.error("Error in process_expired_events: %s", e)

