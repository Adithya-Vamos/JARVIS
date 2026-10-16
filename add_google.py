# Run once inside the JARVIS folder:  python add_google.py
#
# ADDS: Gmail + Google Calendar read-out (READ-ONLY: Jarvis can never send, delete or change anything)
#   "connect google"                      -> one-time sign-in in your browser
#   "check my email" / "any new emails"   -> unread count + who sent the newest ones
#   "read my latest email"                -> reads the preview line of the newest unread email
#   "what's on my calendar today" / "tomorrow" / "what's my next class"
#   The morning briefing also includes today's events and your unread count.
#   "disconnect google" deletes the saved sign-in.
#
# ONE-TIME SETUP (about 5 minutes, free) is printed when this script finishes.
# Needs: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
# Needs the earlier patches (upgrade_jarvis.py, upgrade_vision.py, fix_time_quiet.py, upgrade_suite.py).
# Makes a backup first (main.py.bak). If anything does not fit, it changes NOTHING.

import os
import shutil
import sys

PATH = "main.py"

if not os.path.exists(PATH):
    print("main.py not found. Run this from inside the JARVIS folder.")
    sys.exit(1)

with open(PATH, "r", encoding="utf-8") as f:
    src = f.read()

if "def tool_check_email" in src:
    print("Already installed. Nothing to do.")
    sys.exit(0)

if "def build_briefing" not in src:
    print("Run upgrade_suite.py first (and the earlier patches), then run this one.")
    sys.exit(1)


def fail(what):
    print("Could not find the right spot in main.py for:", what)
    print("Nothing was changed.")
    sys.exit(1)


def swap(old, new):
    global src
    if src.count(old) != 1:
        fail(old.strip()[:60])
    src = src.replace(old, new)


swap('HOME_CITY = "Bangalore"   # used when you ask for the weather without a city\n',
     'HOME_CITY = "Bangalore"   # used when you ask for the weather without a city\n'
     'GOOGLE_CREDENTIALS = os.path.join(app_dir(), "google_credentials.json")  # you download this once (see setup)\n'
     'GOOGLE_TOKEN = os.path.join(app_dir(), "jarvis_google_token.json")      # Jarvis saves your sign-in here\n')

