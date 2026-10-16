# Run once inside the JARVIS folder:  python upgrade_suite.py
#
# ADDS (all in main.py, no new packages needed)
#   1. START WITH WINDOWS + MORNING BRIEFING
#        "start with windows" / "disable startup"      -> adds / removes a Startup-folder shortcut
#        "good morning" / "brief me"                    -> time, date, weather, today's reminders, to-do list
#        When Windows starts Jarvis, it gives the briefing by itself.
#   2. VOICE NOTES AND TO-DO LIST
#        "note down buy a multimeter", "what are my notes", "clear my notes"
#        "add call mom to my to-do list", "what's on my to-do list", "mark call mom as done"
#   3. STUDY TIMER (Pomodoro)
#        "start a 25 minute focus session", "how much time is left", "skip the break", "stop focus"
#   5. FILE FINDER
#        "open my VLSI notes", "open the lab report pdf", "find my resume file"
#   6. CLIPBOARD HELPER
#        "summarize what I copied", "fix the grammar of what I copied", "translate what I copied to Hindi"
#   7. SMARTER MEMORY
#        "remember that my DSP exam is on 14 October", "what do you know about me", "forget the exam"
#        Jarvis also picks up lasting facts from normal chat (never health, money or other sensitive things).
#
# Needs the earlier patches (upgrade_jarvis.py, upgrade_vision.py, fix_time_quiet.py).
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

if "def build_briefing" in src:
    print("Already installed. Nothing to do.")
    sys.exit(0)

if "def ist_now" not in src or "def tool_look_at_screen" not in src:
    print("Run upgrade_jarvis.py, upgrade_vision.py and fix_time_quiet.py first, then run this one.")
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

swap('LOCAL_TZ = datetime.timezone(datetime.timedelta(hours=5, minutes=30), "IST")  # India Standard Time (no daylight saving)\n',
     'LOCAL_TZ = datetime.timezone(datetime.timedelta(hours=5, minutes=30), "IST")  # India Standard Time (no daylight saving)\n'
     'USER_NAME = "Mitch"       # how the morning briefing greets you\n'
     'STARTUP_BRIEFING = True   # when Windows starts Jarvis, give the morning briefing\n'
     'FOCUS_MINUTES = 25        # study timer: focus length\n'
     'SHORT_BREAK = 5           # study timer: normal break\n'
     'LONG_BREAK = 15           # study timer: long break (after every 4th focus round)\n'
     'ROUNDS_BEFORE_LONG = 4\n'
     'EXTRA_SEARCH_FOLDERS = []  # more folders for the file finder, e.g. [r"D:\\College"]\n'
     'FILE_SEARCH_SECONDS = 4   # the file finder gives up after this long\n')

# ------------------------------------------------------------------ memory: no duplicates, safe empty "forget"

replace_block('def tool_remember(fact):\n', 'SHOT_DIR = os.path.join(', r'''MEMORY_LOCK = threading.Lock()
MEMORY_MAX = 80  # the oldest facts drop off after this many


def tool_remember(fact):
    fact = str(fact).strip(" .")
    if not fact:
        return "What should I remember?"
    key = norm(fact)
    with MEMORY_LOCK:
        facts = load_memory()
        for i, old in enumerate(facts):
            k = norm(old)
            if k == key or (len(key) > 12 and key in k):
                return "I already know that."
            if len(k) > 12 and k in key:  # the new one says the same thing with more detail
                facts[i] = fact
                save_memory(facts)
                return "Updated my memory."
        facts.append(fact)
        del facts[:-MEMORY_MAX]
        save_memory(facts)
    return "Saved to long-term memory."


def tool_forget(keyword):
    words = [w for w in re.findall(r"[a-z0-9]+", str(keyword).lower()) if len(w) > 2 and w not in ("the", "about", "that", "and", "our", "his", "her")]
    if not words:
        return "Tell me what to forget."
    with MEMORY_LOCK:
        facts = load_memory()
        kept = [f for f in facts if not all(w in f.lower() for w in words)]
        save_memory(kept)
    return f"Removed {len(facts) - len(kept)} memory item(s)."


def tool_list_memory():
    facts = load_memory()
    if not facts:
        return "I do not know anything about you yet. Say remember that, then a fact."
    shown = facts[-8:][::-1]
    more = len(facts) - len(shown)
    text = f"I know {len(facts)} thing" + ("" if len(facts) == 1 else "s") + " about you. " + ". ".join(shown) + "."
    return text + (f" And {more} more." if more > 0 else "")


''')

swap('    memory = ("Known about the user: " + "; ".join(facts) + ". ") if facts else ""\n',
     '    memory = ("Known about the user: " + "; ".join(facts[-40:]) + ". ") if facts else ""\n')

swap('    print(f"[brain: {LAST_BRAIN}]")\n',
     '    print(f"[brain: {LAST_BRAIN}]")\n'
     '    maybe_learn(question)\n')

