from flask import Flask, render_template, jsonify, request
import json
import os
import re
import threading
import time

import ollama
import pyttsx3
import serial

try:
    import sounddevice as sd
    import numpy as np
except Exception:
    sd = None
    np = None

app = Flask(__name__)

SERIAL_PORT = os.getenv("SEIZUREGUARD_SERIAL_PORT", "COM13")
SERIAL_BAUD = int(os.getenv("SEIZUREGUARD_SERIAL_BAUD", "115200"))
OLLAMA_MODEL = os.getenv("SEIZUREGUARD_OLLAMA_MODEL", "llama3.2")
ENABLE_VOICE = os.getenv("SEIZUREGUARD_ENABLE_VOICE", "1").lower() not in ("0", "false", "no")

HR_SEIZURE_BPM = 120
SPO2_SEIZURE_PERCENT = 80
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

whisper_model = None

emergency_mode_active = False
emergency_generation = 0
emergency_start_time = 0.0
tts_active = False
voice_accepting = False
last_user_text = ""
last_user_time = 0.0
_tts_engine_ref = None

EMERGENCY_MIN_DURATION = 5.0

SYSTEM_PROMPT = (
    "You are SeizureGuard, an AI emergency voice assistant for an epilepsy seizure detection wearable. "
    "You will be given a stage and instructions. Follow them exactly. "
    "Always reply with ONE short, calm, spoken English sentence. No lists. No diagnosis. No extra words."
)

BYSTANDER_STEPS = [
    "Do not restrain the person or try to stop their movements.",
    "Place something soft under their head and move sharp objects away.",
    "Do not put anything in their mouth — they cannot swallow their tongue.",
    "Note the time — check how long the seizure has been going on.",
    "If the seizure lasts longer than five minutes, call emergency services immediately.",
]


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
    global tts_active, _tts_engine_ref
    sentence = first_sentence(text)
    if not sentence:
        return

    with tts_lock:
        tts_active = True
        try:
            engine = pyttsx3.init()
            _tts_engine_ref = engine
            engine.setProperty("rate", 135)
            engine.say(sentence)
            engine.runAndWait()
        except Exception as e:
            print(f"[TTS ERROR] {e}")
        finally:
            _tts_engine_ref = None
            tts_active = False


def interrupt_tts():
    eng = _tts_engine_ref
    if eng is not None:
        try:
            eng.stop()
            print("[TTS] Kullanici konustu, TTS kesildi.")
        except Exception:
            pass


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
    while tts_active:
        time.sleep(0.1)
    start = time.time()
    print(f"[DIALOG] Dinleniyor {timeout_seconds}s — voice_accepting={voice_accepting}")
    while time.time() - start < timeout_seconds:
        if generation != emergency_generation:
            return ""
        reply = get_reply_since(start)
        if reply:
            print(f"[DIALOG] Cevap alindi: '{reply}'")
            return reply
        time.sleep(0.2)
    print("[DIALOG] Süre doldu, cevap yok.")
    return ""


def finish_if_normal(generation):
    if generation != emergency_generation:
        return True
    if latest_data["status"] != "danger":
        say_fixed("RECOVERY", "Readings are returning to normal. Please stay calm.")
        return True
    return False


def llm_say(stage_instruction, history, fallback):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": stage_instruction})
    try:
        with ai_lock:
            full_text = ""
            for chunk in ollama.chat(
                model=OLLAMA_MODEL,
                messages=messages,
                options={"temperature": 0.3},
                stream=True,
            ):
                token = chunk.get("message", {}).get("content", "")
                full_text += token
                if any(c in token for c in ".!?"):
                    break
        sentence = first_sentence(full_text) or fallback
        print(f"[LLM] {sentence}")
        return sentence
    except Exception as e:
        print(f"[OLLAMA ERROR] {e}")
        return fallback


def speak_log(msg, history):
    latest_data["ai_decision"] = f"[EMERGENCY AI]\nAI Speech: {msg}"
    history.append({"role": "assistant", "content": msg})
    speak_text(msg)


