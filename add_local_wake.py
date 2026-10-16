# Run once inside the JARVIS folder:  python add_local_wake.py
#
# ADDS: an OFFLINE "Hey Jarvis" detector (openWakeWord). It runs on your laptop, so while Jarvis waits
# for its name your voice is NOT sent to Google or Groq. Audio is only sent after it hears "Hey Jarvis".
#   "use offline wake word"   -> switch it on (first time it downloads a small model, about 5 MB)
#   "use cloud wake word"     -> go back to the old way (the old way also accepts a bare "Jarvis")
#   Or set LOCAL_WAKE = True near the top of main.py to start with it on.
#
# Honest limits: it only listens for "Hey Jarvis" (not a bare "Jarvis"), quiet mode still uses the old way
# because it must also hear "wake up", and I could not test it with a real voice, so try it and
# say "use cloud wake word" if it misses you.
#
# Needs:  pip install openwakeword
# Needs the earlier patches. Makes a backup first (main.py.bak). If anything does not fit, it changes NOTHING.

import os
import shutil
import sys

PATH = "main.py"

if not os.path.exists(PATH):
    print("main.py not found. Run this from inside the JARVIS folder.")
    sys.exit(1)

with open(PATH, "r", encoding="utf-8") as f:
    src = f.read()

if "def init_local_wake" in src:
    print("Already installed. Nothing to do.")
    sys.exit(0)

if "def ist_now" not in src or "def wait_for_wake_word" not in src:
    print("Run the earlier patches first (upgrade_jarvis.py, upgrade_vision.py, fix_time_quiet.py), then this one.")
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
     'LOCAL_WAKE = False        # True = listen for "Hey Jarvis" on this laptop (needs: pip install openwakeword)\n'
     'LOCAL_WAKE_THRESHOLD = 0.5  # lower = hears you more easily but may trigger by mistake\n')

NEW_CODE = r'''# ---------------------------------------------------------------- offline wake word ("Hey Jarvis" detected on this laptop)

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


'''

swap('STR = {"type": "STRING"}\n', NEW_CODE + 'STR = {"type": "STRING"}\n')

swap('    action = media_action(text)\n',
     '    wake_reply = local_wake_command(text)\n    if wake_reply:\n        return wake_reply\n\n    action = media_action(text)\n')

swap('''    """Listen forever. When someone says 'Jarvis', return what came after it (may be empty)."""
    gen = STATE.get("gen", 0)
    while True:
''', '''    """Listen forever. When someone says 'Jarvis', return what came after it (may be empty)."""
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
''')

swap('    awake = False  # True during the follow-up window after an answer\n',
     '    if LOCAL_WAKE and USE_WAKE_WORD and not ALWAYS_LISTENING:\n'
     '        init_local_wake()\n\n'
     '    awake = False  # True during the follow-up window after an answer\n')

try:
    compile(src, PATH, "exec")
except SyntaxError as e:
    print("The patched code did not compile:", e)
    print("Nothing was changed.")
    sys.exit(1)

shutil.copy(PATH, "main.py.bak")
with open(PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Done. Added: offline wake word (off until you say 'use offline wake word' or set LOCAL_WAKE = True).")
print("Backup saved as main.py.bak")
print("Now run:  pip install openwakeword")
