import collections
import datetime
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import numpy as np
import psutil
import sounddevice as sd

GOOGLE_SPEECH_KEY = "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"
GEMINI_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash"]
HISTORY = []  # recent conversation (cleared when Jarvis closes)
LAST_BRAIN = "none yet"  # which brain answered last
MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_memory.json")

SYSTEM_PROMPT = (
    "You are Jarvis, a calm, witty, loyal AI assistant like the one in Iron Man. "
    "Be proactive and helpful. Answer in 1 to 3 short sentences in plain spoken English. "
    "Do not use markdown, bullet points, emojis or special symbols."
)

# Only apps in this list can be opened (safe: Jarvis cannot run random programs).
APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "file explorer": "explorer.exe",
    "command prompt": "cmd.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
    "paint": "mspaint.exe",
    "chrome": "chrome",
    "vs code": "code",
    "spotify": "spotify:",
}


# ---------------------------------------------------------------- voice

def speak(text):
    """Print the reply and say it out loud using the Windows built-in voice."""
    print("Jarvis:", text)
    env = dict(os.environ, JARVIS_TEXT=text.replace("\n", " "))
    subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Speak($env:JARVIS_TEXT)",
        ],
        env=env,
    )


def recognize(data, fs):
    """Send 16 kHz raw audio straight to Google speech recognition."""
    samples = data.flatten().astype(np.float32)
    n = int(len(samples) * 16000 / fs)
    positions = np.linspace(0, len(samples) - 1, n)
    resampled = np.interp(positions, np.arange(len(samples)), samples).astype(np.int16)

    url = "https://www.google.com/speech-api/v2/recognize?" + urllib.parse.urlencode(
        {"client": "chromium", "lang": "en-US", "key": GOOGLE_SPEECH_KEY}
    )
    request = urllib.request.Request(
        url,
        data=resampled.tobytes(),
        headers={"Content-Type": "audio/l16; rate=16000"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")

    for line in body.split("\n"):
        if not line.strip():
            continue
        result = json.loads(line).get("result")
        if result:
            alternatives = result[0].get("alternative", [])
            if alternatives:
                return alternatives[0]["transcript"].lower()
    return ""


def listen(seconds=5):
    """Record from the microphone and return the recognised text (lowercase)."""
    fs = int(sd.query_devices(kind="input")["default_samplerate"])
    print("Listening... speak now")
    data = sd.rec(int(seconds * fs), samplerate=fs, channels=1, dtype="int16")
    sd.wait()

    level = int(abs(data).max())
    print("Mic level:", level)
    if level < 300:
        print("Too quiet. Speak louder or check your mic in Windows Sound settings.")
        return ""

    try:
        text = recognize(data, fs)
        if not text:
            print("Could not understand, try again.")
        return text
    except urllib.error.URLError as e:
        print("Internet/Google error:", e)
    except Exception as e:
        print("Error:", repr(e))
    return ""


# ---------------------------------------------------------------- long-term memory

def load_memory():
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_memory(facts):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=2)


# ---------------------------------------------------------------- tools Jarvis can use

def get_json(url):
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def tool_open_app(name):
    key = name.lower().strip()
    target = APPS.get(key)
    if not target:
        return f"I do not know the app {name}. I can open: " + ", ".join(APPS)
    try:
        os.startfile(target)
        return f"Opened {key}."
    except Exception as e:
        return f"Could not open {key}: {e}"


def tool_web_search(query):
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"Opened a Google search for {query}."


def tool_open_website(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}."


def tool_get_system_status():
    parts = [
        f"CPU at {psutil.cpu_percent(interval=0.5)} percent",
        f"RAM at {psutil.virtual_memory().percent} percent",
    ]
    battery = psutil.sensors_battery()
    if battery:
        state = "charging" if battery.power_plugged else "not charging"
        parts.append(f"battery at {int(battery.percent)} percent, {state}")
    return ", ".join(parts)


def tool_set_volume(action):
    keys = {"up": 175, "down": 174, "mute": 173}
    code = keys.get(action)
    if code is None:
        return "Volume action must be up, down or mute."
    presses = 1 if action == "mute" else 5
    subprocess.run([
        "powershell", "-NoProfile", "-Command",
        f"$w = New-Object -ComObject WScript.Shell; "
        f"1..{presses} | ForEach-Object {{ $w.SendKeys([char]{code}) }}",
    ])
    return f"Volume {action} done."


def tool_set_reminder(minutes, message):
    minutes = float(minutes)
    timer = threading.Timer(minutes * 60, lambda: speak("Reminder: " + message))
    timer.daemon = True
    timer.start()
    return f"Reminder set for {minutes:g} minutes from now."


def tool_get_weather(city):
    try:
        geo = get_json(
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode({"name": city, "count": 1})
        )
        places = geo.get("results")
        if not places:
            return f"I could not find a place called {city}."
        p = places[0]
        weather = get_json(
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode({
                "latitude": p["latitude"],
                "longitude": p["longitude"],
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            })
        )
        c = weather["current"]
        return (
            f"In {p['name']}: {c['temperature_2m']} degrees Celsius, "
            f"humidity {c['relative_humidity_2m']} percent, "
            f"wind {c['wind_speed_10m']} kilometres per hour, "
            f"WMO weather code {c['weather_code']}."
        )
    except Exception as e:
        return f"Weather lookup failed: {e}"


def tool_remember(fact):
    facts = load_memory()
    facts.append(fact)
    save_memory(facts)
    return "Saved to long-term memory."


def tool_forget(keyword):
    facts = load_memory()
    kept = [f for f in facts if keyword.lower() not in f.lower()]
    save_memory(kept)
    return f"Removed {len(facts) - len(kept)} memory item(s)."


STR = {"type": "STRING"}
NUM = {"type": "NUMBER"}


def params(props, required):
    return {"type": "OBJECT", "properties": props, "required": required}


TOOLS = [{"functionDeclarations": [
    {"name": "open_app",
     "description": "Open a desktop app. Available: " + ", ".join(APPS),
     "parameters": params({"name": STR}, ["name"])},
    {"name": "web_search",
     "description": "Open a Google search in the browser.",
     "parameters": params({"query": STR}, ["query"])},
    {"name": "open_website",
     "description": "Open a website by URL or domain, for example youtube.com.",
     "parameters": params({"url": STR}, ["url"])},
    {"name": "get_system_status",
     "description": "Get CPU, RAM and battery status of this PC."},
    {"name": "set_volume",
     "description": "Change the PC volume.",
     "parameters": params({"action": {"type": "STRING", "enum": ["up", "down", "mute"]}}, ["action"])},
    {"name": "set_reminder",
     "description": "Remind the user out loud after some minutes.",
     "parameters": params({"minutes": NUM, "message": STR}, ["minutes", "message"])},
    {"name": "get_weather",
     "description": "Get the current weather for a city.",
     "parameters": params({"city": STR}, ["city"])},
    {"name": "remember",
     "description": "Save a lasting fact about the user (name, preferences, plans) to long-term memory.",
     "parameters": params({"fact": STR}, ["fact"])},
    {"name": "forget",
     "description": "Delete saved memory items that contain a keyword.",
     "parameters": params({"keyword": STR}, ["keyword"])},
]}]

FUNCTIONS = {
    "open_app": tool_open_app,
    "web_search": tool_web_search,
    "open_website": tool_open_website,
    "get_system_status": tool_get_system_status,
    "set_volume": tool_set_volume,
    "set_reminder": tool_set_reminder,
    "get_weather": tool_get_weather,
    "remember": tool_remember,
    "forget": tool_forget,
}


def run_tool(name, args):
    func = FUNCTIONS.get(name)
    if not func:
        return f"Unknown tool {name}."
    try:
        return str(func(**args))
    except Exception as e:
        return f"Tool {name} failed: {e}"


# ---------------------------------------------------------------- the brain

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = []  # filled automatically from Groq's live model list


def find_groq_models(key):
    """Ask Groq which chat models exist right now and pick the best ones first."""
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": "Bearer " + key, "User-Agent": "jarvis/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print("Could not get Groq model list:", repr(e))
        return []
    skip = ("whisper", "guard", "tts", "orpheus", "playai", "embed", "safeguard")
    ids = [m["id"] for m in data.get("data", [])
           if not any(s in m["id"].lower() for s in skip)]
    prefer = ("llama-3.3", "gpt-oss", "llama-4", "llama-3.1", "qwen", "kimi")
    ids.sort(key=lambda i: next((n for n, p in enumerate(prefer) if p in i.lower()), len(prefer)))
    return ids


def build_system_prompt():
    now = datetime.datetime.now().strftime("%A, %d %B %Y, %I:%M %p")
    facts = load_memory()
    memory = ("Known about the user: " + "; ".join(facts) + ". ") if facts else ""
    return (
        SYSTEM_PROMPT
        + f" Current date and time: {now}. "
        + memory
        + "Use your tools whenever the user asks you to do something on the computer. "
        + "Call remember when the user shares something worth keeping long term."
    )


def to_openai_tools():
    """Convert our tool list into the OpenAI/Groq format (lowercase types)."""
    def fix(x):
        if isinstance(x, dict):
            return {k: (v.lower() if k == "type" and isinstance(v, str) else fix(v))
                    for k, v in x.items()}
        if isinstance(x, list):
            return [fix(i) for i in x]
        return x

    tools = []
    for decl in TOOLS[0]["functionDeclarations"]:
        decl = dict(decl)
        decl.setdefault("parameters", {"type": "OBJECT", "properties": {}})
        tools.append({"type": "function", "function": fix(decl)})
    return tools


OPENAI_TOOLS = to_openai_tools()


def clean(text):
    return text.replace("*", "").replace("#", "").replace("`", "").strip()


def post_json(url, payload, headers):
    """POST JSON and return the reply as a dict, or None if it failed."""
    body = json.dumps(payload).encode("utf-8")
    name = url.split("/")[2]
    for attempt in range(2):
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"AI error {e.code} from {name}, attempt {attempt + 1}")
            if e.code in (429, 500, 503) and attempt == 0:
                time.sleep(2)
                continue
            return None
        except Exception as e:
            print(f"AI error from {name}:", repr(e))
            return None
    return None