def run_emergency_dialog(generation):
    global emergency_mode_active, voice_accepting

    try:
        voice_accepting = True
        history = []

        # --- AŞAMA 1: Hastayı kontrol et ---
        msg = llm_say(
            "Stage: patient check. A seizure was detected. Speak directly to the patient and ask if they can hear you.",
            history, "Hello, can you hear me right now?"
        )
        speak_log(msg, history)

        reply = wait_for_reply(8, generation)
        if finish_if_normal(generation): return

        if not reply:
            msg = llm_say(
                "Stage: second patient check. No response. Try once more to reach the patient.",
                history, "If you can hear me, squeeze your hand or make any sound."
            )
            speak_log(msg, history)
            reply = wait_for_reply(8, generation)
            if finish_if_normal(generation): return

        # --- AŞAMA 2A: Hasta cevap verdi ---
        if reply:
            history.append({"role": "user", "content": reply})
            msg = llm_say(
                f"Stage: patient responded. They said: '{reply}'. Reassure them and tell them what to do to stay safe.",
                history, "I hear you. Stay calm, lie still, and keep your head protected."
            )
            speak_log(msg, history)

            while generation == emergency_generation:
                if finish_if_normal(generation): return
                reply = wait_for_reply(10, generation)
                if finish_if_normal(generation): return
                if reply:
                    history.append({"role": "user", "content": reply})
                msg = llm_say(
                    f"Stage: patient dialog. They said: '{reply or 'nothing'}'. Continue guiding the patient through the seizure safely.",
                    history, "Stay as still as possible and focus on breathing slowly."
                )
                speak_log(msg, history)

        # --- AŞAMA 2B: Hasta cevap vermedi — yakınlara dön ---
        else:
            msg = llm_say(
                "Stage: no patient response. Alert bystanders that this person may be having an epileptic seizure and ask them to listen carefully.",
                history, "Attention everyone, this person may be having a seizure. Please listen to my instructions."
            )
            speak_log(msg, history)
            if finish_if_normal(generation): return

            for i, step in enumerate(BYSTANDER_STEPS):
                if finish_if_normal(generation): return

                msg = llm_say(
                    f"Stage: bystander step {i+1} of {len(BYSTANDER_STEPS)}. Tell bystanders to do this now: {step}",
                    history, step
                )
                speak_log(msg, history)

                reply = wait_for_reply(10, generation)
                if finish_if_normal(generation): return

                if reply:
                    history.append({"role": "user", "content": reply})
                    msg = llm_say(
                        f"Stage: bystander confirmed step {i+1}. They said: '{reply}'. Acknowledge briefly and tell them the next step is coming.",
                        history, "Good, keep going."
                    )
                    speak_log(msg, history)

            if generation == emergency_generation:
                msg = llm_say(
                    "Stage: all steps given. Remind bystanders to keep watching the patient and stay calm.",
                    history, "Keep watching them carefully and stay calm until help arrives."
                )
                speak_log(msg, history)

    finally:
        voice_accepting = False
        emergency_mode_active = False


def emergency_manager_loop():
    global emergency_mode_active, emergency_generation, voice_accepting, emergency_start_time

    while True:
        if latest_data["status"] == "danger" and not emergency_mode_active:
            emergency_mode_active = True
            emergency_start_time = time.time()
            emergency_generation += 1
            threading.Thread(
                target=run_emergency_dialog,
                args=(emergency_generation,),
                daemon=True,
            ).start()

        if emergency_mode_active:
            elapsed = time.time() - emergency_start_time
            if elapsed >= EMERGENCY_MIN_DURATION:
                voice_accepting = False
                emergency_mode_active = False
                emergency_generation += 1

        time.sleep(0.5)


def is_danger(data):
    status = str(data.get("status", "")).upper()
    if status == "SEIZURE":
        return True

    shake = latest_data["shake_level"]
    tremor_hz = latest_data["tremor_hz"]
    motion_match = shake >= 2.0 and TREMOR_MIN_HZ <= tremor_hz <= TREMOR_MAX_HZ
    return motion_match


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
    global whisper_model

    if not ENABLE_VOICE:
        print("[VOICE] Voice listener disabled.")
        return
    if sd is None or np is None:
        print("[VOICE] sounddevice or numpy is not installed; voice listener disabled.")
        return

    try:
        from faster_whisper import WhisperModel
        whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
        print("[VOICE] faster-whisper small model loaded.")
    except Exception as e:
        print(f"[VOICE] Whisper model load error: {e}")
        return

    samplerate = 16000
    chunk_sec = 0.8
    chunk_samples = int(chunk_sec * samplerate)
    rms_min = 0.003
    print("[VOICE] Listener active — her 0.8 saniyede bir dinliyor.")

    while True:
        try:
            if tts_active:
                time.sleep(0.2)
                continue

            audio = sd.rec(chunk_samples, samplerate=samplerate, channels=1, dtype="float32")
            sd.wait()

            if tts_active:
                continue

            audio_flat = audio.flatten()
            rms = float(np.sqrt(np.mean(audio_flat ** 2)))
            print(f"[MIC] rms={rms:.4f}  voice_accepting={voice_accepting}")

            if rms < rms_min:
                continue

            segments, _ = whisper_model.transcribe(
                audio_flat, language="en", beam_size=1,
                initial_prompt="seizure, epilepsy, yes, no, help, okay, done, I can hear you"
            )
            text = " ".join(s.text for s in segments).strip()
            if not text:
                continue

            print(f"[VOICE HEARD] '{text}'")

            if voice_accepting:
                remember_voice_text(text)
            else:
                reply = ask_ai(text)
                latest_data["ai_decision"] = f"Q: {text}\nA: {reply}"
                threading.Thread(target=speak_text, args=(reply,), daemon=True).start()

        except Exception as e:
            print(f"[VOICE] error: {e}")
            time.sleep(1)


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
