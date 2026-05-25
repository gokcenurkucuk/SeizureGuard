from flask import Flask, render_template, jsonify, request
import json
import os
import queue
import re
import threading
import time

import ollama
import pyttsx3
import serial

try:
    import sounddevice as sd
    import vosk
except Exception:
    sd = None
    vosk = None

app = Flask(__name__)

SERIAL_PORT = os.getenv("SEIZUREGUARD_SERIAL_PORT", "COM3")
SERIAL_BAUD = int(os.getenv("SEIZUREGUARD_SERIAL_BAUD", "115200"))
OLLAMA_MODEL = os.getenv("SEIZUREGUARD_OLLAMA_MODEL", "llama3.2")
ENABLE_VOICE = os.getenv("SEIZUREGUARD_ENABLE_VOICE", "1").lower() not in ("0", "false", "no")
VOSK_MODEL_PATH = os.path.expanduser(os.getenv("SEIZUREGUARD_VOSK_MODEL", "~/vosk-model-small-en-us-0.15"))

HR_SEIZURE_BPM = 120
SPO2_SEIZURE_PERCENT = 90
MOTION_SEIZURE_G = 1.5
TREMOR_MIN_HZ = 4.0
TREMOR_MAX_HZ = 12.0

latest_data = {
    "heart_rate": 0,
    "spo2": 0,
    "shake_level": 0.0,
    "tremor_hz": 0.0,
    "ai_decision": "System active. Waiting for ESP32-S3 data packets...",
    "status": "waiting",
}

ai_lock = threading.Lock()
tts_lock = threading.Lock()
voice_lock = threading.Lock()
audio_q = queue.Queue()

emergency_mode_active = False
emergency_generation = 0
tts_active = False
voice_accepting = False
last_user_text = ""
last_user_time = 0.0

SYSTEM_PROMPT = (
    "Act as an emergency assistant for an epilepsy monitoring wearable. "
    "First address the patient. If there is no meaningful response, address bystanders. "
    "Reply in English with exactly one short, calm, authoritative spoken sentence. "
    "Do not add extra explanations. Do not claim a definite diagnosis."
)


def first_sentence(text):
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    match = re.search(r"^.*?[.!?](?:\s|$)", text)
    sentence = match.group(0).strip() if match else text
    return sentence[:220].strip()


def ask_local_ollama(stage_name, fallback_message, extra_context=""):
    prompt = (
        f"Stage: {stage_name}\n"
        f"Sensor status: {latest_data['status']}, HR={latest_data['heart_rate']} BPM, "
        f"SpO2={latest_data['spo2']}%, movement={latest_data['shake_level']:.2f}G, "
        f"tremor={latest_data['tremor_hz']:.1f}Hz.\n"
        f"{extra_context}\n"
        f"Use this exact meaning without changing the medical instruction: {fallback_message}"
    )

    try:
        with ai_lock:
            response = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.2},
            )
        message = first_sentence(response.get("message", {}).get("content", ""))
        return message or fallback_message
    except Exception as e:
        print(f"[OLLAMA ERROR] {e}")
        return fallback_message


def speak_text(text):
    global tts_active
    sentence = first_sentence(text)
    if not sentence:
        return

    with tts_lock:
        tts_active = True
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 135)
            engine.say(sentence)
            engine.runAndWait()
        except Exception as e:
            print(f"[TTS ERROR] {e}")
        finally:
            tts_active = False
            while not audio_q.empty():
                try:
                    audio_q.get_nowait()
                except Exception:
                    break


def say_ai(label, stage_name, fallback_message, extra_context=""):
    msg = ask_local_ollama(stage_name, fallback_message, extra_context)
    latest_data["ai_decision"] = f"[{label}]\nAI Speech: {msg}"
    print(f"[AI] {label}: {msg}")
    speak_text(msg)
    return msg


def say_fixed(label, text):
    latest_data["ai_decision"] = f"[{label}]\nAI Speech: {text}"
    print(f"[AI] {label}: {text}")
    speak_text(text)
    return text