def ask_groq(question):
    """Fast brain: Groq. Returns text, or None if it failed."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
        "User-Agent": "jarvis/1.0",
    }
    if not GROQ_MODELS:
        GROQ_MODELS.extend(find_groq_models(key))
    for model in GROQ_MODELS[:3]:
        messages = (
            [{"role": "system", "content": build_system_prompt()}]
            + HISTORY
            + [{"role": "user", "content": question}]
        )
        for _ in range(5):  # at most 5 tool rounds per question
            result = post_json(
                GROQ_URL,
                {"model": model, "messages": messages, "tools": OPENAI_TOOLS},
                headers,
            )
            if not result:
                break
            try:
                message = result["choices"][0]["message"]
            except (KeyError, IndexError):
                break

            calls = message.get("tool_calls")
            if not calls:
                text = clean(message.get("content") or "")
                if text:
                    print(f"[groq model: {model}]")
                    return text
                break

            messages.append({
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": calls,
            })
            for call in calls:
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                output = run_tool(call["function"]["name"], args)
                print(f"[tool] {call['function']['name']} -> {output}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": output,
                })
    return None


def ask_gemini(question):
    """Backup brain: Gemini. Returns text, or None if it failed."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    history = [
        {"role": "user" if h["role"] == "user" else "model",
         "parts": [{"text": h["content"]}]}
        for h in HISTORY
    ]
    user_turn = {"role": "user", "parts": [{"text": question}]}

    for model in GEMINI_MODELS:
        contents = history + [user_turn]
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent")
        for _ in range(5):
            result = post_json(url, {
                "systemInstruction": {"parts": [{"text": build_system_prompt()}]},
                "contents": contents,
                "tools": TOOLS,
            }, headers)
            if not result:
                break
            try:
                content = result["candidates"][0]["content"]
            except (KeyError, IndexError):
                break

            parts = content.get("parts", [])
            calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not calls:
                text = clean("".join(p.get("text", "") for p in parts))
                if text:
                    return text
                break

            contents.append(content)  # keep the model's tool request exactly as sent
            responses = []
            for call in calls:
                output = run_tool(call["name"], call.get("args", {}))
                print(f"[tool] {call['name']} -> {output}")
                responses.append({
                    "functionResponse": {"name": call["name"], "response": {"result": output}}
                })
            contents.append({"role": "user", "parts": responses})
    return None


