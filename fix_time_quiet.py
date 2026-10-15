# Run once inside the JARVIS folder:  python fix_time_quiet.py
#
# FIXES
#   1. TIME: Jarvis now always uses India time (IST, +05:30) from a live clock. Every way of asking the
#      time or date is answered instantly from that clock, the AI has a get_time tool, and time/date
#      answers are never kept in the chat memory (that is what made it repeat an old time).
#   2. REMINDERS: the exact time is worked out by Python, not by the AI. "remind me at 6 pm to call mom",
#      "remind me tomorrow at 9 am to ...", "remind me in 45 minutes to ...", "remind me to ... at 6 pm".
#      Jarvis reads back the exact time ("Reminder set for 6:00 PM today, in 5 hours 10 minutes: call mom").
#      It checks every second, and a reminder that was late (PC asleep) says when it was due.
#   3. QUIET MODE: "go to quiet mode", "go quiet", "be quiet", "switch to quite mode"... all work,
#      and the AI has a set_quiet_mode tool as a backup.
#   4. CLICKING QUIET / WAKE UP in the HUD now switches the microphone listener at once (before, it kept
#      listening the old way, so "wake up" was ignored). Plain "wake up" works in quiet mode.
#   5. The terminal prints [command] <what Jarvis understood> so any miss is easy to diagnose.
#
# Needs the earlier patches (upgrade_jarvis.py and upgrade_vision.py).
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

if "def ist_now" in src:
    print("Already fixed. Nothing to do.")
    sys.exit(0)

if "def media_action" not in src or "def tool_look_at_screen" not in src:
    print("Run upgrade_jarvis.py and upgrade_vision.py first, then run this one.")
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


def replace_block(start, end, new):
    """Replace everything from `start` up to (not including) `end`."""
    global src
    if src.count(start) != 1 or src.count(end) != 1:
        fail(start)
    a = src.index(start)
    b = src.index(end)
    if b < a:
        fail(start)
    src = src[:a] + new + src[b:]


# ------------------------------------------------------------------ settings

swap('VISION_HIDE_HUD = True    # hide the Jarvis window for a moment so it does not cover your screen\n',
     'VISION_HIDE_HUD = True    # hide the Jarvis window for a moment so it does not cover your screen\n'
     'LOCAL_TZ = datetime.timezone(datetime.timedelta(hours=5, minutes=30), "IST")  # India Standard Time (no daylight saving)\n')

swap('    now = datetime.datetime.now().strftime("%A, %d %B %Y, %I:%M %p")\n',
     '    now = ist_now().strftime("%A, %d %B %Y, %I:%M %p")  # always India time (IST)\n')

swap('        + f" Current date and time: {now}. "\n',
     '        + f" Current date and time in India (IST): {now}. This is the only correct time: never reuse a "\n'
     '        + "time or date from earlier in the conversation, and call get_time for any question about the time or date. "\n')

# ------------------------------------------------------------------ reminders: exact times worked out by Python

swap('REMINDER_POLL = 5  # seconds between checks\n',
     'REMINDER_POLL = 1  # seconds between checks (reminders fire within a second of their time)\n')