def remember_voice_text(text, force=False):
    global last_user_text, last_user_time
    clean = first_sentence(text)
    if not clean:
        return
    if not force and not voice_accepting:
        return
    with voice_lock:
        last_user_text = clean
        last_user_time = time.time()
    print(f"[VOICE HEARD] {clean}")


def get_reply_since(start_time):
    with voice_lock:
        if last_user_time >= start_time:
            return last_user_text
    return ""


def wait_for_reply(timeout_seconds, generation):
    start = time.time()
    while time.time() - start < timeout_seconds:
        if generation != emergency_generation or latest_data["status"] != "danger":
            return ""
        reply = get_reply_since(start)
        if reply:
            return reply
        time.sleep(0.2)
    return ""


def finish_if_normal(generation):
    if generation != emergency_generation:
        return True
    if latest_data["status"] == "danger":
        return False

    say_ai(
        "RECOVERY CHECK",
        "recovery",
        "The readings are returning to normal. Are you feeling better?",
    )
    return True


def run_emergency_dialog(generation):
    global emergency_mode_active, voice_accepting

    try:
        voice_accepting = True
        say_fixed("STAGE 1 - PATIENT CHECK", "Hello, can you hear me right now?")
        reply = wait_for_reply(3, generation)
        if finish_if_normal(generation):
            return

        if not reply:
            say_fixed("STAGE 1 - PATIENT CHECK", "If you can hear me, squeeze a hand or make any sound.")
            reply = wait_for_reply(5, generation)
            if finish_if_normal(generation):
                return

        if reply:
            say_ai(
                "PATIENT RESPONSE",
                "patient responded",
                "I heard you. Stay calm, stay low, and keep your head safe.",
                "A response was detected; transcription may be inaccurate, so treat it only as a sign of response.",
            )
            say_fixed("STAGE 2 - PATIENT SAFETY", "If you can, lie on your side and move away from hard objects.")
            wait_for_reply(10, generation)
            if finish_if_normal(generation):
                return
        else:
            say_fixed("NO PATIENT RESPONSE", "Attention, this person may be having a seizure.")
            if finish_if_normal(generation):
                return
            say_fixed("BYSTANDER MODE", "Please stay calm and follow my instructions one by one.")

        bystander_steps = [
            ("BYSTANDER STEP 1", "Do not restrain the person or try to stop their movements."),
            ("BYSTANDER STEP 2", "Place something soft under their head and move hard objects away."),
            ("BYSTANDER STEP 3", "Do not put anything in their mouth; they cannot swallow their tongue."),
            ("BYSTANDER STEP 4", "Check the time and wait for the shaking to stop."),
            ("BYSTANDER STEP 5", "If it lasts longer than five minutes, call emergency services immediately."),
        ]

        step_index = 0
        while generation == emergency_generation and latest_data["status"] == "danger":
            label, text = bystander_steps[step_index]
            say_fixed(label, text)
            reply = wait_for_reply(10, generation)
            if finish_if_normal(generation):
                return
            if reply:
                say_ai(
                    "FOLLOW-UP",
                    "bystander response",
                    "I heard you. Continue the safety steps and keep watching their breathing.",
                    "A spoken response was detected; transcription may be inaccurate.",
                )
            step_index = (step_index + 1) % len(bystander_steps)
    finally:
        voice_accepting = False
        emergency_mode_active = False


def emergency_manager_loop():
    global emergency_mode_active, emergency_generation, voice_accepting

    while True:
        if latest_data["status"] == "danger" and not emergency_mode_active:
            emergency_mode_active = True
            emergency_generation += 1
            threading.Thread(
                target=run_emergency_dialog,
                args=(emergency_generation,),
                daemon=True,
            ).start()

        if latest_data["status"] != "danger" and emergency_mode_active:
            voice_accepting = False
            emergency_generation += 1

        time.sleep(0.5)