def ask_ai(question):
    """Groq first (fast). If it fails, fall back to Gemini."""
    global LAST_BRAIN
    if not os.environ.get("GROQ_API_KEY") and not os.environ.get("GEMINI_API_KEY"):
        return "My brain key is not set yet. Please set the Groq API key first."

    text = ask_groq(question)
    if text:
        LAST_BRAIN = "Groq"
    else:
        text = ask_gemini(question)
        if text:
            LAST_BRAIN = "Gemini"
    if not text:
        return "Sorry, my brain is busy right now. Please try again in a minute."

    print(f"[brain: {LAST_BRAIN}]")
    HISTORY.append({"role": "user", "content": question})
    HISTORY.append({"role": "assistant", "content": text})
    del HISTORY[:-12]
    return text


def check_one(name, url, headers, key):
    """Test one brain. Returns a short summary and prints the details."""
    if not key:
        print(f"{name}: NO KEY found in this terminal. Restart VS Code or Windows.")
        return f"{name} key is missing"
    request = urllib.request.Request(url, headers=headers)
    try:
        urllib.request.urlopen(request, timeout=10)
        print(f"{name}: OK")
        return f"{name} is working"
    except urllib.error.HTTPError as e:
        hints = {
            401: "key is wrong, make a new one",
            403: "request blocked",
            429: "rate limit reached, wait a bit",
        }
        print(f"{name}: error {e.code} ({hints.get(e.code, 'see the code online')})")
        return f"{name} has error {e.code}"
    except Exception as e:
        print(f"{name}: could not connect ({e!r}). Check your internet.")
        return f"{name} could not connect"


