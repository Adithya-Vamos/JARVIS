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
VISION_HIDE_HUD = True    # hide the Jarvis window for a moment so it does not cover your screen

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


def record_until_silence(wait_seconds=None, max_seconds=None, pause_seconds=None):
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
    while True:
        audio = record_until_silence(max_seconds=8)
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
    while True:
        audio = record_until_silence()
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
REMINDER_POLL = 5  # seconds between checks
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


def tool_set_reminder(minutes, message):
    minutes = float(minutes)
    with REMINDER_LOCK:
        items = load_reminders()
        items.append({"due": time.time() + minutes * 60, "text": message})
        save_reminders(items)
    return f"Reminder set for {minutes:g} minutes from now."


def tool_list_reminders():
    with REMINDER_LOCK:
        items = sorted(load_reminders(), key=lambda r: r["due"])
    if not items:
        return "You have no reminders."
    parts = []
    for r in items[:5]:
        when = datetime.datetime.fromtimestamp(r["due"]).strftime("%I:%M %p").lstrip("0")
        parts.append(f"{r['text']} at {when}")
    return f"You have {len(items)} reminder" + ("s" if len(items) != 1 else "") + ": " + "; ".join(parts) + "."


def tool_clear_reminders():
    with REMINDER_LOCK:
        count = len(load_reminders())
        save_reminders([])
    return f"Cleared {count} reminder" + ("s." if count != 1 else ".")


def reminder_loop():
    first = True
    while True:
        try:
            with REMINDER_LOCK:
                items = load_reminders()
                now = time.time()
                due_now = [r for r in items if r["due"] <= now]
                if due_now:
                    save_reminders([r for r in items if r["due"] > now])
            for r in due_now:
                missed = first and now - r["due"] > 90
                announce(("You missed a reminder while I was off: " if missed else "Reminder: ") + r["text"])
        except Exception as e:
            print("Reminder error:", repr(e))
        first = False
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
     "description": "Remind the user out loud after some minutes.",
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
    "look_at_screen": tool_look_at_screen,
    "list_reminders": tool_list_reminders,
    "clear_reminders": tool_clear_reminders,
    "take_screenshot": tool_take_screenshot,
    "close_app": tool_close_app,
    "lock_pc": tool_lock_pc,
    "open_folder": tool_open_folder,
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
    now = datetime.datetime.now().strftime("%A, %d %B %Y, %I:%M %p")
    facts = load_memory()
    memory = ("Known about the user: " + "; ".join(facts) + ". ") if facts else ""
    return (
        SYSTEM_PROMPT
        + f" Current date and time: {now}. "
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


def fast_command(text):
    """Instant commands that skip the AI (faster and more reliable). Returns a reply or None."""
    text = re.sub(r"^(please |can you |could you )", "", text).strip()

    action = media_action(text)
    if action:
        return tool_media_control(action)

    if len(text.split()) <= 5:
        volume = volume_action(text)
        if volume:
            return tool_set_volume(volume)
        if re.search(r"\b(what time is it|what is the time|what's the time|current time|time now|tell me the time)\b", text):
            return "It is " + datetime.datetime.now().strftime("%I:%M %p").lstrip("0") + "."
        if re.search(r"\b(what is the date|what's the date|today's date|what day is it|what is today|what's today)\b", text):
            return "Today is " + datetime.datetime.now().strftime("%A, %d %B %Y") + "."
        if re.search(r"\bbattery\b", text):
            return tool_get_system_status()

    question = screen_request(text)
    if question:
        return tool_look_at_screen(question)

    match = re.match(r"remind me (?:in|after) (\d+(?:\.\d+)?) ?(seconds?|secs?|minutes?|mins?|hours?|hrs?) (?:to |that |about )?(.+)$", text)
    if match:
        amount = float(match.group(1))
        unit = match.group(2)
        if unit.startswith("sec"):
            amount = amount / 60
        elif unit.startswith(("hour", "hr")):
            amount = amount * 60
        return tool_set_reminder(amount, match.group(3))
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


def handle(command):
    """Run one command. Returns 'quit', 'sleep' (stop follow-up listening) or 'ok'."""
    text = command.strip(" .!?,")
    # "wake up jarvis" / "jarvis pause": the name at the start or end is not part of the command
    text = re.sub(r"^(?:(?:hey|hi|ok|okay)[ ,]+)?(?:jarvis|jarves|jervis)\b[ ,]*"
                  r"|[ ,]*\b(?:jarvis|jarves|jervis)$", "", text).strip(" .!?,") or text
    words = text.split()
    STATE["enter_quiet"] = False

    if text in QUIT_PHRASES:
        speak("Goodbye, see you soon!")
        return "quit"
    if text in QUIET_ON_PHRASES:
        speak("Going quiet. Say Hey Jarvis when you need me.")
        set_lock(True)
        return "sleep"
    if text in QUIET_OFF_PHRASES:
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