def is_danger(data):
    status = str(data.get("status", "")).upper()
    hr = latest_data["heart_rate"]
    spo2 = latest_data["spo2"]
    shake = latest_data["shake_level"]
    tremor_hz = latest_data["tremor_hz"]

    if status == "SEIZURE":
        return True

    motion_match = shake >= MOTION_SEIZURE_G and TREMOR_MIN_HZ <= tremor_hz <= TREMOR_MAX_HZ
    heart_match = hr >= HR_SEIZURE_BPM or (0 < spo2 <= SPO2_SEIZURE_PERCENT)
    return motion_match and heart_match


def read_serial_data():
    while True:
        try:
            with serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1) as ser:
                ser.reset_input_buffer()
                print(f"[IoT Pipeline] Listening on {SERIAL_PORT} at {SERIAL_BAUD} baud.")

                while True:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if line.startswith("{") and line.endswith("}"):
                        data = json.loads(line)

                        latest_data["heart_rate"] = int(float(data.get("hr", 0)))
                        latest_data["spo2"] = int(float(data.get("spo2", 0)))
                        latest_data["shake_level"] = float(data.get("vibration", data.get("shake", 0.0)))
                        latest_data["tremor_hz"] = float(data.get("tremor_hz", 0.0))
                        latest_data["status"] = "danger" if is_danger(data) else "normal"

                    time.sleep(0.05)
        except Exception as e:
            print(f"[SERIAL ERROR] {e}")
            time.sleep(2)


def ask_ai(user_text):
    prompt = (
        f"User said: {user_text}\n"
        f"Current sensor context: status={latest_data['status']}, "
        f"HR={latest_data['heart_rate']} BPM, SpO2={latest_data['spo2']}%, "
        f"movement={latest_data['shake_level']:.2f}G, tremor={latest_data['tremor_hz']:.1f}Hz.\n"
        "Answer with one short spoken sentence."
    )
    return ask_local_ollama("user question", "Please stay calm and follow the safety instructions.", prompt)


def continuous_listen():
    if not ENABLE_VOICE:
        print("[VOICE] Voice listener disabled.")
        return
    if sd is None or vosk is None:
        print("[VOICE] sounddevice or vosk is not installed; voice listener disabled.")
        return
    if not os.path.isdir(VOSK_MODEL_PATH):
        print(f"[VOICE] Vosk model not found at {VOSK_MODEL_PATH}; voice listener disabled.")
        return

    try:
        model = vosk.Model(VOSK_MODEL_PATH)
    except Exception as e:
        print(f"[VOICE] Vosk model error: {e}")
        return

    samplerate = 16000
    blocksize = 8000
    print("[VOICE] Microphone listener active.")

    def callback(indata, frames, time_info, status):
        if not tts_active:
            audio_q.put(bytes(indata))

    try:
        with sd.RawInputStream(
            samplerate=samplerate,
            blocksize=blocksize,
            dtype="int16",
            channels=1,
            callback=callback,
        ):
            rec = vosk.KaldiRecognizer(model, samplerate)
            while True:
                chunk = audio_q.get()
                if rec.AcceptWaveform(chunk):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").strip()
                    if len(text) > 1:
                        remember_voice_text(text)
    except Exception as e:
        print(f"[VOICE] Microphone error: {e}")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def get_data():
    return jsonify(latest_data)


@app.route("/api/chat", methods=["POST"])
def chat():
    payload = request.get_json(silent=True) or {}
    user_text = str(payload.get("message", "")).strip()
    should_speak = bool(payload.get("speak", False))

    if not user_text:
        return jsonify({"error": "message is required"}), 400

    remember_voice_text(user_text, force=True)
    reply = ask_ai(user_text)
    latest_data["ai_decision"] = f"Q: {user_text}\nA: {reply}"

    if should_speak:
        threading.Thread(target=speak_text, args=(reply,), daemon=True).start()

    return jsonify({"reply": reply})


if __name__ == "__main__":
    threading.Thread(target=read_serial_data, daemon=True).start()
    threading.Thread(target=emergency_manager_loop, daemon=True).start()
    threading.Thread(target=continuous_listen, daemon=True).start()
    app.run(debug=False, port=5000, use_reloader=False)