REMINDERS = r'''def ist_now():
    """The exact time right now in India (IST), read from the clock every time it is asked."""
    return datetime.datetime.now(LOCAL_TZ)


def human_delta(seconds):
    """93 -> '2 minutes', 7980 -> '2 hours 13 minutes'."""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} second" + ("" if seconds == 1 else "s")
    minutes = int(round(seconds / 60))
    days, rest = divmod(minutes, 1440)
    hours, minutes = divmod(rest, 60)
    parts = []
    if days:
        parts.append(f"{days} day" + ("" if days == 1 else "s"))
    if hours:
        parts.append(f"{hours} hour" + ("" if hours == 1 else "s"))
    if minutes:
        parts.append(f"{minutes} minute" + ("" if minutes == 1 else "s"))
    return " ".join(parts)


def describe_due(due, base=None, delta=True):
    """'6:00 PM today, in 5 hours 10 minutes' (so you can hear if Jarvis understood you)."""
    base = base or ist_now()
    due = due.astimezone(LOCAL_TZ)
    clock = due.strftime("%I:%M %p").lstrip("0")
    days = (due.date() - base.date()).days
    if days == 0:
        day = "today"
    elif days == 1:
        day = "tomorrow"
    elif 1 < days < 7:
        day = "on " + due.strftime("%A")
    else:
        day = "on " + due.strftime("%A") + ", " + str(due.day) + " " + due.strftime("%B")
    label = f"{clock} {day}"
    if delta:
        label += ", in " + human_delta((due - base).total_seconds())
    return label


HOUR_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
REL_WORDS = dict(HOUR_WORDS, fifteen=15, twenty=20, thirty=30)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_WORDS = "today|tomorrow|tonight|" + "|".join(WEEKDAYS)


def parse_when(phrase, base=None):
    """Spoken time -> (moment, rolled, assumed), or None if it is not understood.
    Examples: 'at 6 pm', '6:30 pm', '18:30', 'tomorrow at 9 am', 'monday 8 am', 'tonight at 9',
    'at noon', 'in 45 minutes', 'in half an hour', 'after 2 hours'.
    rolled  = False, or 'tomorrow' / 'next week' when the time had already passed.
    assumed = 'AM' or 'PM' when you did not say which and Jarvis had to pick, else None.
    Raises ValueError when the time is clear but has already passed today."""
    base = base or ist_now()
    t = phrase.lower().strip(" .,!?")
    t = t.replace("a.m.", "am").replace("p.m.", "pm").replace("o'clock", " ").replace("o clock", " ")
    t = re.sub(r"\b(?:sharp|exactly|please|on|the|at|for|around|about|by)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    # a length of time: "in 45 minutes", "after 2 hours", "in half an hour", "in an hour"
    m = re.fullmatch(r"(?:in|after) (?P<n>\d+(?:\.\d+)?|half an?|an?|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty) ?"
                     r"(?P<u>seconds?|secs?|minutes?|mins?|hours?|hrs?)(?: from now)?", t)
    if m:
        n, unit = m.group("n"), m.group("u")
        if n.startswith("half"):
            value = 0.5
        elif n in ("a", "an"):
            value = 1.0
        elif n in REL_WORDS:
            value = float(REL_WORDS[n])
        else:
            value = float(n)
        seconds = value * (1 if unit.startswith("sec") else 3600 if unit.startswith(("hour", "hr")) else 60)
        if seconds <= 0 or seconds > 366 * 86400:
            return None
        return base + datetime.timedelta(seconds=seconds), False, None

    # a clock time, maybe with a day: "tomorrow 9 am", "monday 8 am", "tonight 9", "7 in the evening"
    day = None
    dm = re.search(r"\b(" + DAY_WORDS + r")\b", t)
    if dm:
        day = dm.group(1)
        t = re.sub(r"\s+", " ", t[:dm.start()] + " " + t[dm.end():]).strip()
    part = None
    pm = re.search(r"\b(?:in )?(morning|afternoon|evening|night)\b", t)
    if pm:
        part = pm.group(1)
        t = re.sub(r"\s+", " ", t[:pm.start()] + " " + t[pm.end():]).strip()
    if day == "tonight" and part is None:
        part = "night"
    t = t.replace("12 noon", "noon").replace("12 midnight", "midnight")
    t = re.sub(r"\b(" + "|".join(HOUR_WORDS) + r")\b", lambda mm: str(HOUR_WORDS[mm.group(1)]), t)

    ambiguous = False
    if t == "noon":
        hours, minute = [12], 0
    elif t == "midnight":
        hours, minute = [0], 0
    else:
        mt = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))? ?(am|pm)?", t)
        if not mt:
            return None
        h, minute, ap = int(mt.group(1)), int(mt.group(2) or 0), mt.group(3)
        if minute > 59:
            return None
        if ap:
            if not 1 <= h <= 12:
                return None
            hours = [h % 12 + (12 if ap == "pm" else 0)]
        elif part:
            if not 1 <= h <= 12:
                return None
            if part == "morning":
                hours = [h % 12]
            elif part in ("afternoon", "evening"):
                hours = [h % 12 + 12]
            else:  # night
                hours = [0] if h == 12 else [h + 12] if h >= 6 else [h]
        elif h > 23:
            return None
        elif h >= 13 or h == 0:
            hours = [h]
        else:
            hours, ambiguous = [h % 12, h % 12 + 12], True  # you did not say AM or PM

    target = base.date()
    if day == "tomorrow":
        target += datetime.timedelta(days=1)
    elif day in WEEKDAYS:
        target += datetime.timedelta(days=(WEEKDAYS.index(day) - base.weekday()) % 7)
    elif day == "tonight" and hours[0] < 6:
        target += datetime.timedelta(days=1)  # "tonight at 1" means just after midnight

    def at(d, hh):
        return datetime.datetime(d.year, d.month, d.day, hh, minute, tzinfo=LOCAL_TZ)

    chosen, rolled = None, False
    for hh in hours:
        if at(target, hh) > base:
            chosen = at(target, hh)
            break
    if chosen is None:
        if day in WEEKDAYS:
            chosen, rolled = at(target + datetime.timedelta(days=7), hours[0]), "next week"
        elif day in ("today", "tonight"):
            raise ValueError("That time has already passed today.")
        else:
            chosen, rolled = at(target + datetime.timedelta(days=1), hours[0]), "tomorrow"
    assumed = ("AM" if chosen.hour < 12 else "PM") if ambiguous else None
    return chosen, rolled, assumed


TIME_WORDS = ("at", "in", "after", "on", "for", "tomorrow", "tonight", "today") + tuple(WEEKDAYS)
CONNECTORS = ("to", "that", "about")


def reminder_request(text):
    """'remind me at 6 pm to call mom' / 'remind me to call mom at 6 pm' -> ('at 6 pm', 'call mom'), else None."""
    t = text.lower().strip(" .!?,")
    m = re.match(r"(?:please )?(?:remind me|set (?:a |an )?reminder(?: for me)?)\b[ ,]*(.*)$", t)
    if not m:
        return None
    words = m.group(1).split()
    if not words:
        return None

    def understood(phrase):
        try:
            return parse_when(phrase) is not None
        except ValueError:
            return True  # understood, but it has already passed: the reminder tool says so

    for i in range(1, len(words)):  # time first: "at 6 pm to call mom"
        if words[i] in CONNECTORS and understood(" ".join(words[:i])):
            return " ".join(words[:i]), " ".join(words[i + 1:])
    if understood(" ".join(words)):  # "remind me at 6 pm" (no message yet)
        return " ".join(words), ""
    if words[0] in CONNECTORS:  # message first: "to call mom at 6 pm"
        body = words[1:]
        for j in range(1, len(body)):
            if body[j] in TIME_WORDS and understood(" ".join(body[j:])):
                return " ".join(body[j:]), " ".join(body[:j])
    return None


def tool_set_reminder(minutes, message):
    base = ist_now()
    due = base + datetime.timedelta(minutes=float(minutes))
    with REMINDER_LOCK:
        items = load_reminders()
        items.append({"due": due.timestamp(), "text": message})
        save_reminders(items)
    return f"Reminder set for {describe_due(due, base)}: {message}."


def tool_set_reminder_at(when, message):
    """Python (not the AI) works out the exact moment from the words you said."""
    message = (message or "").strip()
    if not message:
        return "What should I remind you about?"
    base = ist_now()
    try:
        parsed = parse_when(when, base)
    except ValueError as e:
        return str(e)
    if parsed is None:
        return "I did not understand the time. Say it like: at 6 PM, in 45 minutes, or tomorrow at 9 AM."
    due, rolled, assumed = parsed
    with REMINDER_LOCK:
        items = load_reminders()
        items.append({"due": due.timestamp(), "text": message})
        save_reminders(items)
    text = f"Reminder set for {describe_due(due, base)}: {message}."
    if rolled:
        text = f"That time has already passed, so I set it for {rolled}. " + text
    if assumed:
        text += f" I took it as {assumed}."
    return text


def tool_list_reminders():
    with REMINDER_LOCK:
        items = sorted(load_reminders(), key=lambda r: r["due"])
    if not items:
        return "You have no reminders."
    base = ist_now()
    parts = []
    for r in items[:5]:
        due = datetime.datetime.fromtimestamp(r["due"], LOCAL_TZ)
        parts.append(f"{r['text']} at {describe_due(due, base, delta=False)}")
    return f"You have {len(items)} reminder" + ("s" if len(items) != 1 else "") + ": " + "; ".join(parts) + "."


'''

