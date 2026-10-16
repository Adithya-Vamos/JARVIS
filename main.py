import asyncio
import collections
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
import webbrowser

import numpy as np
import psutil
import sounddevice as sd


def app_dir():
    """Folder where Jarvis lives (works for main.py and for the built Jarvis.exe)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


if getattr(sys, "frozen", False):  # the .exe has no console window, so keep a log file
    try:
        _log = open(os.path.join(app_dir(), "jarvis.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = _log
    except Exception:
        pass

NOWIN = 0x08000000 if os.name == "nt" else 0  # stops black PowerShell windows flashing up

# ---------------------------------------------------------------- settings you can tune

USE_WAKE_WORD = True      # False = old style: press Enter, then speak
ALWAYS_LISTENING = False  # True = answers EVERYTHING it hears (no need to say "Jarvis")
WAKE_WORDS = ("jarvis", "jarves", "jervis")
PAUSE_SECONDS = 2.0       # how long you must be silent before Jarvis thinks you finished
MAX_SECONDS = 60          # longest single question
FOLLOW_UP_SECONDS = 15    # after an answer, Jarvis keeps listening this long without the name
BROWSER = "chrome"        # "chrome" = open links in YOUR Chrome profile; "default" = Windows default
CHROME_PROFILE = "auto"   # "auto" = the profile you used last, or type "Default" / "Profile 1"
USE_HUD = True            # the futuristic window (needs: pip install pywebview)
HUD_ON_TOP = False        # True = keep the HUD above other windows
NEURAL_VOICE = True       # natural voice (needs: pip install edge-tts + internet)
VOICE = "en-GB-RyanNeural"  # a calm British voice. Others: en-US-GuyNeural, en-IN-PrabhatNeural
VOICE_RATE = "+5%"
QUIET_AFTER_OPEN = True   # go silent after opening an app or website
QUIET_FOLLOW_UP_SECONDS = 8  # in quiet mode, how long it keeps listening after you call it
HOME_CITY = "Bangalore"   # used when you ask for the weather without a city
LOCAL_WAKE = False        # True = listen for "Hey Jarvis" on this laptop (needs: pip install openwakeword)
LOCAL_WAKE_THRESHOLD = 0.5  # lower = hears you more easily but may trigger by mistake
GOOGLE_CREDENTIALS = os.path.join(app_dir(), "google_credentials.json")  # you download this once (see setup)
GOOGLE_TOKEN = os.path.join(app_dir(), "jarvis_google_token.json")      # Jarvis saves your sign-in here
VISION_HIDE_HUD = True    # hide the Jarvis window for a moment so it does not cover your screen
LOCAL_TZ = datetime.timezone(datetime.timedelta(hours=5, minutes=30), "IST")  # India Standard Time (no daylight saving)
USER_NAME = "Mitch"       # how the morning briefing greets you
STARTUP_BRIEFING = True   # when Windows starts Jarvis, give the morning briefing
FOCUS_MINUTES = 25        # study timer: focus length
SHORT_BREAK = 5           # study timer: normal break
LONG_BREAK = 15           # study timer: long break (after every 4th focus round)
ROUNDS_BEFORE_LONG = 4
EXTRA_SEARCH_FOLDERS = []  # more folders for the file finder, e.g. [r"D:\College"]
FILE_SEARCH_SECONDS = 4   # the file finder gives up after this long

GOOGLE_SPEECH_KEY = "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"
GEMINI_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash"]
HISTORY = []  # recent conversation (cleared when Jarvis closes)
LAST_BRAIN = "none yet"
MEMORY_FILE = os.path.join(app_dir(), "jarvis_memory.json")

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

SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "whatsapp": "https://web.whatsapp.com",
    "maps": "https://maps.google.com",
    "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com",
    "wikipedia": "https://www.wikipedia.org",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.in",
}

MEDIA_PHRASES = {
    "pause": "play_pause", "pause music": "play_pause", "pause the music": "play_pause",
    "resume": "play_pause", "resume music": "play_pause", "play": "play_pause",
    "next": "next", "next song": "next", "next track": "next", "skip": "next",
    "previous": "previous", "previous song": "previous", "previous track": "previous",
}


def norm(text):
    """'You Tube' -> 'youtube' so spelling and spacing do not matter."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


# ---------------------------------------------------------------- quiet mode state

STATE = {"lock": False, "woken": False, "enter_quiet": False}
# lock   = quiet mode is on (Jarvis only answers to "Hey Jarvis")
# woken  = you just called it, so it may talk until the follow-up window ends


def set_lock(flag, woken=False):
    STATE["lock"] = flag
    STATE["woken"] = woken
    STATE["gen"] = STATE.get("gen", 0) + 1  # tells the listener the mode changed
    HUD.quiet(flag)


def mark_quiet():
    """Called whenever Jarvis opens an app or website: it goes silent afterwards."""
    if QUIET_AFTER_OPEN:
        STATE["enter_quiet"] = True


def run_hidden(args, **kwargs):
    return subprocess.run(args, creationflags=NOWIN, **kwargs)


# ---------------------------------------------------------------- the HUD window

