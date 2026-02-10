from . import sendlog, sendmail, detailsformat

def addevent(c, form_data: dict, owner_username: str):
    # List of expected fields
    field = ["eventname", "email", "starttime", "endtime", "eventdate", "enddate", "location", "category", "description", "username"]

    # Construct event_values.
    # Logic: iterate through 'field'. If key is 'username', use owner_username. Else get from form_data.
    event_values = []
    for f in field:
        if f == "username":
            event_values.append(owner_username)
        else:
            event_values.append(form_data.get(f))

    # Check if event already exists
    check = c.execute("SELECT * FROM eventdetail WHERE eventname=?", (event_values[0],))
    fetchall = check.fetchall()
    for ab in fetchall:
        # Strict check: if all fields match, it's a duplicate
        is_duplicate = True
        for i, f in enumerate(field):
            if str(ab[f]) != str(event_values[i]):
                is_duplicate = False
                break
        if is_duplicate:
            return "Event Already Exists"

    tuple_all = ", ".join(field)
    vals = ", ".join(["?"] * len(event_values))

    try:
        c.execute(f"INSERT INTO eventdetail({tuple_all}) VALUES ({vals})", tuple(event_values))

        lastid = c.execute("SELECT eventid FROM eventdetail ORDER BY eventid DESC LIMIT 1").fetchone()

        # We don't need to delete from eventreq here because app.py does it,
        # but leaving it as a safeguard doesn't hurt.
        try:
             c.execute("DELETE FROM eventreq WHERE eventname=? AND username=?", (event_values[0], owner_username))
        except:
             pass

        # Update userdetails 'events' column
        uud = c.execute("SELECT events FROM userdetails WHERE username=?", (owner_username, )).fetchone()
        if not uud or not uud["events"]:
            fe = []
        else:
            fe = uud["events"].split(",")

        fe.append(str(lastid["eventid"]))
        joint = ",".join(fe)
        c.execute("UPDATE userdetails SET events=? WHERE username=?", (joint, owner_username))

        # Fetch details for email
        eventdetails = c.execute("SELECT * FROM eventdetail WHERE eventid=?", (lastid["eventid"], )).fetchone()
        details = detailsformat(eventdetails)

        try:
            sendmail(event_values[1], "Event Approved", f'Congragulations\n\nYour Event is approved and now visible on Campaigns Page.\n\nEvent Details:\n\n{details}\n\nThank You!')
        except Exception as e:
            print(f"Mail error: {e}")

        sendlog(f"#EventAdd \nNew Event Added:\n{details}")
        return "Event added!"

    except Exception as e:
        print(f"Error adding event: {e}")
        return f"Error adding event: {str(e)}"


def addeventrequest(c, form_data: dict, session: dict):
    uuname, uemail = session.get("username"), session.get("email")
    if not uuname:
        return "Please Login First To Add Event."

    field = ["eventname", "email", "starttime", "endtime", "eventdate", "enddate", "location", "category", "description", "username"]

    event_values = []
    for f in field:
        if f == "username":
            event_values.append(uuname)
        elif f == "email":
            event_values.append(uemail)
        else:
            event_values.append(form_data.get(f))

    # Check if exists in active events
    check = c.execute("SELECT * FROM eventdetail WHERE eventname=?", (event_values[0],)).fetchone()
    if check:
         return "Event Already Exists"

    # Check if exists in pending requests
    check_req = c.execute("SELECT * FROM eventreq WHERE eventname=?", (event_values[0],)).fetchone()
    if check_req:
         return "Event Already Submitted! Please Wait For Approval"

    efields = ", ".join(field)
    vals = ", ".join(["?"] * len(event_values))

    c.execute(f"INSERT INTO eventreq({efields}) VALUES ({vals})", tuple(event_values))

    # Clear draft from session (except email/username)
    for x in field:
        if x not in ("email", "username"):
            session.pop(x, None)

    sendlog(f"#EventRequst \nNew Event Request: {event_values} by {uuname}")
    return "Event Registered ✅. Kindly wait for approval!"