replace_block('def tool_set_reminder(minutes, message):\n', 'def tool_clear_reminders():\n', REMINDERS)

LOOP = r'''def reminder_loop():
    while True:
        try:
            with REMINDER_LOCK:
                items = load_reminders()
                now_ts = time.time()
                due_now = [r for r in items if r["due"] <= now_ts]
                if due_now:
                    save_reminders([r for r in items if r["due"] > now_ts])
            for r in due_now:
                if now_ts - r["due"] > 90:  # the PC was asleep or Jarvis was off: say when it was due
                    when = datetime.datetime.fromtimestamp(r["due"], LOCAL_TZ)
                    announce(f"You missed a reminder due at {describe_due(when, ist_now(), delta=False)}: " + r["text"])
                else:
                    announce("Reminder: " + r["text"])
        except Exception as e:
            print("Reminder error:", repr(e))
        time.sleep(REMINDER_POLL)


'''

replace_block('def reminder_loop():\n', 'def start_reminders():\n', LOOP)

# the instant reminder phrases
replace_block('    match = re.match(r"remind me (?:in|after) (\\d+',
              '    if text in ("what are my reminders",',
              '    request = reminder_request(text)\n'
              '    if request:\n'
              '        return tool_set_reminder_at(request[0], request[1])\n')