NEW_CODE = r'''# ---------------------------------------------------------------- Gmail + Google Calendar (read-only)

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
                 "https://www.googleapis.com/auth/calendar.readonly"]
GOOGLE_SETUP_HINT = ("Google is not connected yet. Save google_credentials.json in the Jarvis folder, "
                     "install the Google packages, then say connect Google.")
GOOGLE_STATE = {"signing_in": False}


class GoogleNotReady(Exception):
    pass


def google_service(name, version):
    """Build a Gmail/Calendar client from the saved sign-in. Raises GoogleNotReady with a spoken reason."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        raise GoogleNotReady("The Google packages are not installed. Run: pip install google-api-python-client "
                             "google-auth-oauthlib google-auth-httplib2")
    if not os.path.exists(GOOGLE_TOKEN):
        raise GoogleNotReady(GOOGLE_SETUP_HINT if not os.path.exists(GOOGLE_CREDENTIALS)
                             else "You are not signed in to Google yet. Say connect Google.")
    try:
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN, GOOGLE_SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(GOOGLE_TOKEN, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            else:
                raise GoogleNotReady("Your Google sign-in ran out. Say connect Google again.")
    except GoogleNotReady:
        raise
    except Exception as e:
        print("Google sign-in check error:", repr(e)[:200])
        if type(e).__name__ == "RefreshError":  # Google refused the saved sign in (revoked or expired)
            raise GoogleNotReady("Your Google sign-in expired. Say connect Google again.")
        raise GoogleNotReady("I could not reach Google right now.")
    return build(name, version, credentials=creds, cache_discovery=False)


def google_sign_in_worker():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS, GOOGLE_SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent", authorization_prompt_message="",
                                      success_message="Jarvis is connected to Google. You can close this tab.")
        with open(GOOGLE_TOKEN, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        announce("Google is connected. Try saying check my email, or what's on my calendar.")
    except Exception as e:
        print("Google sign-in error:", repr(e))
        announce("The Google sign in did not finish. Say connect Google to try again.")
    finally:
        GOOGLE_STATE["signing_in"] = False


def tool_connect_google():
    if not os.path.exists(GOOGLE_CREDENTIALS):
        return GOOGLE_SETUP_HINT
    try:
        import google_auth_oauthlib  # noqa: F401
    except ImportError:
        return "The Google packages are not installed. Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
    if GOOGLE_STATE["signing_in"]:
        return "The Google sign in is already open in your browser."
    GOOGLE_STATE["signing_in"] = True
    threading.Thread(target=google_sign_in_worker, daemon=True).start()
    return "Opening Google sign in in your browser. Approve it there. I only ask to read, never to send or change anything."


def tool_disconnect_google():
    try:
        os.remove(GOOGLE_TOKEN)
    except FileNotFoundError:
        return "Google was not connected."
    return "Done. I forgot your Google sign in."


def sender_name(header):
    import email.utils
    name, addr = email.utils.parseaddr(header or "")
    return (name or addr.split("@")[0] or "someone").strip()


def tool_check_email(count=3):
    try:
        gmail = google_service("gmail", "v1")
        unread = gmail.users().labels().get(userId="me", id="INBOX").execute().get("messagesUnread", 0)
        if not unread:
            return "Your inbox has no unread emails."
        ids = gmail.users().messages().list(userId="me", q="is:unread in:inbox", maxResults=int(count)).execute().get("messages", [])
        lines = []
        for m in ids:
            msg = gmail.users().messages().get(userId="me", id=m["id"], format="metadata",
                                               metadataHeaders=["From", "Subject"]).execute()
            h = {x["name"].lower(): x["value"] for x in msg.get("payload", {}).get("headers", [])}
            lines.append(f"{sender_name(h.get('from'))}: {(h.get('subject') or 'no subject')[:80]}")
        return f"You have {plural(unread, 'unread email')}. Newest: " + "; ".join(lines) + "." if lines else f"You have {plural(unread, 'unread email')}."
    except GoogleNotReady as e:
        return str(e)
    except Exception as e:
        print("Gmail error:", repr(e))
        return "I could not reach Gmail right now."


def tool_read_email():
    try:
        gmail = google_service("gmail", "v1")
        ids = gmail.users().messages().list(userId="me", q="in:inbox", maxResults=1).execute().get("messages", [])
        if not ids:
            return "Your inbox is empty."
        msg = gmail.users().messages().get(userId="me", id=ids[0]["id"], format="metadata",
                                           metadataHeaders=["From", "Subject"]).execute()
        h = {x["name"].lower(): x["value"] for x in msg.get("payload", {}).get("headers", [])}
        snippet = (msg.get("snippet") or "").replace("&#39;", "'").replace("&quot;", '"').replace("&amp;", "&")
        return f"Latest email from {sender_name(h.get('from'))}, subject {h.get('subject') or 'none'}. It starts: {snippet[:300]}"
    except GoogleNotReady as e:
        return str(e)
    except Exception as e:
        print("Gmail error:", repr(e))
        return "I could not reach Gmail right now."


def event_clock(event):
    start = event.get("start", {})
    if "dateTime" in start:
        t = datetime.datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        return t.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")
    return "all day"


def tool_check_calendar(day="today"):
    day = str(day or "today").lower()
    try:
        cal = google_service("calendar", "v3")
        now = ist_now()
        if day == "next":
            lo, hi = now, now + datetime.timedelta(days=30)
        else:
            base = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if day == "tomorrow":
                base += datetime.timedelta(days=1)
            lo, hi = base, base + datetime.timedelta(days=1)
        events = cal.events().list(calendarId="primary", timeMin=lo.isoformat(), timeMax=hi.isoformat(), singleEvents=True,
                                   orderBy="startTime", maxResults=1 if day == "next" else 8).execute().get("items", [])
        if day == "next":
            if not events:
                return "You have nothing coming up in the next 30 days."
            e = events[0]
            when = datetime.datetime.fromisoformat(e["start"]["dateTime"].replace("Z", "+00:00")).astimezone(LOCAL_TZ) if "dateTime" in e["start"] else None
            label = describe_due(when, now, delta=False) if when else "all day " + e["start"]["date"]
            return f"Your next event is {e.get('summary') or 'busy'} at {label}."
        if not events:
            return f"You have nothing on your calendar {day}."
        listing = "; ".join(f"{e.get('summary') or 'busy'} at {event_clock(e)}" if event_clock(e) != "all day"
                            else f"{e.get('summary') or 'busy'}, all day" for e in events)
        return f"You have {plural(len(events), 'event')} {day}: " + listing + "."
    except GoogleNotReady as e:
        return str(e)
    except Exception as e:
        print("Calendar error:", repr(e))
        return "I could not reach your calendar right now."


def calendar_brief():
    """For the morning briefing. Says nothing at all if Google is not connected."""
    if not os.path.exists(GOOGLE_TOKEN):
        return ""
    parts = []
    cal = tool_check_calendar("today")
    if cal.startswith("You have"):
        parts.append(cal)
    try:
        gmail = google_service("gmail", "v1")
        unread = gmail.users().labels().get(userId="me", id="INBOX").execute().get("messagesUnread", 0)
        if unread:
            parts.append(f"You have {plural(unread, 'unread email')}.")
    except Exception as e:
        print("Briefing mail error:", repr(e))
    return " ".join(parts)


def google_command(text):
    if re.search(r"\b(?:disconnect|unlink|sign out of|log out of|forget)\b.*\bgoogle\b", text):
        return tool_disconnect_google()
    if re.search(r"\b(?:connect|link|sign in to|log in to|set up|setup)\b.*\b(?:google|gmail|google calendar)\b", text):
        return tool_connect_google()
    if re.search(r"\b(?:read|tell me)\b.*\b(?:latest|last|newest|first|recent) (?:email|e-mail|mail)\b", text):
        return tool_read_email()
    if re.search(r"^(?:check|read|show|any|what'?s in|how many|do i have)\b.*\b(?:emails?|e-mails?|inbox|gmail|mail)\b", text) \
            and not re.search(r"\b(?:send|write|compose|draft|delete|reply)\b", text):
        return tool_check_email()
    m = re.search(r"\b(?:calendar|schedule|agenda)\b(?: for)?(?: (today|tomorrow))?$", text)
    if m and re.match(r"(?:what(?:'s| is| are)|show|check|read|tell me|how does|what does)", text):
        return tool_check_calendar(m.group(1) or "today")
    m = re.fullmatch(r"(?:do i have|have i got|am i free|what do i have)(?: any| anything)?(?: (?:meetings?|events?|classes|appointments?|lectures?))?(?: on)?(?: (today|tomorrow))?", text)
    if m and (m.group(1) or "meeting" in text or "event" in text or "class" in text or "lecture" in text or "appointment" in text):
        return tool_check_calendar(m.group(1) or "today")
    if re.fullmatch(r"what(?:'s| is) my next (?:event|meeting|class|appointment|lecture)", text):
        return tool_check_calendar("next")
    return None


'''