HUD_HTML = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>JARVIS</title>
<style>
  :root { --c: #19e6ff; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #02060d; color: #bfefff;
    font-family: "Segoe UI", system-ui, sans-serif; overflow: hidden; user-select: none; }
  canvas { position: fixed; inset: 0; width: 100%; height: 100%; }
  .top { position: fixed; top: 14px; left: 22px; right: 22px; display: flex;
    justify-content: space-between; align-items: flex-start; pointer-events: none; }
  .tag { font-size: 11px; letter-spacing: .28em; color: #4f9fb4; text-transform: uppercase; }
  #clock { font-size: 24px; letter-spacing: .14em; color: #19e6ff; font-weight: 300; }
  #date { margin-top: 2px; }
  .stats { text-align: right; line-height: 1.7; }
  .stats b { color: #19e6ff; font-weight: 400; }
  #status { position: fixed; left: 0; right: 0; text-align: center; font-size: 13px;
    letter-spacing: .38em; text-transform: uppercase; color: #19e6ff; text-shadow: 0 0 12px currentColor; }
  #brand { position: fixed; left: 0; right: 0; text-align: center; font-size: 22px;
    letter-spacing: .6em; font-weight: 300; color: #d9f7ff; text-shadow: 0 0 18px #19e6ff; }
  #log { position: fixed; left: 50%; transform: translateX(-50%); bottom: 22px;
    width: min(760px, 86vw); font-size: 14px; line-height: 1.55; }
  .line { padding: 3px 12px; border-left: 2px solid #19e6ff55; margin-top: 4px;
    background: linear-gradient(90deg, #0a2230aa, transparent); animation: in .35s ease-out; }
  .line.you { border-left-color: #3dffd0aa; color: #9ff7e2; }
  .line.jarvis { color: #cfefff; }
  .line .who { font-size: 10px; letter-spacing: .25em; opacity: .7; margin-right: 10px; }
  @keyframes in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  #qbtn { position: fixed; right: 22px; bottom: 22px; font: inherit; font-size: 11px;
    letter-spacing: .25em; color: #19e6ff; background: #06202c; border: 1px solid #19e6ff66;
    padding: 9px 14px; cursor: pointer; border-radius: 3px; user-select: none; }
  #qbtn:hover { background: #0a3347; }
  #mctl { position: fixed; right: 22px; top: 98px; display: flex; flex-direction: column; gap: 6px; }
  .mbtn { font: inherit; font-size: 11px; letter-spacing: .25em; color: #19e6ff; background: #06202c;
    border: 1px solid #19e6ff66; padding: 8px 14px; cursor: pointer; border-radius: 3px; user-select: none; }
  .mbtn:hover { background: #0a3347; }
</style>
</head>
<body>
<canvas id="cv"></canvas>
<div class="top">
  <div><div id="clock">00:00:00</div><div id="date" class="tag"></div></div>
  <div class="stats tag">CPU <b id="cpu">--</b>%<br>RAM <b id="ram">--</b>%<br>PWR <b id="bat">--</b></div>
</div>
<div id="brand">J.A.R.V.I.S</div>
<div id="status">STARTING</div>
<div id="log"></div>
<div id="mctl">
  <button class="mbtn" id="mprev" title="Previous song">PREV</button>
  <button class="mbtn" id="mplay" title="Play or pause">PLAY / PAUSE</button>
  <button class="mbtn" id="mnext" title="Next song">NEXT</button>
</div>
<button id="qbtn" title="Switch quiet mode on or off">QUIET</button>
<script>
(function () {
  var cv = document.getElementById('cv');
  var ctx = cv.getContext('2d');
  var W = 0, H = 0;
  function resize() {
    var d = window.devicePixelRatio || 1;
    W = window.innerWidth; H = window.innerHeight;
    cv.width = W * d; cv.height = H * d;
    ctx.setTransform(d, 0, 0, d, 0, 0);
    var cy = H / 2 - 30, R = Math.min(W, H) * 0.27;
    document.getElementById('brand').style.top = (cy - 12) + 'px';
    document.getElementById('status').style.top = (cy + R * 1.38) + 'px';
  }
  window.addEventListener('resize', resize);
  resize();

  var COL = {
    idle: [25, 230, 255], listening: [61, 255, 208], thinking: [255, 176, 46],
    speaking: [127, 180, 255], standby: [40, 100, 135]
  };
  var LABEL = {
    idle: 'ONLINE  -  SAY "JARVIS"', listening: 'LISTENING', thinking: 'THINKING',
    speaking: 'SPEAKING', standby: 'STANDBY  -  SAY "HEY JARVIS"'
  };
  var S = { name: 'idle', cur: [25, 230, 255], lvl: 0, tgt: 0, a: 0, b: 0 };

  function lerp(a, b, t) { return a + (b - a) * t; }

  function frame(ts) {
    var t = ts / 1000;
    var tc = COL[S.name] || COL.idle;
    for (var i = 0; i < 3; i++) S.cur[i] = lerp(S.cur[i], tc[i], 0.06);
    if (S.name === 'speaking') S.tgt = 0.30 + 0.28 * Math.abs(Math.sin(t * 5.3)) * (0.65 + 0.35 * Math.sin(t * 1.9));
    else if (S.name === 'thinking') S.tgt = 0.12 + 0.08 * Math.sin(t * 6);
    else if (S.name === 'standby') S.tgt = 0;
    else S.tgt *= 0.9;
    S.lvl = lerp(S.lvl, S.tgt, 0.3);
    var speed = S.name === 'thinking' ? 2.2 : (S.name === 'standby' ? 0.25 : 1);
    S.a += 0.006 * speed; S.b -= 0.009 * speed;

    ctx.clearRect(0, 0, W, H);
    var cx = W / 2, cy = H / 2 - 30, R = Math.min(W, H) * 0.27;
    var dim = S.name === 'standby' ? 0.55 : 1;
    function rgba(a) {
      return 'rgba(' + (S.cur[0] | 0) + ',' + (S.cur[1] | 0) + ',' + (S.cur[2] | 0) + ',' + (a * dim) + ')';
    }

    var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * (0.9 + S.lvl * 0.5));
    g.addColorStop(0, rgba(0.22 + S.lvl * 0.5));
    g.addColorStop(0.6, rgba(0.06));
    g.addColorStop(1, rgba(0));
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, R * 1.3, 0, Math.PI * 2); ctx.fill();

    function arcs(r, n, gap, rot, lw, alpha) {
      ctx.lineWidth = lw; ctx.strokeStyle = rgba(alpha);
      var seg = Math.PI * 2 / n;
      for (var k = 0; k < n; k++) {
        ctx.beginPath();
        ctx.arc(cx, cy, r, rot + k * seg, rot + k * seg + seg * (1 - gap));
        ctx.stroke();
      }
    }
    arcs(R * 1.18, 3, 0.55, S.a, 2, 0.75);
    arcs(R * 1.00, 24, 0.45, S.b * 1.6, 3, 0.55);
    arcs(R * 0.82, 6, 0.30, S.a * 2.2, 1.5, 0.70);

    ctx.lineWidth = 1; ctx.strokeStyle = rgba(0.35);
    for (var j = 0; j < 120; j++) {
      var ang = j / 120 * Math.PI * 2 + S.a * 0.4;
      var r1 = R * 1.28, r2 = r1 + (j % 5 === 0 ? 10 : 5);
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(ang) * r1, cy + Math.sin(ang) * r1);
      ctx.lineTo(cx + Math.cos(ang) * r2, cy + Math.sin(ang) * r2);
      ctx.stroke();
    }

    var bars = 72;
    ctx.lineWidth = 3; ctx.lineCap = 'round';
    for (var q = 0; q < bars; q++) {
      var an = q / bars * Math.PI * 2 - Math.PI / 2;
      var noise = Math.abs(Math.sin(q * 1.7 + t * 3.1)) * Math.abs(Math.cos(q * 0.9 - t * 2.3));
      var len = 3 + S.lvl * R * 0.55 * (0.35 + 0.65 * noise);
      var r0 = R * 0.56;
      ctx.strokeStyle = rgba(0.85);
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(an) * r0, cy + Math.sin(an) * r0);
      ctx.lineTo(cx + Math.cos(an) * (r0 + len), cy + Math.sin(an) * (r0 + len));
      ctx.stroke();
    }

    ctx.lineWidth = 2; ctx.strokeStyle = rgba(0.9);
    ctx.beginPath(); ctx.arc(cx, cy, R * 0.50, 0, Math.PI * 2); ctx.stroke();
    var pulse = 0.5 + 0.5 * Math.sin(t * (S.name === 'standby' ? 0.8 : 2.4));
    ctx.fillStyle = rgba(0.10 + 0.10 * pulse + S.lvl * 0.4);
    ctx.beginPath(); ctx.arc(cx, cy, R * 0.47, 0, Math.PI * 2); ctx.fill();

    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  var statusEl = document.getElementById('status');
  var qbtn = document.getElementById('qbtn');
  var logEl = document.getElementById('log');

  window.hud = {
    setState: function (name, label) {
      if (!COL[name]) name = 'idle';
      S.name = name;
      statusEl.textContent = label || LABEL[name];
      var c = COL[name];
      statusEl.style.color = 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')';
    },
    level: function (v) { S.tgt = Math.max(S.tgt, Math.min(1, v)); },
    log: function (role, text) {
      var d = document.createElement('div');
      d.className = 'line ' + role;
      var who = document.createElement('span');
      who.className = 'who';
      who.textContent = role === 'you' ? 'YOU' : 'JARVIS';
      var body = document.createElement('span');
      body.textContent = text;
      d.appendChild(who); d.appendChild(body);
      logEl.appendChild(d);
      while (logEl.children.length > 4) logEl.removeChild(logEl.firstChild);
    },
    stats: function (cpu, ram, bat) {
      document.getElementById('cpu').textContent = Math.round(cpu);
      document.getElementById('ram').textContent = Math.round(ram);
      document.getElementById('bat').textContent = bat;
    },
    quiet: function (on) { qbtn.textContent = on ? 'WAKE UP' : 'QUIET'; }
  };

  qbtn.onclick = function () {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.toggle_quiet().then(function (on) { window.hud.quiet(on); });
    }
  };

  function media(a) {
    if (window.pywebview && window.pywebview.api) { window.pywebview.api.media(a); }
  }
  document.getElementById('mprev').onclick = function () { media('previous'); };
  document.getElementById('mplay').onclick = function () { media('play_pause'); };
  document.getElementById('mnext').onclick = function () { media('next'); };

  function tick() {
    var n = new Date();
    function p(x) { return (x < 10 ? '0' : '') + x; }
    document.getElementById('clock').textContent = p(n.getHours()) + ':' + p(n.getMinutes()) + ':' + p(n.getSeconds());
    document.getElementById('date').textContent =
      n.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
  }
  tick(); setInterval(tick, 1000);
  window.hud.setState('idle', 'STARTING');
})();
</script>
</body>
</html>
"""


class Hud:
    """The futuristic window. Does nothing when USE_HUD is False or pywebview is missing."""

    def __init__(self):
        self.window = None
        self.ready = False
        self._last_level = 0.0

    def _js(self, code):
        if self.window is None or not self.ready:
            return
        try:
            self.window.evaluate_js(code)
        except Exception:
            pass

    def state(self, name, label=None):
        self._js(f"hud.setState({json.dumps(name)}, {json.dumps(label)})")

    def log(self, role, text):
        self._js(f"hud.log({json.dumps(role)}, {json.dumps(text)})")

    def level(self, value):
        now = time.time()
        if now - self._last_level < 0.07:
            return
        self._last_level = now
        self._js(f"hud.level({min(1.0, float(value) / 9000.0):.3f})")

    def stats(self, cpu, ram, battery):
        self._js(f"hud.stats({float(cpu)}, {float(ram)}, {json.dumps(battery)})")

    def quiet(self, flag):
        self._js(f"hud.quiet({'true' if flag else 'false'})")


HUD = Hud()


class HudApi:
    """Buttons in the HUD call these."""

    def media(self, action):
        tool_media_control(action)
        return True

    def toggle_quiet(self):
        set_lock(not STATE["lock"])
        show("Quiet mode on. Say Hey Jarvis." if STATE["lock"] else "Quiet mode off.")
        return STATE["lock"]


def stats_loop():
    while True:
        try:
            battery = psutil.sensors_battery()
            text = "AC" if battery is None else f"{int(battery.percent)}%"
            HUD.stats(psutil.cpu_percent(interval=None), psutil.virtual_memory().percent, text)
        except Exception:
            pass
        time.sleep(2)


def run_with_hud(target):
    """Open the HUD and run Jarvis inside it. Falls back to the plain console."""
    if not USE_HUD:
        target()
        return
    try:
        import webview
    except Exception as e:
        print("HUD not available (run: python -m pip install pywebview):", repr(e))
        target()
        return

    started = []
    window = webview.create_window(
        "JARVIS", html=HUD_HTML, js_api=HudApi(), width=1000, height=680,
        min_size=(760, 520), background_color="#02060d", on_top=HUD_ON_TOP,
    )
    HUD.window = window

    def worker():
        started.append(True)
        try:
            window.events.loaded.wait(15)
        except Exception:
            time.sleep(2)
        try:
            window.show()
            window.restore()
        except Exception:
            pass
        HUD.ready = True
        threading.Thread(target=stats_loop, daemon=True).start()
        try:
            target()
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            try:
                window.destroy()
            except Exception:
                pass

    try:
        webview.start(worker)
    except Exception as e:
        print("HUD failed to open:", repr(e))
    if started:
        os._exit(0)  # window closed or Jarvis said goodbye
    HUD.window = None
    target()  # the HUD did not open: run in the console instead


# ---------------------------------------------------------------- voice out

def sapi_speak(text):
    """The robotic built-in Windows voice (always works, no internet)."""
    env = dict(os.environ, JARVIS_TEXT=text.replace("\n", " "))
    run_hidden(
        [
            "powershell", "-NoProfile", "-Command",
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Speak($env:JARVIS_TEXT)",
        ],
        env=env,
    )


def play_mp3(path):
    """Play an mp3 with Windows' own player and wait until it finishes."""
    import ctypes
    mci = ctypes.windll.winmm.mciSendStringW
    alias = "jarvisvoice"
    mci(f"close {alias}", None, 0, 0)
    if mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, 0) != 0:
        raise RuntimeError("Windows could not open the audio file")
    try:
        mci(f"play {alias} wait", None, 0, 0)
    finally:
        mci(f"close {alias}", None, 0, 0)


def neural_speak(text):
    """Natural voice from Microsoft Edge's free online voices."""
    import edge_tts
    path = os.path.join(tempfile.gettempdir(), f"jarvis_{uuid.uuid4().hex}.mp3")

    async def make():
        await asyncio.wait_for(edge_tts.Communicate(text, VOICE, rate=VOICE_RATE).save(path), 15)

    asyncio.run(make())
    try:
        play_mp3(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


VOICE_FAILS = [0]


def voice(text):
    """Say it out loud: natural voice first, robotic Windows voice as the backup."""
    if NEURAL_VOICE and VOICE_FAILS[0] < 3:
        try:
            neural_speak(text)
            VOICE_FAILS[0] = 0
            return
        except Exception as e:
            VOICE_FAILS[0] += 1
            print("Natural voice failed, using the Windows voice:", repr(e))
    sapi_speak(text)


def show(text, role="jarvis"):
    """Print on screen (console and HUD) without speaking."""
    print(("Jarvis:" if role == "jarvis" else "You:"), text)
    HUD.log(role, text)


def speak(text, silent=False):
    """Show the reply, and say it out loud unless Jarvis is in quiet mode."""
    show(text)
    if silent or (STATE["lock"] and not STATE["woken"]):
        return
    HUD.state("speaking")
    try:
        with SPEAK_LOCK:
            voice(text)
    finally:
        HUD.state("standby" if STATE["lock"] and not STATE["woken"] else "idle")


# ---------------------------------------------------------------- voice in

def to_16k(data, fs):
    samples = data.flatten().astype(np.float32)
    n = int(len(samples) * 16000 / fs)
    positions = np.linspace(0, len(samples) - 1, n)
    return np.interp(positions, np.arange(len(samples)), samples).astype(np.int16)


def make_wav(samples):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def google_transcribe(data, fs):
    """Free Google speech service (short clips only). Returns lowercase text or ''."""
    try:
        resampled = to_16k(data, fs)
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
    except urllib.error.URLError as e:
        print("Internet/Google error:", e)
    except Exception as e:
        print("Google speech error:", repr(e))
    return ""


GROQ_IDS = []  # every model Groq offers right now (filled once)


def groq_model_ids(key):
    if not GROQ_IDS:
        request = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": "Bearer " + key, "User-Agent": "jarvis/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            GROQ_IDS.extend(m["id"] for m in data.get("data", []))
        except Exception as e:
            print("Could not get Groq model list:", repr(e))
    return GROQ_IDS


def pick_whisper(key):
    ids = [i for i in groq_model_ids(key) if "whisper" in i.lower()]
    ids.sort(key=lambda i: 0 if "turbo" in i.lower() else 1)
    return ids[0] if ids else None


def whisper_transcribe(data, fs):
    """Accurate speech-to-text on Groq (handles long speech). Returns lowercase text or ''."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return ""
    model = pick_whisper(key)
    if not model:
        return ""
    wav = make_wav(to_16k(data, fs))
    boundary = "----jarvis" + uuid.uuid4().hex
    body = b""
    for name, value in (("model", model), ("language", "en"),
                        ("response_format", "json"), ("temperature", "0")):
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                 f"\r\n\r\n{value}\r\n").encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
             'filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode()
    body += wav + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        data=body,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "jarvis/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8")).get("text", "").strip().lower()
    except urllib.error.HTTPError as e:
        print(f"Whisper error {e.code}")
    except Exception as e:
        print("Whisper error:", repr(e))
    return ""


NOISE_PHRASES = {"you", "thanks for watching", "thank you for watching", "please subscribe"}


def transcribe(audio):
    """Whisper first (accurate). Falls back to the free Google service."""
    if audio is None:
        return ""
    data, fs = audio
    text = whisper_transcribe(data, fs) or google_transcribe(data[: fs * 15], fs)
    if text.strip(" .!?,") in NOISE_PHRASES:
        return ""
    return text


AMBIENT = 300.0  # how loud the room is when nobody speaks (updates itself)
ROOM = {"base": None, "recent": collections.deque(maxlen=40)}  # quiet-room level, last 4 s of background
NOISY_TRIGGER = 1.8      # over music/video, speech must be this many times louder than the background
NOISY_CLIP_BLOCKS = 40   # over music/video, take a 4 second clip (a pause in the sound never comes)
LAST = {"hit_max": False}  # did the last recording run to the maximum (music or a video)?


def mic_rate():
    return int(sd.query_devices(kind="input")["default_samplerate"])


def calibrate():
    """Listen to the room for 1 second so Jarvis knows what 'quiet' sounds like."""
    global AMBIENT
    fs = mic_rate()
    print("Calibrating... stay quiet for 1 second")
    HUD.state("idle", "CALIBRATING")
    data = sd.rec(int(fs * 1.0), samplerate=fs, channels=1, dtype="int16")
    sd.wait()
    AMBIENT = max(100.0, float(abs(data).max()))
    ROOM["base"] = AMBIENT
    ROOM["recent"].clear()
    print("Room noise level:", int(AMBIENT))


def record_until_silence(wait_seconds=None, max_seconds=None, pause_seconds=None, abort=None):
    """Wait for speech, record it, stop after a pause.
    Also works over steady background sound (music, a video): your voice has to stand out from it.
    Returns (audio, rate), or None if nothing was said within wait_seconds."""
    global AMBIENT
    max_seconds = max_seconds or MAX_SECONDS
    pause_blocks = int((pause_seconds or PAUSE_SECONDS) * 10)
    fs = mic_rate()
    block = int(fs * 0.1)  # 0.1 second per block
    base = ROOM["base"] or AMBIENT
    recent = ROOM["recent"]  # loudness of the last 4 seconds of background (never speech)
    before = collections.deque(maxlen=3)  # the moment just before speech starts
    pending = []  # loud blocks that may be the start of speech
    chunks = []
    levels = []
    started = False
    noisy = False  # True = something loud is playing (music, video): take a short clip
    silent = 0
    waited = 0.0
    LAST["hit_max"] = False
    with sd.InputStream(samplerate=fs, channels=1, dtype="int16", blocksize=block) as stream:
        while True:
            data, _ = stream.read(block)
            if abort is not None and not started and abort():
                return None  # the mode changed while we were waiting for speech
            level = int(abs(data).max())
            HUD.level(level)
            if not started:
                floor = max(AMBIENT, float(np.median(recent)) if recent else 0.0)
                loud_room = floor > base * 2.5
                trigger = max(500.0, floor * (NOISY_TRIGGER if loud_room else 3.0))
                if level > trigger:
                    pending.append((data, level))
                    if len(pending) >= (2 if loud_room else 1):
                        started = True
                        noisy = loud_room
                        chunks.extend(before)
                        chunks.extend(d for d, _ in pending)
                        levels.extend(l for _, l in pending)
                    continue
                for d, l in pending:  # a short blip, not speech: count it as background
                    recent.append(l)
                    before.append(d)
                pending.clear()
                recent.append(level)
                before.append(data)
                AMBIENT = 0.9 * AMBIENT + 0.1 * level  # keep learning the room
                waited += 0.1
                if wait_seconds is not None and waited >= wait_seconds:
                    return None
            else:
                chunks.append(data)
                levels.append(level)
                if noisy:
                    if len(chunks) >= min(NOISY_CLIP_BLOCKS, max_seconds * 10):
                        break  # over loud music a pause never comes, so take a short clip
                    continue
                silent = 0 if level > max(300, AMBIENT * 1.8) else silent + 1
                LAST["hit_max"] = len(chunks) >= max_seconds * 10
                if silent >= pause_blocks or LAST["hit_max"]:
                    break
    if LAST["hit_max"]:  # a long steady sound, not speech: learn it as background
        recent.extend(levels[-40:])
    return np.concatenate(chunks), fs


def has_wake_word(text):
    return any(w in text for w in WAKE_WORDS)


def strip_wake(text):
    """'jarvis open notepad' -> 'open notepad'"""
    for w in WAKE_WORDS:
        if w in text:
            return text.split(w, 1)[1].strip(" ,.!?")
    return text.strip(" ,.!?")


QUIET_WAKE = re.compile(r"\b(?:(?:hey|hay|hi|ok|okay)\s*,?\s*)?(?:jarvis|jarves|jervis|jarvi)\b")


def wait_for_quiet_wake():
    """Quiet mode: stay silent until someone says 'Hey Jarvis'. Returns what came after it."""
    gen = STATE.get("gen", 0)
    while True:
        audio = record_until_silence(max_seconds=8, abort=lambda: STATE.get("gen", 0) != gen)
        if STATE.get("gen", 0) != gen:
            return None  # you clicked QUIET / WAKE UP: let the main loop listen the new way
        if audio is None or LAST["hit_max"]:
            continue  # long continuous sound = music or a video: ignore it (saves your free limits)
        data, fs = audio
        quick = google_transcribe(data, fs)
        if not quick:
            continue
        print("(heard:", quick + ")")
        if not QUIET_WAKE.search(quick):
            bare = quick.strip(" .!?,")
            if bare in QUIET_OFF_PHRASES:
                return bare  # just "wake up" (no name needed)
            continue
        full = whisper_transcribe(data, fs)
        text = full if QUIET_WAKE.search(full) else quick
        match = QUIET_WAKE.search(text)
        return text[match.end():].strip(" ,.!?")


def wait_for_wake_word():
    """Listen forever. When someone says 'Jarvis', return what came after it (may be empty)."""
    gen = STATE.get("gen", 0)
    if WAKE_ENGINE["on"]:  # offline detector: nothing leaves the laptop until it hears "Hey Jarvis"
        hit = local_wait(gen)
        if hit is None:
            return None  # you clicked QUIET / WAKE UP: let the main loop listen the new way
        if hit:
            audio = record_until_silence(wait_seconds=2.5, abort=lambda: STATE.get("gen", 0) != gen)
            if audio is None:
                return ""  # only the name was said: the main loop asks "Yes?"
            return strip_wake(transcribe(audio))
    while True:
        audio = record_until_silence(abort=lambda: STATE.get("gen", 0) != gen)
        if audio is None:
            return None  # you clicked QUIET / WAKE UP: let the main loop listen the new way
        data, fs = audio
        quick = google_transcribe(data[: fs * 8], fs)  # free check on the first 8 seconds
        if not quick:
            continue
        print("(heard:", quick + ")")
        if not has_wake_word(quick):
            continue
        full = whisper_transcribe(data, fs)  # accurate version of the whole sentence
        return strip_wake(full if has_wake_word(full) else quick)


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


# ---------------------------------------------------------------- browser (your own Chrome profile)

def chrome_path():
    path = shutil.which("chrome")
    if path:
        return path
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            candidate = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.exists(candidate):
                return candidate
    return None


def chrome_state():
    """Chrome's own settings file (it knows your profiles). Returns a dict or {}."""
    try:
        path = os.path.join(os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data", "Local State")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def chrome_profile():
    """Which Chrome profile to open links in."""
    if CHROME_PROFILE != "auto":
        return CHROME_PROFILE
    return chrome_state().get("profile", {}).get("last_used", "Default")


def open_url(url):
    """Open a link in your own Chrome profile, so your ad-free YouTube setup is used."""
    mark_quiet()
    if BROWSER == "chrome":
        chrome = chrome_path()
        if chrome:
            try:
                subprocess.Popen([chrome, f"--profile-directory={chrome_profile()}", url])
                return
            except Exception as e:
                print("Could not start Chrome:", repr(e))
    webbrowser.open(url)


def describe_browser():
    if BROWSER == "chrome" and chrome_path():
        print("Browser: Chrome, profile folder:", chrome_profile())
        for folder, info in chrome_state().get("profile", {}).get("info_cache", {}).items():
            print(f"   {folder} = {info.get('name', '?')} {info.get('user_name', '')}")
    else:
        print("Browser: Windows default (Chrome not found or BROWSER = default)")


# ---------------------------------------------------------------- tools Jarvis can use

def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "jarvis/1.0 (personal assistant)"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def tool_open_app(name):
    key = name.lower().strip()
    target = APPS.get(key)
    if not target:
        return f"I do not know the app {name}. I can open: " + ", ".join(APPS)
    try:
        os.startfile(target)
        mark_quiet()
        return f"Opened {key}."
    except Exception as e:
        return f"Could not open {key}: {e}"


def tool_web_search(query):
    open_url("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"Opened a Google search for {query}."


def tool_open_website(url):
    key = norm(url)
    if key in SITES:
        url = SITES[key]
    elif "." not in url:
        return tool_web_search(url)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    open_url(url)
    return f"Opened {url}."


def youtube_first_video(query):
    """Find the top YouTube result for a search and return its video id."""
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query})
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        html = response.read().decode("utf-8", "ignore")
    match = re.search(r'"videoId":"([\w-]{11})"', html)
    return match.group(1) if match else None


def tool_play_music(song):
    try:
        video = youtube_first_video(song + " official")
    except Exception as e:
        print("YouTube lookup failed:", repr(e))
        video = None
    if video:
        open_url(f"https://www.youtube.com/watch?v={video}&autoplay=1")
        return f"Playing {song} on YouTube."
    open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote(song))
    return f"I could not pick a video automatically, so I opened YouTube results for {song}."


MEDIA_KEYS = {"play_pause": 179, "next": 176, "previous": 177}


MEDIA_VKEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}