# ------------------------------------------------------------------ time and date: always live, any wording

TIME_BLOCK = r'''def time_answer(text):
    """Any wording of 'what time / date is it' -> an answer read from the live IST clock, else None."""
    t = text.lower().strip(" .!?,")
    if len(t.split()) > 10:
        return None
    if re.search(r"\bin\s+(?!india\b|ist\b|bangalore\b|bengaluru\b|right\b)[a-z]", t):
        return None  # "what time is it in tokyo" is another place: leave it to the AI
    ask_time = re.search(
        r"\bwhat(?:'s| is) (?:the )?(?:current |exact |correct )?time\b(?!\s+(?:of|for|on|at|when|that|to)\b)"
        r"|\bwhat time is it\b|\bwhat time it is\b|\btell me the (?:current )?time\b|\bcurrent time\b"
        r"|\btime (?:now|please)\b|\bdo you (?:know|have) the time\b|\bgot the time\b", t)
    ask_date = re.search(
        r"\bwhat(?:'s| is) (?:the )?(?:today's |current |exact )?date\b(?!\s+(?:of|for|on|when|that))"
        r"|\btoday's date\b|\bcurrent date\b|\bwhat day (?:is it|is today)\b|\bwhat(?:'s| is) today\b"
        r"|\bdate today\b|\bwhich day (?:is it|is today)\b|\bwhat is the day today\b", t)
    both = re.search(r"\bdate and time\b|\btime and date\b", t)
    if not (ask_time or ask_date or both):
        return None
    return clock_text(want_time=bool(ask_time or both), want_date=bool(ask_date or both))


def clock_text(want_time=True, want_date=True):
    now = ist_now()
    clock = now.strftime("%I:%M %p").lstrip("0")
    date = f"{now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}"
    if want_time and want_date:
        return f"It is {clock} on {date}."
    if want_time:
        return f"It is {clock}."
    return f"Today is {date}."


def tool_get_time():
    return clock_text() + " (India Standard Time)"


'''

swap('def fast_command(text):\n', TIME_BLOCK + 'def fast_command(text):\n')

swap('    action = media_action(text)\n    if action:\n',
     '    answer = time_answer(text)\n    if answer:\n        return answer\n\n    action = media_action(text)\n    if action:\n')