# ------------------------------------------------------------------ the new features

NEW_CODE = r'''# ---------------------------------------------------------------- suite: startup, briefing, notes, to-do,
# ---------------------------------------------------------------- study timer, file finder, clipboard, memory

STARTED_BY_WINDOWS = "--startup" in sys.argv
STARTUP_BAT_NAME = "Jarvis Startup.bat"
NOTES_FILE = os.path.join(app_dir(), "jarvis_notes.json")
TODO_FILE = os.path.join(app_dir(), "jarvis_todo.json")
DATA_LOCK = threading.Lock()
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
                "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}


def load_list(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def save_list(path, items):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


# ---- 1. start with Windows

def startup_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def startup_path():
    return os.path.join(startup_dir(), STARTUP_BAT_NAME)


def tool_enable_startup():
    if getattr(sys, "frozen", False):
        launch = f'start "" /min "{sys.executable}" --startup'
    else:
        launch = f'start "" /min "{sys.executable}" "{os.path.abspath(__file__)}" --startup'
    lines = ["@echo off", f'cd /d "{app_dir()}"',
             "ping -n 16 127.0.0.1 >nul",  # about 15 seconds: let the network and microphone come up
             launch]
    try:
        os.makedirs(startup_dir(), exist_ok=True)
        with open(startup_path(), "w", encoding="utf-8", newline="") as f:
            f.write("\r\n".join(lines) + "\r\n")
    except OSError as e:
        return f"I could not set that up: {e}"
    return "Done. Jarvis will start with Windows and give you a morning briefing. Say disable startup to undo it."


def tool_disable_startup():
    try:
        os.remove(startup_path())
    except FileNotFoundError:
        return "Jarvis was not set to start with Windows."
    except OSError as e:
        return f"I could not remove it: {e}"
    return "Done. Jarvis will no longer start with Windows."


def tool_startup_status():
    if os.path.exists(startup_path()):
        return "Yes, Jarvis starts with Windows."
    return "No, Jarvis does not start with Windows. Say start with Windows to turn it on."


# ---- 1b. morning briefing

def build_briefing():
    now = ist_now()
    hour = now.hour
    hello = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    clock = now.strftime("%I:%M %p").lstrip("0")
    parts = [f"{hello}, {USER_NAME}. It is {clock} on {now.strftime('%A')}, {now.day} {now.strftime('%B')}."]

    try:
        weather = tool_get_weather(HOME_CITY)
        if not weather.startswith(("Weather lookup failed", "I could not")):
            parts.append(weather)
    except Exception as e:
        print("Briefing weather error:", repr(e))

    cal = globals().get("calendar_brief")  # added by the Google upgrade, if you installed it
    if callable(cal):
        try:
            text = cal()
            if text:
                parts.append(text)
        except Exception as e:
            print("Briefing calendar error:", repr(e))

    today = []
    for r in sorted(load_reminders(), key=lambda r: r["due"]):
        due = datetime.datetime.fromtimestamp(r["due"], LOCAL_TZ)
        if due.date() == now.date() and due > now:
            today.append(f"{r['text']} at {due.strftime('%I:%M %p').lstrip('0')}")
    if today:
        parts.append(f"You have {plural(len(today), 'reminder')} today: " + "; ".join(today[:4]) + ".")

    pending = [t for t in load_list(TODO_FILE) if not t.get("done")]
    if pending:
        top = "; ".join(t["text"] for t in pending[:3])
        parts.append(f"{plural(len(pending), 'task')} on your to-do list. Top: {top}.")
    if len(parts) == 1:
        parts.append("Nothing is pending today.")
    parts.append("How can I help?")
    return " ".join(parts)


# ---- 2. notes and to-do list

def tool_add_note(text):
    text = str(text).strip(" .,:;")
    if not text:
        return "What should I note down?"
    with DATA_LOCK:
        items = load_list(NOTES_FILE)
        items.append({"text": text, "time": ist_now().isoformat(timespec="minutes")})
        save_list(NOTES_FILE, items)
    return f"Noted: {text}."


def tool_list_notes():
    items = load_list(NOTES_FILE)
    if not items:
        return "You have no notes."
    newest = [n["text"] for n in items[::-1][:5]]
    more = len(items) - len(newest)
    text = f"You have {plural(len(items), 'note')}. Newest first: " + ". ".join(newest) + "."
    return text + (f" And {more} older." if more > 0 else "")


def tool_clear_notes():
    with DATA_LOCK:
        n = len(load_list(NOTES_FILE))
        save_list(NOTES_FILE, [])
    return f"Cleared {plural(n, 'note')}." if n else "You have no notes."


def tool_add_todo(task):
    task = str(task).strip(" .,:;")
    if not task:
        return "What task should I add?"
    with DATA_LOCK:
        items = load_list(TODO_FILE)
        items.append({"text": task, "done": False, "added": ist_now().isoformat(timespec="minutes")})
        save_list(TODO_FILE, items)
        pending = len([t for t in items if not t.get("done")])
    return f"Added to your to-do list: {task}. {plural(pending, 'task')} pending."


def tool_list_todos():
    pending = [t for t in load_list(TODO_FILE) if not t.get("done")]
    if not pending:
        return "Your to-do list is empty."
    listing = ". ".join(f"{i}, {t['text']}" for i, t in enumerate(pending[:8], 1))
    more = len(pending) - 8
    return f"You have {plural(len(pending), 'task')}. " + listing + "." + (f" And {more} more." if more > 0 else "")


def tool_complete_todo(which):
    which = str(which).strip(" .,").lower()
    which = re.sub(r"^(?:the |task |number |item )+", "", which)
    with DATA_LOCK:
        items = load_list(TODO_FILE)
        pending = [t for t in items if not t.get("done")]
        if not pending:
            return "Your to-do list is empty."
        target = None
        number = int(which) if which.isdigit() else NUMBER_WORDS.get(which)
        if number:
            if 1 <= number <= len(pending):
                target = pending[number - 1]
            else:
                return f"You only have {plural(len(pending), 'task')}."
        else:
            words = [w for w in re.findall(r"[a-z0-9]+", which) if len(w) > 1]
            found = [t for t in pending if words and all(w in t["text"].lower() for w in words)]
            if len(found) > 1:
                return "Which one? " + ". ".join(t["text"] for t in found[:4]) + "."
            if found:
                target = found[0]
        if not target:
            return f"I could not find a task matching {which}."
        target["done"] = True
        target["finished"] = ist_now().isoformat(timespec="minutes")
        save_list(TODO_FILE, items)
        left = len(pending) - 1
    return f"Done: {target['text']}. " + (f"{plural(left, 'task')} left." if left else "Your list is clear.")


def tool_clear_todos():
    with DATA_LOCK:
        n = len([t for t in load_list(TODO_FILE) if not t.get("done")])
        save_list(TODO_FILE, [])
    return f"Cleared {plural(n, 'task')}." if n else "Your to-do list is empty."


# ---- 3. study timer (Pomodoro)

POMO = {"gen": 0, "phase": None, "end": 0.0, "round": 0}
POMO_LOCK = threading.Lock()
POMO_TICK = 0.5  # seconds between checks


def pomo_wait(gen):
    while True:
        if POMO["gen"] != gen:
            return False
        if time.time() >= POMO["end"]:
            return True
        time.sleep(POMO_TICK)


def pomodoro_loop(gen, focus, short, long):
    round_no = 1
    while True:
        with POMO_LOCK:
            if POMO["gen"] != gen:
                return
            POMO.update(phase="focus", end=time.time() + focus * 60, round=round_no)
        if not pomo_wait(gen):
            return
        rest = long if round_no % ROUNDS_BEFORE_LONG == 0 else short
        with POMO_LOCK:
            if POMO["gen"] != gen:
                return
            POMO.update(phase="break", end=time.time() + rest * 60)
        announce(f"Focus round {round_no} is done. Take a {rest:g} minute break.")
        if not pomo_wait(gen):
            return
        round_no += 1
        announce(f"Break over. Starting focus round {round_no}.")


def tool_start_focus(minutes=None, break_minutes=None):
    try:
        focus = float(minutes) if minutes else FOCUS_MINUTES
        short = float(break_minutes) if break_minutes else SHORT_BREAK
    except (TypeError, ValueError):
        return "How many minutes should the focus session be?"
    if focus <= 0 or short <= 0:
        return "The time must be more than zero."
    with POMO_LOCK:
        if POMO["phase"]:
            return "A focus session is already running. " + focus_status() + " Say stop focus to end it."
        POMO["gen"] += 1
        gen = POMO["gen"]
        POMO.update(phase="focus", end=time.time() + focus * 60, round=1)
    threading.Thread(target=pomodoro_loop, args=(gen, focus, short, max(LONG_BREAK, short)), daemon=True).start()
    return f"Starting a {focus:g} minute focus session. I will tell you when to take a break."


def focus_status():
    if not POMO["phase"]:
        return "No focus session is running."
    left = max(0, POMO["end"] - time.time())
    what = "of focus" if POMO["phase"] == "focus" else "of break"
    return f"Round {POMO['round']}, {human_delta(left)} {what} left."


def tool_stop_focus():
    with POMO_LOCK:
        if not POMO["phase"]:
            return "No focus session is running."
        POMO["gen"] += 1
        rounds = POMO["round"]
        POMO["phase"] = None
    return f"Focus session stopped after {plural(rounds, 'round')}."


def tool_skip_break():
    with POMO_LOCK:
        if POMO["phase"] != "break":
            return "You are not on a break right now."
        POMO["end"] = 0.0
    return "Skipping the break."


def number_in(text):
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1))
    for word, n in NUMBER_WORDS.items():
        if re.search(r"\b" + word + r"\b", text):
            return float(n)
    return None


def focus_minutes(text):
    if re.search(r"\bhalf an? hour\b", text):
        return 30.0
    if re.search(r"\b(?:an|one|1) hour\b", text):
        return 60.0
    m = re.search(r"((?:\d+(?:\.\d+)?)|(?:" + "|".join(NUMBER_WORDS) + r"|fifteen|twenty|thirty|forty|forty five|fifty))\s*-?\s*(minute|min|hour|hr)s?\b", text)
    if not m:
        return None
    word = m.group(1)
    extra = {"fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50}
    n = float(word) if re.match(r"[\d.]+$", word) else float(extra.get(word) or NUMBER_WORDS[word])
    return n * 60 if m.group(2) in ("hour", "hr") else n


def focus_command(text):
    if re.search(r"\b(?:stop|end|cancel|quit|finish)\b.*\b(?:focus|pomodoro|study)\b", text):
        return tool_stop_focus()
    if re.fullmatch(r"skip (?:the |this )?(?:break|rest)", text):
        return tool_skip_break()
    if re.search(r"\b(?:focus|pomodoro)\b.*\b(?:left|remaining|status)\b|\b(?:left|remaining)\b.*\b(?:focus|pomodoro|session|break)\b"
                 r"|how much time (?:is )?left|how long (?:is )?(?:left|the break)", text):
        return focus_status()
    starts = re.match(r"(?:please )?(?:start|begin|set|run|activate|let'?s do|lets do|i want|put me in)\b.*\b(?:pomodoro|focus|study)\b", text)
    if starts or re.match(r"(?:focus|study) for\b.*\b(?:minutes?|mins?|hours?|hr)\b", text) or re.fullmatch(r"(?:pomodoro|focus mode|focus session)", text):
        return tool_start_focus(focus_minutes(text))
    return None


# ---- 5. file finder

FILE_WORDS = {"file", "files", "document", "documents", "doc", "docs", "pdf", "notes", "ppt", "pptx", "presentation",
              "slides", "spreadsheet", "excel", "word", "report", "assignment", "syllabus", "resume", "paper"}
EXT_HINTS = {"pdf": (".pdf",), "ppt": (".ppt", ".pptx"), "pptx": (".pptx",), "presentation": (".ppt", ".pptx"),
             "slides": (".ppt", ".pptx"), "spreadsheet": (".xls", ".xlsx", ".csv"), "excel": (".xls", ".xlsx", ".csv"),
             "word": (".doc", ".docx")}
FILE_STOP = {"my", "the", "a", "an", "called", "named", "please", "file", "files", "on", "in", "pc", "laptop", "computer",
             "from", "of", "up", "for"}
GENERIC_WORDS = {"file", "files", "document", "documents", "doc", "docs", "pdf", "notes", "ppt", "pptx", "presentation",
                 "slides", "spreadsheet", "excel", "word"}
SKIP_DIRS = {"node_modules", "venv", ".venv", "__pycache__", ".git", "site-packages", "appdata", "$recycle.bin"}
SKIP_EXT = {".dll", ".sys", ".tmp", ".ini", ".lnk", ".exe", ".pyc", ".bak", ".db"}


def search_roots():
    home = os.path.expanduser("~")
    roots = []
    for base in (home, os.path.join(home, "OneDrive"), os.environ.get("OneDrive", "")):
        if not base:
            continue
        for sub in ("Documents", "Desktop", "Downloads"):
            roots.append(os.path.join(base, sub))
    roots += list(EXTRA_SEARCH_FOLDERS)
    seen, out = set(), []
    for r in roots:
        key = os.path.normcase(os.path.abspath(r))
        if key not in seen and os.path.isdir(r):
            seen.add(key)
            out.append(r)
    return out


def find_files(tokens, exts=(), roots=None, limit=5, seconds=None):
    """Files whose name (or folder name) contains every word. Best first."""
    deadline = time.time() + (FILE_SEARCH_SECONDS if seconds is None else seconds)
    want = [norm(t) for t in tokens if norm(t)]
    if not want:
        return []
    found = []
    for root in (roots if roots is not None else search_roots()):
        base_depth = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")
                           and dirpath.count(os.sep) - base_depth < 5]
            folder = norm(os.path.relpath(dirpath, root))
            for name in filenames:
                stem, ext = os.path.splitext(name)
                if name.startswith(("~$", ".")) or ext.lower() in SKIP_EXT:
                    continue
                s = norm(stem)
                if not all(w in s or w in folder for w in want):
                    continue
                score = sum(2 if w in s else 1 for w in want)
                if exts and ext.lower() in exts:
                    score += 3
                elif exts:
                    score -= 1
                path = os.path.join(dirpath, name)
                try:
                    stamp = os.path.getmtime(path)
                except OSError:
                    stamp = 0
                found.append((score, -len(stem), stamp, path))
            if time.time() > deadline:
                break
        if time.time() > deadline:
            break
    found.sort(key=lambda x: x[:3], reverse=True)  # best match, then the closest name, then the newest
    return [x[3] for x in found[:limit]]


def open_path(path):
    if hasattr(os, "startfile"):
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


def file_query(words):
    tokens = [w for w in words if w not in FILE_STOP]
    exts = ()
    for w in words:
        exts = exts or EXT_HINTS.get(w, ())
    return [w for w in tokens if w not in GENERIC_WORDS], exts


def tool_find_file(query):
    words = re.findall(r"[a-z0-9]+", str(query).lower())
    tokens, exts = file_query(words)
    if not tokens:
        return "Which file? Say part of its name."
    hits = find_files(tokens, exts)
    if not hits:
        return f"I could not find a file matching {' '.join(tokens)} in Documents, Desktop or Downloads."
    names = [os.path.basename(p) for p in hits[:3]]
    return f"I found {plural(len(hits), 'match')}: " + "; ".join(names) + "."


def tool_open_file(query):
    words = re.findall(r"[a-z0-9]+", str(query).lower())
    tokens, exts = file_query(words)
    if not tokens:
        return "Which file? Say part of its name."
    hits = find_files(tokens, exts)
    if not hits:
        return f"I could not find a file matching {' '.join(tokens)} in Documents, Desktop or Downloads."
    try:
        open_path(hits[0])
    except Exception as e:
        return f"I found it but could not open it: {e}"
    mark_quiet()
    extra = f" {len(hits) - 1} other match" + ("" if len(hits) == 2 else "es") + " found." if len(hits) > 1 else ""
    return f"Opening {os.path.basename(hits[0])}." + extra


def file_command(text):
    m = re.fullmatch(r"(?:open|show|pull up|launch)\s+(?:up\s+)?(?:the |my |a )?(?:file|document)s?\s+(?!folder\b|app\b|application\b)(?:called |named )?(.+)", text)
    if m:
        return tool_open_file(m.group(1))
    m = re.fullmatch(r"(?:find|locate|search for|look for|where is|where's)\s+(?:the |my |a )?(?:file|document)s?\s+(?!folder\b|app\b|application\b)(?:called |named )?(.+)", text)
    if m:
        return tool_find_file(m.group(1))
    m = re.fullmatch(r"(?:open|show|pull up)\s+(?:up\s+)?(?:the |my |a )?(.+)", text)
    if m:
        words = m.group(1).split()
        if words[-1] in FILE_WORDS and file_query(words)[0]:
            return tool_open_file(m.group(1))
        return None
    m = re.fullmatch(r"(?:find|locate|search for|look for|where is|where's)\s+(?:the |my |a )?(.+?)(?:\s+(?:on|in) my (?:pc|laptop|computer|files|documents))?", text)
    if m:
        words = m.group(1).split()
        on_pc = bool(re.search(r"\b(?:on|in) my (?:pc|laptop|computer|files|documents)$", text))
        if (words[-1] in FILE_WORDS or on_pc) and file_query(words)[0]:
            return tool_find_file(m.group(1))
    return None


# ---- 6. clipboard helper

def get_clipboard():
    if os.name != "nt":
        raise RuntimeError("The clipboard helper works on Windows.")
    path = os.path.join(tempfile.gettempdir(), "jarvis_clip_" + uuid.uuid4().hex + ".txt")
    try:
        run_hidden(["powershell", "-NoProfile", "-Command",
                    f"Get-Clipboard -Raw | Set-Content -Encoding UTF8 -LiteralPath '{path}'"], timeout=10)
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def set_clipboard(text):
    if os.name != "nt":
        raise RuntimeError("The clipboard helper works on Windows.")
    path = os.path.join(tempfile.gettempdir(), "jarvis_clip_" + uuid.uuid4().hex + ".txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        run_hidden(["powershell", "-NoProfile", "-Command",
                    f"Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 -LiteralPath '{path}')"], timeout=10)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def llm_plain(instruction, text, raw=False):
    """One-off AI call: no chat history, no tools. Returns text, or None if every brain failed."""
    prompt = instruction + "\n\n" + text
    key = os.environ.get("GROQ_API_KEY")
    if key:
        if not GROQ_MODELS:
            GROQ_MODELS.extend(find_groq_models(key))
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": "jarvis/1.0"}
        for model in GROQ_MODELS[:3]:
            result = post_json(GROQ_URL, {"model": model, "messages": [
                {"role": "system", "content": "Follow the instruction exactly. Reply with only the result."},
                {"role": "user", "content": prompt}]}, headers)
            try:
                out = (result["choices"][0]["message"].get("content") or "").strip()
            except (TypeError, KeyError, IndexError):
                continue
            if out:
                return out if raw else clean(out)
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        headers = {"Content-Type": "application/json", "x-goog-api-key": key}
        for model in GEMINI_MODELS:
            result = post_json("https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent",
                               {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}, headers)
            try:
                out = "".join(p.get("text", "") for p in result["candidates"][0]["content"]["parts"]).strip()
            except (TypeError, KeyError, IndexError):
                continue
            if out:
                return out if raw else clean(out)
    return None


SPOKEN = "Reply in at most 3 short plain spoken sentences. No markdown, no bullet points."
CLIP_TASKS = {
    "summarize": ("Summarize the text below. " + SPOKEN, False),
    "explain": ("Explain the text below in simple words. " + SPOKEN, False),
    "fix": ("Fix the grammar, spelling and punctuation of the text below. Keep the meaning and the tone. Reply with only the corrected text.", True),
    "shorten": ("Make the text below shorter but keep the meaning. Reply with only the shortened text.", True),
    "formal": ("Rewrite the text below in a formal, professional tone. Reply with only the rewritten text.", True),
}


def tool_clipboard_task(task, language=""):
    try:
        text = get_clipboard()
    except Exception as e:
        return f"I could not read the clipboard: {e}"
    if not text:
        return "Your clipboard is empty, or it holds something that is not text."
    text = text[:8000]
    if task == "read":
        return "You copied: " + (text[:400] + ("..." if len(text) > 400 else ""))
    if task == "translate":
        language = str(language).strip().capitalize() or "English"
        instruction, replace = f"Translate the text below into {language}. Reply with only the translation.", True
    elif task in CLIP_TASKS:
        instruction, replace = CLIP_TASKS[task]
    else:
        return "I can summarize, explain, fix, shorten, translate or read what you copied."
    out = llm_plain(instruction, text, raw=replace)
    if not out:
        return "Sorry, my brain is busy right now. Try again in a minute."
    if not replace:
        return out
    try:
        set_clipboard(out)
    except Exception as e:
        return "Here it is, but I could not copy it back: " + out[:300] + f" ({e})"
    show(out)
    return "Done. The new text is on your clipboard and on screen. Just paste it."


CLIP_REF = (r"(?:(?:what|that|whatever|everything|the text|the stuff)\s+(?:i|i've|i have|ive)\s+(?:just\s+)?cop(?:ied|y)"
            r"|(?:my|the)\s+clipboard|(?:the\s+)?copied\s+(?:text|content|stuff)|what(?:'s| is)\s+copied)")


def clip_command(text):
    if not re.search(CLIP_REF, text) and not re.fullmatch(r"what did i (?:just )?copy", text):
        return None
    m = re.search(r"translate\b.*?\b(?:to|into)\s+([a-z]+)", text)
    if m:
        return tool_clipboard_task("translate", m.group(1))
    if re.search(r"summari[sz]e|sum up|tldr|tl;dr", text):
        return tool_clipboard_task("summarize")
    if re.search(r"\bexplain\b|what does .* mean", text):
        return tool_clipboard_task("explain")
    if re.search(r"grammar|proofread|spelling|correct|\bfix\b", text):
        return tool_clipboard_task("fix")
    if re.search(r"shorten|shorter|make .* short", text):
        return tool_clipboard_task("shorten")
    if re.search(r"formal|professional", text):
        return tool_clipboard_task("formal")
    if re.search(r"\bread\b|what did i|what(?:'s| is) (?:on|in)|what have i|\bsay\b", text):
        return tool_clipboard_task("read")
    return None


# ---- 7. smarter memory: learn lasting facts from normal chat

STATEMENT = re.compile(r"\bmy [a-z' ]{1,30}? (?:is|are|was|will be|starts|ends)\b|\bi (?:am|'m|have|study|work|live|like|love|prefer|usually|always|never)\b"
                       r"|\b(?:exam|birthday|deadline|submission|interview)\b.*\b(?:on|is|at|by)\b")
QUESTION_START = re.compile(r"^(?:what|when|where|who|why|how|which|can|could|do|does|did|is|are|will|would|should|open|play|set|remind|"
                            r"tell|show|find|search|take|close|lock)\b")


def maybe_learn(question):
    q = question.lower().strip(" .!?,")
    if len(q.split()) < 4 or QUESTION_START.match(q) or not STATEMENT.search(q):
        return
    threading.Thread(target=learn_from, args=(question,), daemon=True).start()


def learn_from(question):
    try:
        today = ist_now().strftime("%d %B %Y")
        instruction = ("Extract lasting personal facts the user states about themselves: studies, exam or event dates, "
                       "preferences, habits, goals. Ignore health, money, politics, religion and other sensitive details, and ignore "
                       "temporary things such as what they are doing right now. Turn relative dates into exact dates "
                       f"(today is {today}). Reply with ONLY a JSON list of 0 to 2 short strings, for example "
                       '["Has a DSP exam on 14 October 2026"]. Reply [] if nothing qualifies.')
        out = llm_plain(instruction, question, raw=True)
        if not out:
            return
        start, end = out.find("["), out.rfind("]")
        facts = json.loads(out[start:end + 1]) if 0 <= start < end else []
        for fact in facts[:2]:
            if isinstance(fact, str) and 3 < len(fact) <= 140:
                if tool_remember(fact) in ("Saved to long-term memory.", "Updated my memory."):
                    show("(remembered: " + fact + ")")
    except Exception as e:
        print("Learn error:", repr(e))


# ---- the voice commands for all of the above

def suite_command(text):
    """Returns a reply, or None if this is not one of the suite commands."""
    t = re.sub(r"\bto-do'?s?\b|\bto do'?s?\b|\btodos\b", "todo", text)
    t = re.sub(r"\btasks? list\b", "todo list", t).strip()

    # start with Windows
    if re.search(r"\b(?:disable|turn off|remove|cancel)\b.*\b(?:startup|start up|autostart|auto start)\b"
                 r"|\b(?:stop|don'?t|do not)\b.*\bstart(?:ing)? (?:with|when|on) windows\b", t):
        return tool_disable_startup()
    if re.fullmatch(r"(?:is )?(?:the )?(?:startup|auto ?start)(?: enabled| on| set up)?|(?:do you|does jarvis) start with windows", t):
        return tool_startup_status()
    if re.search(r"\b(?:enable|turn on|set up|setup|activate|add)\b.*\b(?:startup|start up|autostart|auto start)\b"
                 r"|\bstart (?:jarvis )?(?:with|when|on|at) (?:windows|boot|login|startup)\b|\blaunch (?:jarvis )?(?:with|on|at) (?:windows|startup|boot)\b"
                 r"|\bstart automatically\b", t):
        return tool_enable_startup()

    # briefing
    if re.fullmatch(r"(?:good morning|morning briefing|daily briefing|briefing|brief me|start my day|give me (?:my |the )?(?:morning |daily )?(?:briefing|brief)"
                    r"|what'?s (?:my|the) day (?:looking )?like|what does my day look like)", t):
        return build_briefing()

    # notes
    m = re.fullmatch(r"(?:please )?(?:note down|note that|note|take a note(?: that| to)?|make a note(?: that| of| to)?|jot down|write down|add a note(?: that)?)\s*[:,]?\s+(.+)", t)
    if m:
        return tool_add_note(m.group(1))
    if re.fullmatch(r"(?:take|make|add) a note", t):
        return "What should I note down?"
    if re.fullmatch(r"(?:clear|delete|erase|remove) (?:all )?(?:of )?(?:my )?notes", t):
        return tool_clear_notes()
    if re.fullmatch(r"(?:(?:what are|what's|what is|read|show|list|tell me)(?: me)? )?(?:(?:my|the|all my) )?notes(?: please)?|what notes do i have|do i have any notes", t):
        return tool_list_notes()

    # to-do list
    for pattern in (r"(?:please )?add (?:a )?(?:task |todo )?(.+?) (?:to|on) (?:my |the )?todo(?: list)?",
                    r"(?:please )?add (?:to|on) (?:my |the )?todo(?: list)?[:, ]+(.+)",
                    r"(?:please )?(?:add|new|create) (?:a )?(?:task|todo)[:, ]+(.+)",
                    r"(?:please )?put (.+?) on (?:my |the )?todo(?: list)?"):
        m = re.fullmatch(pattern, t)
        if m:
            return tool_add_todo(m.group(1))
    if re.fullmatch(r"(?:clear|delete|erase|empty) (?:all )?(?:of )?(?:my |the )?(?:todo(?: list)?|tasks)", t):
        return tool_clear_todos()
    if re.fullmatch(r"(?:(?:what(?:'s| is| are)|read|show|list|tell me)(?: me)? )?(?:on )?(?:(?:my|the) )?(?:todo list|todo|tasks|pending tasks)(?: for today| today)?"
                    r"|what do i (?:have|need) to do(?: today)?", t):
        return tool_list_todos()
    for pattern in (r"(?:mark|check off|tick off|cross off)\s+(?:task |todo |number )?(.+?)(?:\s+(?:as )?(?:done|complete|completed|finished))?(?:\s+(?:on|in|from) (?:my )?todo(?: list)?)?",
                    r"(?:i(?:'m| am|'ve| have)? )?(?:done|finished|completed)(?: with)? (?:task |todo |number )?(.+)",
                    r"remove (.+?) from (?:my |the )?todo(?: list)?"):
        m = re.fullmatch(pattern, t)
        if m and m.group(1) not in ("it", "this", "that", "everything", "work", "for today", "for now", "eating", "the call"):
            return tool_complete_todo(m.group(1))

    # study timer
    reply = focus_command(t)
    if reply:
        return reply

    # files, clipboard
    reply = file_command(t)
    if reply:
        return reply
    reply = clip_command(t)
    if reply:
        return reply

    # memory
    m = re.fullmatch(r"(?:please )?(?:remember that|remember|keep in mind(?: that)?)\s+(?!to\b)(.+)", t)
    if m:
        return tool_remember(m.group(1))
    if re.fullmatch(r"what (?:do you|have you) (?:know|remember|remembered)(?: about me)?|what do you know about me|what have you learned about me", t):
        return tool_list_memory()
    m = re.fullmatch(r"forget (?:that |about |what i said about )?(.+)", t)
    if m and not re.search(r"conversation|chat|everything", m.group(1)) and m.group(1) not in ("it", "that", "this", "them"):
        return tool_forget(m.group(1))
    return None


'''