def press_media_key(vk):
    """Press a real media key (same as the play/pause key on a keyboard)."""
    import ctypes
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 1, 0)      # key down (extended key)
    time.sleep(0.03)
    user32.keybd_event(vk, 0, 1 | 2, 0)  # key up


def tool_media_control(action):
    vk = MEDIA_VKEYS.get(action)
    if vk is None:
        return "Media action must be play_pause, next or previous."
    try:
        press_media_key(vk)
    except Exception as e:  # backup: the old PowerShell way
        print("Media key failed, trying PowerShell:", repr(e))
        run_hidden([
            "powershell", "-NoProfile", "-Command",
            f"$w = New-Object -ComObject WScript.Shell; $w.SendKeys([char]{MEDIA_KEYS[action]})",
        ])
    return "Done."


def tool_look_up(question):
    """Get fresh facts: Google-grounded Gemini first, Wikipedia as a backup."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        headers = {"Content-Type": "application/json", "x-goog-api-key": key}
        for model in GEMINI_MODELS[:2]:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent")
            result = post_json(url, {
                "contents": [{"role": "user", "parts": [
                    {"text": question + " Answer in three short sentences or fewer."}]}],
                "tools": [{"google_search": {}}],
            }, headers)
            try:
                parts = result["candidates"][0]["content"]["parts"]
                text = clean("".join(p.get("text", "") for p in parts))
                if text:
                    return text
            except (TypeError, KeyError, IndexError):
                pass
    try:
        search = get_json("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "query", "list": "search", "srsearch": question,
             "format": "json", "srlimit": 1}))
        hits = search["query"]["search"]
        if hits:
            title = hits[0]["title"].replace(" ", "_")
            summary = get_json("https://en.wikipedia.org/api/rest_v1/page/summary/"
                               + urllib.parse.quote(title))
            return summary.get("extract", "")[:600]
    except Exception as e:
        print("Wikipedia lookup failed:", repr(e))
    return "I could not find reliable information on that."


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
    run_hidden([
        "powershell", "-NoProfile", "-Command",
        f"$w = New-Object -ComObject WScript.Shell; "
        f"1..{presses} | ForEach-Object {{ $w.SendKeys([char]{code}) }}",
    ])
    return f"Volume {action} done."


REMINDER_FILE = os.path.join(app_dir(), "jarvis_reminders.json")
REMINDER_LOCK = threading.Lock()
REMINDER_POLL = 1  # seconds between checks (reminders fire within a second of their time)
SPEAK_LOCK = threading.Lock()  # one voice at a time


def load_reminders():
    try:
        with open(REMINDER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [r for r in data if isinstance(r, dict) and "due" in r and "text" in r]
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return []


def save_reminders(items):
    with open(REMINDER_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def announce(text):
    """Say it out loud even in quiet mode (a reminder has to be heard)."""
    show(text)
    HUD.state("speaking")
    try:
        with SPEAK_LOCK:
            voice(text)
    finally:
        HUD.state("standby" if STATE["lock"] and not STATE["woken"] else "idle")


def ist_now():
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


def tool_clear_reminders():
    with REMINDER_LOCK:
        count = len(load_reminders())
        save_reminders([])
    return f"Cleared {count} reminder" + ("s." if count != 1 else ".")


def reminder_loop():
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


def start_reminders():
    threading.Thread(target=reminder_loop, daemon=True).start()


WEATHER_WORDS = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "light rain showers", 81: "rain showers", 82: "heavy rain showers",
    85: "snow showers", 86: "heavy snow showers", 95: "a thunderstorm",
    96: "a thunderstorm with hail", 99: "a thunderstorm with hail",
}


def weather_words(code):
    return WEATHER_WORDS.get(int(code), "unclear conditions")


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
            f"{weather_words(c['weather_code'])}."
        )
    except Exception as e:
        return f"Weather lookup failed: {e}"


MEMORY_LOCK = threading.Lock()
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


SHOT_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "Jarvis")

CLOSE_APPS = {
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "command prompt": "cmd.exe",
    "task manager": "Taskmgr.exe",
    "paint": "mspaint.exe",
    "chrome": "chrome.exe",
    "spotify": "Spotify.exe",
}

FOLDERS = ("downloads", "documents", "desktop", "pictures", "music", "videos")


def tool_take_screenshot():
    try:
        from PIL import ImageGrab
    except Exception:
        return "I need Pillow for that. Run: python -m pip install pillow"
    os.makedirs(SHOT_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    ImageGrab.grab().save(os.path.join(SHOT_DIR, "shot_" + stamp + ".png"))
    return "Screenshot saved in your Pictures, Jarvis folder."


def tool_close_app(name):
    key = name.lower().strip()
    exe = CLOSE_APPS.get(key)
    if not exe:
        return "I can close: " + ", ".join(CLOSE_APPS)
    result = run_hidden(["taskkill", "/IM", exe], capture_output=True, text=True)
    if result.returncode == 0:
        return "Closed " + key + "."
    return key + " does not seem to be open."


def tool_lock_pc():
    run_hidden(["rundll32.exe", "user32.dll,LockWorkStation"])
    return "Locking the PC."


def tool_open_folder(name):
    key = name.lower().strip()
    if key not in FOLDERS:
        return "I can open: " + ", ".join(FOLDERS)
    os.startfile(os.path.join(os.path.expanduser("~"), key.capitalize()))
    mark_quiet()
    return "Opened " + key + "."


def screen_request(text):
    """'what's on my screen' / 'explain this error' -> the question to ask about the screen, else None."""
    t = text.lower()
    if len(t.split()) > 14:
        return None
    patterns = (
        r"\bwhat(?:'s| is| am i)?\b.*\b(?:on|at|in)\b.*\bscreen\b",
        r"\b(?:look at|read|describe|analy[sz]e|summari[sz]e|scan|check)\b.*\b(?:my|the|this)\s+screen\b",
        r"\bcan you see\b.*\bscreen\b",
        r"\bwhat am i (?:looking at|seeing)\b",
        r"\b(?:explain|fix|solve|translate|summari[sz]e|read)\s+(?:this|that|the)\s+(?:error|code|problem|question|page|text|message|bug|screen)\b",
        r"\bwhat(?:'s| is) this error\b",
        r"\bwhat does this (?:error|say|mean)\b",
    )
    if any(re.search(p, t) for p in patterns):
        return text
    return None