swap(r'''        if re.search(r"\b(what time is it|what is the time|what's the time|current time|time now|tell me the time)\b", text):
            return "It is " + datetime.datetime.now().strftime("%I:%M %p").lstrip("0") + "."
        if re.search(r"\b(what is the date|what's the date|today's date|what day is it|what is today|what's today)\b", text):
            return "Today is " + datetime.datetime.now().strftime("%A, %d %B %Y") + "."
''', '')

# never keep time-sensitive answers in the chat memory (that is how an old time got repeated)
HIST = r'''def time_sensitive(question, answer):
    """Time, date and reminder answers go stale in minutes, so they must not be kept in the chat memory."""
    if re.search(r"\b(?:time|date|day|today|tomorrow|tonight|clock|o'clock|remind|reminder|now)\b", question.lower()):
        return True
    return bool(re.search(r"\b\d{1,2}:\d{2}\b|\b\d{1,2} ?(?:am|pm)\b", answer.lower()))


'''

swap('def ask_ai(question):\n', HIST + 'def ask_ai(question):\n')

swap('    HISTORY.append({"role": "user", "content": question})\n'
     '    HISTORY.append({"role": "assistant", "content": text})\n'
     '    del HISTORY[:-12]\n',
     '    if not time_sensitive(question, text):\n'
     '        HISTORY.append({"role": "user", "content": question})\n'
     '        HISTORY.append({"role": "assistant", "content": text})\n'
     '        del HISTORY[:-12]\n')

# ------------------------------------------------------------------ quiet mode: wording

QUIET = r'''def quiet_request(text):
    """'go to quiet mode' / 'wake up' in many wordings -> 'on', 'off' or None."""
    t = text.lower().strip(" .!?,")
    if not t or len(t.split()) > 8:
        return None
    off = (
        r"\b(?:wake up|wakeup|come back|i'?m back|im back|talk to me|speak to me|normal mode|back online|come online)\b",
        r"\b(?:turn|switch|take)\b.*\b(?:off|out of)\b.*\b(?:quiet|quite|silent)\b",
        r"\b(?:quiet|quite|silent) mode (?:off|disabled?)\b",
        r"\b(?:stop|quit) being (?:quiet|quite|silent)\b",
        r"\b(?:disable|exit|leave|end) (?:the )?(?:quiet|quite|silent)(?: mode)?\b",
    )
    if any(re.search(p, t) for p in off):
        return "off"
    on = (  # "quite" is how speech-to-text often writes "quiet"
        r"\b(?:go|be|stay|get|switch|turn|enter|keep)\s+(?:to\s+|into\s+|in\s+|on\s+)?(?:the\s+|a\s+)?(?:quiet|quite|silent)\b",
        r"^(?:quiet|quite|silent) mode(?: please| on)?$",
        r"^(?:quiet|quite)(?: please| now)?$",
        r"^(?:shh+|shush|silence)$",
    )
    if any(re.search(p, t) for p in on):
        return "on"
    return None


def tool_set_quiet_mode(state):
    if str(state).lower() in ("on", "true", "quiet", "yes"):
        set_lock(True)
        return "Going quiet. Say Hey Jarvis or wake up when you need me."
    set_lock(False)
    return "I am back. Say Jarvis when you need me."


'''

swap('def handle(command):\n', QUIET + 'def handle(command):\n')

swap('    if text in QUIET_ON_PHRASES:\n        speak("Going quiet. Say Hey Jarvis when you need me.")\n',
     '    if text in QUIET_ON_PHRASES or quiet_request(text) == "on":\n'
     '        speak("Going quiet. Say Hey Jarvis or wake up when you need me.")\n')

swap('    if text in QUIET_OFF_PHRASES:\n',
     '    if text in QUIET_OFF_PHRASES or quiet_request(text) == "off":\n')

swap('    words = text.split()\n    STATE["enter_quiet"] = False\n',
     '    words = text.split()\n    print(f"[command] {text}")\n    STATE["enter_quiet"] = False\n')

# ------------------------------------------------------------------ the listener follows QUIET / WAKE UP at once