swap('STR = {"type": "STRING"}\n', NEW_CODE + 'STR = {"type": "STRING"}\n')

# ------------------------------------------------------------------ hook into the command flow

swap('    answer = time_answer(text)\n    if answer:\n        return answer\n\n    action = media_action(text)\n',
     '    answer = time_answer(text)\n    if answer:\n        return answer\n\n'
     '    extra = suite_command(text)\n    if extra:\n        return extra\n\n'
     '    action = media_action(text)\n')

swap('    awake = False  # True during the follow-up window after an answer\n',
     '    if STARTED_BY_WINDOWS and STARTUP_BRIEFING:  # Jarvis was started by Windows: greet with the briefing\n'
     '        try:\n'
     '            speak(build_briefing())\n'
     '        except Exception as e:\n'
     '            print("Briefing error:", repr(e))\n\n'
     '    awake = False  # True during the follow-up window after an answer\n')

# ------------------------------------------------------------------ tools the AI can call

swap(']}]\n\nFUNCTIONS = {\n',
     '''    {"name": "add_note", "description": "Save a quick note for the user.",
     "parameters": params({"text": STR}, ["text"])},
    {"name": "add_todo", "description": "Add a task to the user's to-do list.",
     "parameters": params({"task": STR}, ["task"])},
    {"name": "list_todos", "description": "Read out the user's pending to-do tasks."},
    {"name": "complete_todo", "description": "Mark a to-do task as done, by its number or some of its words.",
     "parameters": params({"which": STR}, ["which"])},
    {"name": "start_focus", "description": "Start a study focus (Pomodoro) timer. Minutes is optional.",
     "parameters": params({"minutes": NUM}, [])},
    {"name": "stop_focus", "description": "Stop the study focus timer."},
    {"name": "open_file", "description": "Find a file on the PC by part of its name and open it.",
     "parameters": params({"query": STR}, ["query"])},
    {"name": "clipboard_task", "description": "Work on the text the user copied. task is one of: summarize, explain, fix, shorten, formal, translate, read. For translate also give the language.",
     "parameters": params({"task": STR, "language": STR}, ["task"])},
    {"name": "morning_briefing", "description": "Give the morning briefing: time, weather, reminders and tasks."},
    {"name": "enable_startup", "description": "Make Jarvis start automatically when Windows starts."},
    {"name": "disable_startup", "description": "Stop Jarvis starting automatically with Windows."},
]}]

FUNCTIONS = {
''')

swap('    "open_folder": tool_open_folder,\n}\n',
     '''    "open_folder": tool_open_folder,
    "add_note": tool_add_note,
    "add_todo": tool_add_todo,
    "list_todos": tool_list_todos,
    "complete_todo": tool_complete_todo,
    "start_focus": tool_start_focus,
    "stop_focus": tool_stop_focus,
    "open_file": tool_open_file,
    "clipboard_task": tool_clipboard_task,
    "morning_briefing": lambda: build_briefing(),
    "enable_startup": tool_enable_startup,
    "disable_startup": tool_disable_startup,
}
''')

# ------------------------------------------------------------------ keep private data out of GitHub

try:
    ignore = ".gitignore"
    existing = open(ignore, encoding="utf-8").read() if os.path.exists(ignore) else ""
    add = [n for n in ("jarvis_notes.json", "jarvis_todo.json") if n not in existing]
    if add:
        with open(ignore, "a", encoding="utf-8") as f:
            f.write(("" if existing.endswith("\n") or not existing else "\n") + "\n".join(add) + "\n")
except OSError:
    pass

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

print("Done. Added: start with Windows + briefing, notes, to-do list, study timer, file finder,")
print("clipboard helper, smarter memory.")
print("Backup saved as main.py.bak")