def check_brains():
    """Self-check: is each API key present and accepted? Prints and returns a summary."""
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    groq = check_one(
        "Groq",
        "https://api.groq.com/openai/v1/models",
        {"Authorization": "Bearer " + str(groq_key), "User-Agent": "jarvis/1.0"},
        groq_key,
    )
    if groq_key:
        GROQ_MODELS[:] = find_groq_models(groq_key)
        print("Groq models to use:", GROQ_MODELS[:3])
    gemini = check_one(
        "Gemini",
        "https://generativelanguage.googleapis.com/v1beta/models",
        {"x-goog-api-key": str(gemini_key), "User-Agent": "jarvis/1.0"},
        gemini_key,
    )
    return groq + ". " + gemini + "."


# ---------------------------------------------------------------- main loop

def handle(command):
    """Run one command. Returns False when Jarvis should quit."""
    words = command.split()

    if len(words) <= 3 and any(w in ("stop", "exit", "bye", "goodbye") for w in words):
        speak("Goodbye, see you soon!")
        return False
    if len(words) <= 4 and "forget" in words and "conversation" in words:
        HISTORY.clear()
        speak("Okay, I have forgotten our conversation.")
        return True

    if "brain" in words:
        if "check" in words or "test" in words:
            speak(check_brains())
        else:
            if LAST_BRAIN == "none yet":
                speak("Ask me something first, then I can tell you which brain answered.")
            else:
                speak(f"My last answer came from {LAST_BRAIN}.")
        return True

    print("Thinking...")
    speak(ask_ai(command))
    return True


# ---------------------------------------------------------------- hands-free (wake word)

USE_WAKE_WORD = True  # False = old style: press Enter, then speak
WAKE_WORDS = ("jarvis", "jarves", "jervis")
THRESHOLD = 600  # how loud counts as speech (set automatically at startup)


def mic_rate():
    return int(sd.query_devices(kind="input")["default_samplerate"])


def calibrate():
    """Listen to the room for 1 second so Jarvis knows what 'quiet' sounds like."""
    global THRESHOLD
    fs = mic_rate()
    print("Calibrating... stay quiet for 1 second")
    data = sd.rec(int(fs * 1.0), samplerate=fs, channels=1, dtype="int16")
    sd.wait()
    THRESHOLD = max(600, int(abs(data).max()) * 2.5)
    print("Speech threshold set to", THRESHOLD)


def record_until_silence(wait_seconds=None, max_seconds=10):
    """Wait for speech, record it, stop after 1 second of silence.
    Returns (audio, rate), or None if nothing was said within wait_seconds."""
    fs = mic_rate()
    block = int(fs * 0.1)  # 0.1 second per block
    before = collections.deque(maxlen=3)  # keeps the moment just before speech starts
    chunks = []
    started = False
    silent = 0
    waited = 0.0
    with sd.InputStream(samplerate=fs, channels=1, dtype="int16", blocksize=block) as stream:
        while True:
            data, _ = stream.read(block)
            loud = int(abs(data).max()) > THRESHOLD
            if not started:
                if loud:
                    started = True
                    chunks.extend(before)
                    chunks.append(data)
                else:
                    before.append(data)
                    waited += 0.1
                    if wait_seconds is not None and waited >= wait_seconds:
                        return None
            else:
                chunks.append(data)
                silent = 0 if loud else silent + 1
                if silent >= 10 or len(chunks) >= max_seconds * 10:
                    break
    return np.concatenate(chunks), fs


def transcribe(audio):
    if audio is None:
        return ""
    data, fs = audio
    try:
        return recognize(data, fs)
    except urllib.error.URLError as e:
        print("Internet/Google error:", e)
    except Exception as e:
        print("Error:", repr(e))
    return ""


def wait_for_wake_word():
    """Listen forever. When someone says 'Jarvis', return what came after it (may be empty)."""
    while True:
        text = transcribe(record_until_silence())
        if not text:
            continue
        print("(heard:", text + ")")
        for word in WAKE_WORDS:
            if word in text:
                return text.split(word, 1)[1].strip(" ,.")


def main():
    print("--- Brain self-check ---")
    check_brains()
    print("------------------------")

    if USE_WAKE_WORD:
        calibrate()
        speak("Jarvis is online. Say Jarvis, then your command.")
    else:
        speak("Jarvis is online. How can I help?")

    while True:
        try:
            if USE_WAKE_WORD:
                command = wait_for_wake_word()
                if not command:  # they only said "Jarvis" - ask for the command
                    speak("Yes?")
                    command = transcribe(record_until_silence(wait_seconds=6))
            else:
                input("\nPress Enter, then speak: ")
                command = listen()
        except (KeyboardInterrupt, EOFError):
            print("\nStopped.")
            break

        if not command:
            continue
        print("You:", command)

        if not handle(command):
            break


if __name__ == "__main__":
    main()