def tool_look_at_screen(question=""):
    """Take a screenshot (not saved to disk) and let Gemini answer a question about it."""
    import base64
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return "I need the Gemini key to look at your screen."
    try:
        from PIL import ImageGrab
    except Exception:
        return "I need Pillow for that. Run: python -m pip install pillow"

    hidden = False
    if VISION_HIDE_HUD and HUD.window is not None and HUD.ready:
        try:
            HUD.window.minimize()  # so the Jarvis window does not cover what you want to show
            hidden = True
            time.sleep(0.7)
        except Exception:
            pass
    try:
        image = ImageGrab.grab().convert("RGB")
    finally:
        if hidden:
            try:
                HUD.window.restore()
            except Exception:
                pass

    image.thumbnail((1600, 1600))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    picture = base64.b64encode(buffer.getvalue()).decode("ascii")

    ask = (question or "").strip() or "What is on my screen?"
    prompt = (
        "You are Jarvis, a helpful voice assistant. The user is showing you a screenshot of their "
        f"screen and said: {ask}. Answer that directly. If it is an error, say what it means and the "
        "most likely fix. If it is a question or a problem, solve it. Answer in at most four short "
        "sentences of plain spoken English. Do not use markdown, bullet points, emojis or special symbols."
    )
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    for model in GEMINI_MODELS[:2]:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent")
        result = post_json(url, {
            "contents": [{"role": "user", "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": picture}},
            ]}],
        }, headers)
        try:
            parts = result["candidates"][0]["content"]["parts"]
            text = clean("".join(p.get("text", "") for p in parts))
            if text:
                return text
        except (TypeError, KeyError, IndexError):
            pass
    return "I could not read the screen right now. Try again in a minute."