swap('    STATE["lock"] = flag\n    STATE["woken"] = woken\n    HUD.quiet(flag)\n',
     '    STATE["lock"] = flag\n    STATE["woken"] = woken\n    STATE["gen"] = STATE.get("gen", 0) + 1  # tells the listener the mode changed\n    HUD.quiet(flag)\n')

swap('def record_until_silence(wait_seconds=None, max_seconds=None, pause_seconds=None):\n',
     'def record_until_silence(wait_seconds=None, max_seconds=None, pause_seconds=None, abort=None):\n')

swap('            data, _ = stream.read(block)\n',
     '            data, _ = stream.read(block)\n'
     '            if abort is not None and not started and abort():\n'
     '                return None  # the mode changed while we were waiting for speech\n')

swap('    while True:\n        audio = record_until_silence(max_seconds=8)\n        if audio is None or LAST["hit_max"]:\n',
     '    gen = STATE.get("gen", 0)\n'
     '    while True:\n'
     '        audio = record_until_silence(max_seconds=8, abort=lambda: STATE.get("gen", 0) != gen)\n'
     '        if STATE.get("gen", 0) != gen:\n'
     '            return None  # you clicked QUIET / WAKE UP: let the main loop listen the new way\n'
     '        if audio is None or LAST["hit_max"]:\n')

swap('    while True:\n        audio = record_until_silence()\n        data, fs = audio\n',
     '    gen = STATE.get("gen", 0)\n'
     '    while True:\n'
     '        audio = record_until_silence(abort=lambda: STATE.get("gen", 0) != gen)\n'
     '        if audio is None:\n'
     '            return None  # you clicked QUIET / WAKE UP: let the main loop listen the new way\n'
     '        data, fs = audio\n')

swap('                command = wait_for_quiet_wake()\n'
     '                STATE["woken"] = True  # you called it, so it may answer out loud\n',
     '                command = wait_for_quiet_wake()\n'
     '                if command is None:\n'
     '                    continue  # the mode changed: start listening the new way straight away\n'
     '                STATE["woken"] = True  # you called it, so it may answer out loud\n')

swap('                command = wait_for_wake_word()\n'
     '                HUD.state("listening")\n',
     '                command = wait_for_wake_word()\n'
     '                if command is None:\n'
     '                    continue  # the mode changed: start listening the new way straight away\n'
     '                HUD.state("listening")\n')

# ------------------------------------------------------------------ tools the AI can call

swap('    {"name": "forget",\n',
     '''    {"name": "get_time",
     "description": "Get the exact current time and date in India (IST). ALWAYS call this for any question "
                    "about the time, date or day. Never answer those from memory."},
    {"name": "set_reminder_at",
     "description": "Set a reminder for a clock time or a length of time. For 'when' pass the user's own words "
                    "exactly, for example 'at 6 pm', 'tomorrow at 9 am', 'in 45 minutes'. Never work out minutes yourself.",
     "parameters": params({"when": STR, "message": STR}, ["when", "message"])},
    {"name": "set_quiet_mode",
     "description": "Turn quiet mode on (stop talking until the user says Hey Jarvis or wake up) or off.",
     "parameters": params({"state": {"type": "STRING", "enum": ["on", "off"]}}, ["state"])},
    {"name": "forget",\n''')

swap('     "description": "Remind the user out loud after some minutes.",\n',
     '     "description": "Remind the user after a plain number of minutes. For a clock time use set_reminder_at.",\n')

swap('    "forget": tool_forget,\n',
     '    "forget": tool_forget,\n'
     '    "get_time": lambda: tool_get_time(),\n'
     '    "set_reminder_at": tool_set_reminder_at,\n'
     '    "set_quiet_mode": lambda state: tool_set_quiet_mode(state),\n')

# ------------------------------------------------------------------ check, back up, save

try:
    compile(src, PATH, "exec")
except SyntaxError as e:
    print("The patched code did not compile:", e)
    print("Nothing was changed.")
    sys.exit(1)

shutil.copy(PATH, "main.py.bak")
with open(PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Done. Fixed: exact IST time, exact-time reminders, quiet mode wording, instant QUIET / wake up.")
print("Backup saved as main.py.bak")