swap('STR = {"type": "STRING"}\n', NEW_CODE + 'STR = {"type": "STRING"}\n')

swap('    action = media_action(text)\n',
     '    google_reply = google_command(text)\n    if google_reply:\n        return google_reply\n\n    action = media_action(text)\n')

swap(']}]\n\nFUNCTIONS = {\n',
     '''    {"name": "check_email", "description": "Tell the user how many unread emails they have and who sent the newest ones (Gmail, read-only)."},
    {"name": "read_latest_email", "description": "Read out the preview of the newest email in the inbox."},
    {"name": "check_calendar", "description": "Read the user's Google Calendar. day is today, tomorrow or next (the next upcoming event).",
     "parameters": params({"day": STR}, [])},
    {"name": "connect_google", "description": "Start the one-time Google sign in for email and calendar."},
]}]

FUNCTIONS = {
''')

swap('    "open_folder": tool_open_folder,\n',
     '''    "open_folder": tool_open_folder,
    "check_email": tool_check_email,
    "read_latest_email": tool_read_email,
    "check_calendar": tool_check_calendar,
    "connect_google": tool_connect_google,
''')

try:
    ignore = ".gitignore"
    existing = open(ignore, encoding="utf-8").read() if os.path.exists(ignore) else ""
    add = [n for n in ("google_credentials.json", "jarvis_google_token.json") if n not in existing]
    if add:
        with open(ignore, "a", encoding="utf-8") as f:
            f.write(("" if existing.endswith("\n") or not existing else "\n") + "\n".join(add) + "\n")
except OSError:
    pass

try:
    compile(src, PATH, "exec")
except SyntaxError as e:
    print("The patched code did not compile:", e)
    print("Nothing was changed.")
    sys.exit(1)

shutil.copy(PATH, "main.py.bak")
with open(PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Done. Added: Gmail and Google Calendar read-out (read-only).")
print("Backup saved as main.py.bak")
print()
print("ONE-TIME GOOGLE SETUP:")
print(" 1. In the terminal run:  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
print(" 2. Go to console.cloud.google.com, create a project, then APIs & Services > Library:")
print("    enable 'Gmail API' and 'Google Calendar API'.")
print(" 3. APIs & Services > OAuth consent screen: choose External, fill the name and your email,")
print("    add your own Gmail address under Test users.")
print("    Then press PUBLISH APP (In production). If you leave it in Testing, the sign in may expire every 7 days.")
print(" 4. APIs & Services > Credentials > Create credentials > OAuth client ID > Desktop app.")
print("    Download the JSON and save it in the JARVIS folder as google_credentials.json")
print(" 5. Start Jarvis and say: connect Google. Approve in the browser (an 'unverified app' warning is normal for your own app).")