# ---------------------------------------------------------------- suite: startup, briefing, notes, to-do,
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


# ---------------------------------------------------------------- Gmail + Google Calendar (read-only)

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


# ---------------------------------------------------------------- offline wake word ("Hey Jarvis" detected on this laptop)

WAKE_ENGINE = {"on": False, "model": None, "error": ""}


def resample_16k(data, fs):
    x = data.flatten()
    if fs == 16000:
        return x.astype(np.int16)
    if fs % 16000 == 0:  # 48000 -> 16000: average every 3 samples (keeps it clean)
        k = fs // 16000
        n = len(x) // k * k
        return x[:n].astype(np.float32).reshape(-1, k).mean(axis=1).astype(np.int16)
    return to_16k(data, fs)


def init_local_wake():
    """Load the offline 'Hey Jarvis' detector. True if it is ready."""
    if WAKE_ENGINE["model"] is not None:
        WAKE_ENGINE["on"] = True
        return True
    try:
        from openwakeword.model import Model
        try:
            model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        except Exception:  # the model files are not downloaded yet
            from openwakeword.utils import download_models
            download_models(model_names=["hey_jarvis"])
            model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    except Exception as e:
        WAKE_ENGINE["on"] = False
        WAKE_ENGINE["error"] = repr(e)[:200]
        print("[wake] offline wake word unavailable:", WAKE_ENGINE["error"])
        return False
    WAKE_ENGINE["model"] = model
    WAKE_ENGINE["on"] = True
    print("[wake] offline wake word ready: say 'Hey Jarvis'")
    return True


def local_wait(gen):
    """Listen with the offline detector. True = heard 'Hey Jarvis'. None = the mode changed. False = the detector failed."""
    model = WAKE_ENGINE["model"]
    try:
        reset = getattr(model, "reset", None)
        if callable(reset):
            reset()
        fs = mic_rate()
        block = int(fs * 0.08)  # 80 ms, the size the detector likes
        buf = np.zeros(0, dtype=np.int16)
        with sd.InputStream(samplerate=fs, channels=1, dtype="int16", blocksize=block) as stream:
            while True:
                if STATE.get("gen", 0) != gen:
                    return None
                data, _ = stream.read(block)
                buf = np.concatenate([buf, resample_16k(data, fs)])
                while len(buf) >= 1280:
                    chunk, buf = buf[:1280], buf[1280:]
                    scores = model.predict(chunk)
                    if scores and max(float(v) for v in scores.values()) >= LOCAL_WAKE_THRESHOLD:
                        print("[wake] heard Hey Jarvis (offline)")
                        return True
    except Exception as e:
        print("[wake] offline detector stopped, using the normal way:", repr(e)[:200])
        WAKE_ENGINE["on"] = False
        return False


def local_wake_command(text):
    if re.search(r"\b(?:use|switch to|turn on|enable|start)\b.*\b(?:offline|local|private|on[- ]device)\b.*\bwake ?(?:word|up word)\b", text):
        if init_local_wake():
            return "Offline wake word is on. Say Hey Jarvis, then your command."
        return "I could not start the offline wake word. Run pip install openwakeword, then try again."
    if re.search(r"\b(?:use|switch to|turn on|enable|go back to)\b.*\b(?:cloud|online|normal|old|regular)\b.*\bwake ?(?:word|up word)\b"
                 r"|\b(?:disable|turn off|stop)\b.*\b(?:offline|local|private|on[- ]device)\b.*\bwake ?(?:word|up word)\b", text):
        WAKE_ENGINE["on"] = False
        return "Okay, back to the normal wake word. You can say Jarvis again."
    return None


STR = {"type": "STRING"}
NUM = {"type": "NUMBER"}


def params(props, required):
    return {"type": "OBJECT", "properties": props, "required": required}


TOOLS = [{"functionDeclarations": [
    {"name": "open_app",
     "description": "Open a desktop app. Available: " + ", ".join(APPS),
     "parameters": params({"name": STR}, ["name"])},
    {"name": "web_search",
     "description": "Open a Google search in the browser (only when the user wants to see results).",
     "parameters": params({"query": STR}, ["query"])},
    {"name": "open_website",
     "description": "Open a website by name or address, for example youtube or github.com.",
     "parameters": params({"url": STR}, ["url"])},
    {"name": "play_music",
     "description": "Find a song or video on YouTube and start playing it right away.",
     "parameters": params({"song": STR}, ["song"])},
    {"name": "media_control",
     "description": "Pause, resume, skip or go back in whatever music or video is playing.",
     "parameters": params({"action": {"type": "STRING", "enum": ["play_pause", "next", "previous"]}},
                          ["action"])},
    {"name": "look_up",
     "description": "Look up facts. Use for recent events, new products, technology, people, "
                    "or anything you are not sure about. Never guess.",
     "parameters": params({"question": STR}, ["question"])},
    {"name": "get_system_status",
     "description": "Get CPU, RAM and battery status of this PC."},
    {"name": "set_volume",
     "description": "Change the PC volume.",
     "parameters": params({"action": {"type": "STRING", "enum": ["up", "down", "mute"]}}, ["action"])},
    {"name": "set_reminder",
     "description": "Remind the user after a plain number of minutes. For a clock time use set_reminder_at.",
     "parameters": params({"minutes": NUM, "message": STR}, ["minutes", "message"])},
    {"name": "get_weather",
     "description": "Get the current weather for a city.",
     "parameters": params({"city": STR}, ["city"])},
    {"name": "remember",
     "description": "Save a lasting fact about the user (name, preferences, plans) to long-term memory.",
     "parameters": params({"fact": STR}, ["fact"])},
    {"name": "look_at_screen",
     "description": "Look at the user's screen right now and answer about it: what is on screen, "
                    "explain an error, solve the question shown, summarize the page, read the text.",
     "parameters": {"type": "OBJECT", "properties": {"question": STR}}},
    {"name": "list_reminders",
     "description": "Tell the user which reminders are pending."},
    {"name": "clear_reminders",
     "description": "Delete all pending reminders."},
    {"name": "get_time",
     "description": "Get the exact current time and date in India (IST). ALWAYS call this for any question "
                    "about the time, date or day. Never answer those from memory."},
    {"name": "set_reminder_at",
     "description": "Set a reminder for a clock time or a length of time. For 'when' pass the user's own words "
                    "exactly, for example 'at 6 pm', 'tomorrow at 9 am', 'in 45 minutes'. Never work out minutes yourself.",
     "parameters": params({"when": STR, "message": STR}, ["when", "message"])},
    {"name": "set_quiet_mode",
     "description": "Turn quiet mode on (stop talking until the user says Hey Jarvis or wake up) or off.",
     "parameters": params({"state": {"type": "STRING", "enum": ["on", "off"]}}, ["state"])},
    {"name": "forget",
     "description": "Delete saved memory items that contain a keyword.",
     "parameters": params({"keyword": STR}, ["keyword"])},
    {"name": "take_screenshot",
     "description": "Take a screenshot of the whole screen and save it in the Pictures folder."},
    {"name": "close_app",
     "description": "Close an app politely. Available: notepad, calculator, command prompt, "
                    "task manager, paint, chrome, spotify.",
     "parameters": params({"name": STR}, ["name"])},
    {"name": "lock_pc",
     "description": "Lock the Windows PC screen."},
    {"name": "open_folder",
     "description": "Open a folder in File Explorer: downloads, documents, desktop, pictures, music or videos.",
     "parameters": params({"name": STR}, ["name"])},
    {"name": "add_note", "description": "Save a quick note for the user.",
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
    {"name": "check_email", "description": "Tell the user how many unread emails they have and who sent the newest ones (Gmail, read-only)."},
    {"name": "read_latest_email", "description": "Read out the preview of the newest email in the inbox."},
    {"name": "check_calendar", "description": "Read the user's Google Calendar. day is today, tomorrow or next (the next upcoming event).",
     "parameters": params({"day": STR}, [])},
    {"name": "connect_google", "description": "Start the one-time Google sign in for email and calendar."},
]}]

FUNCTIONS = {
    "open_app": tool_open_app,
    "web_search": tool_web_search,
    "open_website": tool_open_website,
    "play_music": tool_play_music,
    "media_control": tool_media_control,
    "look_up": tool_look_up,
    "get_system_status": tool_get_system_status,
    "set_volume": tool_set_volume,
    "set_reminder": tool_set_reminder,
    "get_weather": tool_get_weather,
    "remember": tool_remember,
    "forget": tool_forget,
    "get_time": lambda: tool_get_time(),
    "set_reminder_at": tool_set_reminder_at,
    "set_quiet_mode": lambda state: tool_set_quiet_mode(state),
    "look_at_screen": tool_look_at_screen,
    "list_reminders": tool_list_reminders,
    "clear_reminders": tool_clear_reminders,
    "take_screenshot": tool_take_screenshot,
    "close_app": tool_close_app,
    "lock_pc": tool_lock_pc,
    "open_folder": tool_open_folder,
    "check_email": tool_check_email,
    "read_latest_email": tool_read_email,
    "check_calendar": tool_check_calendar,
    "connect_google": tool_connect_google,
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
    """Pick the best chat models Groq offers right now."""
    skip = ("whisper", "guard", "tts", "orpheus", "playai", "embed", "safeguard")
    ids = [i for i in groq_model_ids(key) if not any(s in i.lower() for s in skip)]
    prefer = ("llama-3.3", "gpt-oss", "llama-4", "llama-3.1", "qwen", "kimi")
    ids.sort(key=lambda i: next((n for n, p in enumerate(prefer) if p in i.lower()), len(prefer)))
    return ids


def build_system_prompt():
    now = ist_now().strftime("%A, %d %B %Y, %I:%M %p")  # always India time (IST)
    facts = load_memory()
    memory = ("Known about the user: " + "; ".join(facts[-40:]) + ". ") if facts else ""
    return (
        SYSTEM_PROMPT
        + f" Current date and time in India (IST): {now}. This is the only correct time: never reuse a "
        + "time or date from earlier in the conversation, and call get_time for any question about the time or date. "
        + memory
        + "Use your tools whenever the user asks you to do something on the computer. "
        + "If the user asks to play a song or video, call play_music. "
        + "If you are not sure about a fact, or it is about recent events, new products, "
        + "technology or people, call look_up instead of guessing. Never invent facts. "
        + "Call remember when the user shares something worth keeping long term. "
        + "If the user asks you to look at their screen, call look_at_screen. "
        + f"If the user asks about the weather without naming a city, use {HOME_CITY}."
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


def time_sensitive(question, answer):
    """Time, date and reminder answers go stale in minutes, so they must not be kept in the chat memory."""
    if re.search(r"\b(?:time|date|day|today|tomorrow|tonight|clock|o'clock|remind|reminder|now)\b", question.lower()):
        return True
    return bool(re.search(r"\b\d{1,2}:\d{2}\b|\b\d{1,2} ?(?:am|pm)\b", answer.lower()))


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
    maybe_learn(question)
    if not time_sensitive(question, text):
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
        print("Groq chat models to use:", GROQ_MODELS[:3])
        print("Groq speech model:", pick_whisper(groq_key))
    gemini = check_one(
        "Gemini",
        "https://generativelanguage.googleapis.com/v1beta/models",
        {"x-goog-api-key": str(gemini_key), "User-Agent": "jarvis/1.0"},
        gemini_key,
    )
    return groq + ". " + gemini + "."


# ---------------------------------------------------------------- commands

MEDIA_VERBS = {
    "pause": "play_pause", "unpause": "play_pause", "resume": "play_pause",
    "continue": "play_pause", "play": "play_pause", "stop": "play_pause",
    "next": "next", "skip": "next",
    "previous": "previous", "back": "previous", "rewind": "previous",
}
MEDIA_FILLER = {"the", "this", "that", "my", "current", "song", "songs", "music", "video",
                "videos", "track", "youtube", "it", "please", "now", "playing", "audio",
                "go", "one", "again"}
PLAY_NAME_WORDS = {"music", "song", "songs", "track", "audio", "youtube"}


def media_action(text):
    """'pause the youtube song' -> 'play_pause', 'skip this song' -> 'next'. None if not a media command."""
    words = re.findall(r"[a-z']+", text.lower())
    if not words or len(words) > 6:
        return None
    verbs = [w for w in words if w in MEDIA_VERBS]
    others = [w for w in words if w not in MEDIA_VERBS and w not in MEDIA_FILLER]
    if not verbs or others:
        return None
    actions = {MEDIA_VERBS[v] for v in verbs}
    if "next" in actions:
        return "next"
    if "previous" in actions:
        return "previous"
    if set(verbs) == {"play"} and PLAY_NAME_WORDS & set(words):
        return None  # "play music" / "play the song" is a search, not a resume
    return "play_pause"


def volume_action(text):
    t = text.lower()
    if re.search(r"\b(?:un)?mute\b", t):
        return "mute"
    if re.search(r"\b(volume up|louder|turn it up|turn up the volume|increase the volume|raise the volume)\b", t):
        return "up"
    if re.search(r"\b(volume down|quieter|softer|turn it down|turn down the volume|decrease the volume|lower the volume)\b", t):
        return "down"
    return None


def time_answer(text):
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


def fast_command(text):
    """Instant commands that skip the AI (faster and more reliable). Returns a reply or None."""
    text = re.sub(r"^(please |can you |could you )", "", text).strip()

    answer = time_answer(text)
    if answer:
        return answer

    extra = suite_command(text)
    if extra:
        return extra

    google_reply = google_command(text)
    if google_reply:
        return google_reply

    wake_reply = local_wake_command(text)
    if wake_reply:
        return wake_reply

    action = media_action(text)
    if action:
        return tool_media_control(action)

    if len(text.split()) <= 5:
        volume = volume_action(text)
        if volume:
            return tool_set_volume(volume)
        if re.search(r"\bbattery\b", text):
            return tool_get_system_status()

    question = screen_request(text)
    if question:
        return tool_look_at_screen(question)

    request = reminder_request(text)
    if request:
        return tool_set_reminder_at(request[0], request[1])
    if text in ("what are my reminders", "list my reminders", "my reminders", "show my reminders",
                "do i have any reminders", "any reminders"):
        return tool_list_reminders()
    if text in ("clear my reminders", "clear reminders", "delete my reminders", "delete all reminders",
                "cancel my reminders", "cancel all reminders"):
        return tool_clear_reminders()
    if re.fullmatch(r"(?:what(?:'s| is) )?(?:the )?weather(?: like)?(?: today| now| right now)?", text):
        return tool_get_weather(HOME_CITY)
    match = re.match(r"(?:what(?:'s| is) )?(?:the )?weather (?:in|for|at) (.+?)(?: today| now)?$", text)
    if match:
        return tool_get_weather(match.group(1))

    match = re.match(r"open (?:the )?(.+?)(?: website| app| application)?$", text)
    if match:
        spoken = match.group(1)
        key = norm(spoken)
        if key in SITES:
            open_url(SITES[key])
            return f"Opening {spoken}."
        for name in APPS:
            if norm(name) == key:
                return tool_open_app(name)

    if text in ("take a screenshot", "take screenshot", "screenshot", "capture the screen"):
        return tool_take_screenshot()
    if text in ("lock the pc", "lock pc", "lock my pc", "lock the computer", "lock the screen", "lock screen"):
        return tool_lock_pc()
    match = re.match(r"close (?:the )?(.+)$", text)
    if match and match.group(1) in CLOSE_APPS:
        return tool_close_app(match.group(1))
    match = re.match(r"open (?:the )?(downloads|documents|desktop|pictures|music|videos)(?: folder)?$", text)
    if match:
        return tool_open_folder(match.group(1))

    match = re.match(r"play (.+?)(?: on youtube)?$", text)
    if match:
        return tool_play_music(match.group(1))
    return None


QUIT_PHRASES = {"goodbye", "bye", "exit", "quit", "shut down", "shutdown",
                "goodbye jarvis", "bye jarvis", "exit jarvis", "shut down jarvis"}
SLEEP_PHRASES = {"stop", "thanks", "thank you", "cancel", "never mind", "nevermind",
                 "sleep", "that's all", "that is all", "thanks jarvis", "thank you jarvis"}
QUIET_ON_PHRASES = {"go quiet", "be quiet", "quiet mode", "silent mode", "stay quiet", "go silent",
                    "quiet please", "shh", "shush"}
QUIET_OFF_PHRASES = {"wake up", "normal mode", "come back", "stop being quiet", "talk to me",
                     "speak to me", "i'm back", "im back", "quiet mode off", "disable quiet mode"}
QUIET_OFF_PHRASES |= {"wake", "wakeup", "wake up now", "wake up please", "get up",
                      "come online", "back online", "i am back"}


def quiet_request(text):
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


def handle(command):
    """Run one command. Returns 'quit', 'sleep' (stop follow-up listening) or 'ok'."""
    text = command.strip(" .!?,")
    # "wake up jarvis" / "jarvis pause": the name at the start or end is not part of the command
    text = re.sub(r"^(?:(?:hey|hi|ok|okay)[ ,]+)?(?:jarvis|jarves|jervis)\b[ ,]*"
                  r"|[ ,]*\b(?:jarvis|jarves|jervis)$", "", text).strip(" .!?,") or text
    words = text.split()
    print(f"[command] {text}")
    STATE["enter_quiet"] = False

    if text in QUIT_PHRASES:
        speak("Goodbye, see you soon!")
        return "quit"
    if text in QUIET_ON_PHRASES or quiet_request(text) == "on":
        speak("Going quiet. Say Hey Jarvis or wake up when you need me.")
        set_lock(True)
        return "sleep"
    if text in QUIET_OFF_PHRASES or quiet_request(text) == "off":
        set_lock(False)
        speak("I am back. Say Jarvis when you need me.")
        return "ok"
    if text in SLEEP_PHRASES:
        hint = "Hey Jarvis" if STATE["lock"] else "Jarvis"
        speak(f"Okay. Say {hint} when you need me.")
        return "sleep"
    if len(words) <= 4 and "forget" in words and "conversation" in words:
        HISTORY.clear()
        speak("Okay, I have forgotten our conversation.")
        return "ok"
    if "brain" in words:
        if "check" in words or "test" in words:
            speak(check_brains())
        elif LAST_BRAIN == "none yet":
            speak("Ask me something first, then I can tell you which brain answered.")
        else:
            speak(f"My last answer came from {LAST_BRAIN}.")
        return "ok"

    reply = fast_command(text)
    if reply:
        speak(reply, silent=STATE["enter_quiet"])
        return "ok"

    print("Thinking...")
    HUD.state("thinking")
    answer = ask_ai(command)
    speak(answer, silent=STATE["enter_quiet"])
    return "ok"


# ---------------------------------------------------------------- main loop

def jarvis_loop():
    print("--- Brain self-check ---")
    check_brains()
    describe_browser()
    print("------------------------")
    start_reminders()

    if USE_WAKE_WORD:
        calibrate()
        if ALWAYS_LISTENING:
            speak("Jarvis is online. I am listening.")
        else:
            speak("Jarvis is online. Say Jarvis, then your command.")
    else:
        speak("Jarvis is online. How can I help?")

    if STARTED_BY_WINDOWS and STARTUP_BRIEFING:  # Jarvis was started by Windows: greet with the briefing
        try:
            speak(build_briefing())
        except Exception as e:
            print("Briefing error:", repr(e))

    if LOCAL_WAKE and USE_WAKE_WORD and not ALWAYS_LISTENING:
        init_local_wake()

    awake = False  # True during the follow-up window after an answer
    while True:
        try:
            quiet = STATE["lock"] and not STATE["woken"]
            if not USE_WAKE_WORD:
                HUD.state("listening")
                input("\nPress Enter, then speak: ")
                command = transcribe(record_until_silence(wait_seconds=8))
            elif quiet:
                HUD.state("standby")
                command = wait_for_quiet_wake()
                if command is None:
                    continue  # the mode changed: start listening the new way straight away
                STATE["woken"] = True  # you called it, so it may answer out loud
                HUD.state("listening")
                if not command:  # they only said "Hey Jarvis" - ask for the command
                    speak("Yes?")
                    command = strip_wake(transcribe(record_until_silence(wait_seconds=8)))
            elif awake or ALWAYS_LISTENING:
                HUD.state("listening")
                if STATE["lock"]:
                    seconds = QUIET_FOLLOW_UP_SECONDS
                elif ALWAYS_LISTENING:
                    seconds = None
                else:
                    seconds = FOLLOW_UP_SECONDS
                audio = record_until_silence(wait_seconds=seconds)
                if audio is None:
                    awake = False
                    STATE["woken"] = False
                    print("(sleeping - say Jarvis)")
                    continue
                HUD.state("thinking")
                command = strip_wake(transcribe(audio))
            else:
                HUD.state("idle")
                command = wait_for_wake_word()
                if command is None:
                    continue  # the mode changed: start listening the new way straight away
                HUD.state("listening")
                if not command:  # they only said "Jarvis" - ask for the command
                    speak("Yes?")
                    command = strip_wake(transcribe(record_until_silence(wait_seconds=8)))
        except (KeyboardInterrupt, EOFError):
            print("\nStopped.")
            break

        if not command:
            continue
        show(command, role="you")

        started = time.time()
        result = handle(command)
        print(f"[done in {time.time() - started:.1f}s]")
        if result == "quit":
            break
        if STATE["enter_quiet"]:  # Jarvis just opened something: go silent
            STATE["enter_quiet"] = False
            set_lock(True)
            awake = False
            print("(quiet mode - say Hey Jarvis)")
        elif result == "sleep":
            awake = False
            STATE["woken"] = False
        else:
            awake = True


def main():
    run_with_hud(jarvis_loop)


if __name__ == "__main__":
    main()