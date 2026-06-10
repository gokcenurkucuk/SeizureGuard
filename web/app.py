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

DEMO_MODE = True
DEMO_SEIZURE_HR = 125     # esik 120 ustu -> tehlike
DEMO_SEIZURE_SPO2 = 78    # esik 80 ve alti -> tehlike
DEMO_NORMAL_HR = 76       # normal
DEMO_NORMAL_SPO2 = 98     # normal
# Anlik paralel takip: titresim esigi gecince HR/SpO2 de ayni anda nobet degerine ciker.
DEMO_MOTION_THRESHOLD = 2.0
DANGER_LATCH_SEC = 5.0
_last_danger_time = 0.0

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

# Bas-konus (push-to-talk) durumu
manual_recording = False
manual_frames = []
manual_lock = threading.Lock()

EMERGENCY_MIN_DURATION = 25.0

SYSTEM_PROMPT = (
    "You are SeizureGuard, an AI emergency voice assistant for an epilepsy seizure detection wearable. "
    "Your job is to give CONCRETE, ACTIONABLE safety instructions — tell the person exactly what to DO. "
    "Do NOT just comfort or reassure (avoid empty phrases like 'I've got you', 'you're safe', 'I'm here'). "
    "Every reply must contain a clear physical action: lie on your side, move away from hard objects, "
    "do not stand up, loosen tight clothing, breathe slowly, stay where you are. "
    "Always reply with ONE short, calm, spoken English sentence that tells them what to do. No diagnosis."
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

            # Karsilikli konusma: SADECE hasta konusunca cevap ver, bosta tekrar etme
            while generation == emergency_generation:
                if finish_if_normal(generation): return
                reply = wait_for_reply(12, generation)
                if finish_if_normal(generation): return
                if not reply:
                    continue  # cevap yoksa sessizce beklemeye devam et, ayni seyi tekrarlama
                history.append({"role": "user", "content": reply})
                msg = llm_say(
                    f"Stage: patient dialog. The patient said: '{reply}'. Reply with ONE concrete safety action they should do RIGHT NOW during the seizure (lie on your side, move away from hard objects, do not stand, breathe slowly). Do not just comfort them.",
                    history, "Lie down on your side and keep your head away from hard objects."
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
    global emergency_mode_active, emergency_generation, emergency_start_time

    while True:
        # Sadece tehlike VAR ve aktif dialog YOKSA yeni dialog baslat.
        # Dialog kendi kendine biter (status normal olunca finish_if_normal).
        # Manager zorla kapatmaz -> tek seferde tek thread garantisi.
        if latest_data["status"] == "danger" and not emergency_mode_active:
            emergency_mode_active = True
            emergency_start_time = time.time()
            emergency_generation += 1
            threading.Thread(
                target=run_emergency_dialog,
                args=(emergency_generation,),
                daemon=True,
            ).start()

        time.sleep(0.5)


def is_danger(data):
    # Demo modu: anlik paralel — titresim esik ustundeyse nobet, altindaysa normal
    return latest_data["shake_level"] >= DEMO_MOTION_THRESHOLD


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

                        latest_data["shake_level"] = float(data.get("vibration", data.get("shake", 0.0)))
                        latest_data["tremor_hz"] = float(data.get("tremor_hz", 0.0))

                        if DEMO_MODE:
                            global _last_danger_time
                            shake = latest_data["shake_level"]
                            if shake >= DEMO_MOTION_THRESHOLD:
                                _last_danger_time = time.time()
                            if time.time() - _last_danger_time < DANGER_LATCH_SEC:
                                # KRIZ: esik ustunde ya da son 5 sn icinde tetiklendi
                                latest_data["heart_rate"] = DEMO_SEIZURE_HR
                                latest_data["spo2"] = DEMO_SEIZURE_SPO2
                                latest_data["status"] = "danger"
                            else:
                                # NORMAL: GERCEK sensor degeri (parmak yoksa 0 -> ekranda --)
                                latest_data["heart_rate"] = int(float(data.get("hr", 0)))
                                latest_data["spo2"] = int(float(data.get("spo2", 0)))
                                latest_data["status"] = "normal"
                        else:
                            latest_data["heart_rate"] = int(float(data.get("hr", 0)))
                            latest_data["spo2"] = int(float(data.get("spo2", 0)))
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
    chunk_sec = 2.5  # Tam cumle yakalamak icin uzun pencere
    chunk_samples = int(chunk_sec * samplerate)
    rms_min = 0.006  # Pencere uzun oldugu icin esik biraz yuksek (gurultu elenmeli)
    print("[VOICE] Listener active — her 2.5 saniyede bir tam cumle dinliyor.")

    while True:
        try:
            # Bas-konus aktifken sureklı dinlemeyi durdur (mikrofon cakismasin)
            if manual_recording or tts_active or not voice_accepting:
                time.sleep(0.2)
                continue

            audio = sd.rec(chunk_samples, samplerate=samplerate, channels=1, dtype="float32")
            sd.wait()

            if tts_active or not voice_accepting:
                continue

            audio_flat = audio.flatten()
            rms = float(np.sqrt(np.mean(audio_flat ** 2)))

            print(f"[MIC] rms={rms:.4f} esik={rms_min}")

            if rms < rms_min:
                continue

            print(f"[MIC] SES ALGILANDI — Whisper isliyor...")

            segments, _ = whisper_model.transcribe(
                audio_flat, language="en", beam_size=1,
                initial_prompt="seizure, epilepsy, yes, no, help, okay, done, I can hear you"
            )
            text = " ".join(s.text for s in segments).strip()
            if not text:
                continue

            print(f"[VOICE HEARD] '{text}'")
            remember_voice_text(text)

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


# ============ BAS-KONUS (Push-to-Talk) Sesli Asistan ============

VOICE_ASSISTANT_PROMPT = (
    "You are SeizureGuard, an offline emergency voice assistant for a seizure detection device. "
    "You run fully locally. Do not mention cloud, API, or internet. "
    "Speak calmly. Keep every sentence short. Ask only one question at a time. "
    "Give only one instruction at a time. Do not give long explanations. "
    "Never tell anyone to restrain the person. Never tell anyone to put anything in the person's mouth. "
    "If needed, tell them to move hard objects away, protect the head, check breathing, "
    "and call emergency services if the seizure lasts more than five minutes."
)


_manual_stream = None


def _manual_callback(indata, frames_count, time_info, status):
    """Mikrofon akisindan gelen her parcayi biriktir (kesintisiz)."""
    with manual_lock:
        manual_frames.append(indata.copy().flatten())


@app.route("/api/voice/start", methods=["POST"])
def voice_start():
    global manual_recording, manual_frames, _manual_stream
    if sd is None or np is None:
        return jsonify({"error": "Microphone access failed."}), 500
    with manual_lock:
        manual_frames = []
    try:
        _manual_stream = sd.InputStream(
            samplerate=16000, channels=1, dtype="float32", callback=_manual_callback
        )
        _manual_stream.start()
    except Exception as e:
        print(f"[VOICE PTT] mikrofon acilamadi: {e}")
        return jsonify({"error": "Microphone access failed."}), 500
    manual_recording = True
    print("[VOICE PTT] Kayit basladi (InputStream).")
    return jsonify({"status": "recording"})


@app.route("/api/voice/stop", methods=["POST"])
def voice_stop():
    global manual_recording, _manual_stream
    manual_recording = False
    if _manual_stream is not None:
        try:
            _manual_stream.stop()
            _manual_stream.close()
        except Exception:
            pass
        _manual_stream = None
    time.sleep(0.2)

    with manual_lock:
        frames = list(manual_frames)
    if not frames:
        return jsonify({"user_text": "", "assistant_text": "Could not transcribe audio."})

    audio = np.concatenate(frames)
    rms = float(np.sqrt(np.mean(audio ** 2)))
    dur = len(audio) / 16000
    print(f"[VOICE PTT] Kayit bitti: {dur:.1f}s, {len(frames)} blok, RMS={rms:.4f}")

    if rms < 0.001:
        return jsonify({
            "user_text": "",
            "assistant_text": f"Microphone too quiet (RMS={rms:.4f}, {dur:.1f}s). Speak louder or check mic.",
        })

    # 1) Ses -> Metin (faster-whisper, lokal)
    try:
        segments, _ = whisper_model.transcribe(audio, language="en", beam_size=1)
        user_text = " ".join(s.text for s in segments).strip()
    except Exception as e:
        print(f"[VOICE PTT] Whisper hatasi: {e}")
        return jsonify({"user_text": "", "assistant_text": "Could not transcribe audio."})

    if not user_text:
        return jsonify({"user_text": "", "assistant_text": "Could not transcribe audio."})

    print(f"[VOICE PTT] You said: {user_text}")

    # 2) Metin -> LLM cevabi (Ollama llama3.2, lokal)
    try:
        with ai_lock:
            response = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": VOICE_ASSISTANT_PROMPT},
                    {"role": "user", "content": f"The user said: {user_text}\nRespond with one short helpful sentence."},
                ],
                options={"temperature": 0.3},
            )
        assistant_text = first_sentence(response.get("message", {}).get("content", ""))
    except Exception as e:
        print(f"[VOICE PTT] Ollama hatasi: {e}")
        return jsonify({"user_text": user_text, "assistant_text": "LLM response failed."})

    if not assistant_text:
        assistant_text = "Please stay calm and keep the person safe."

    print(f"[VOICE PTT] Assistant: {assistant_text}")
    latest_data["ai_decision"] = f"You said: {user_text}\nAssistant: {assistant_text}"

    # 3) Cevap -> Ses (pyttsx3, lokal)
    threading.Thread(target=speak_text, args=(assistant_text,), daemon=True).start()

    return jsonify({"user_text": user_text, "assistant_text": assistant_text})


def load_whisper_model():
    """Push-to-talk icin whisper modelini onceden yukle."""
    global whisper_model
    try:
        from faster_whisper import WhisperModel
        whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
        print("[VOICE] faster-whisper small model loaded (push-to-talk hazir).")
    except Exception as e:
        print(f"[VOICE] Whisper model load error: {e}")


if __name__ == "__main__":
    threading.Thread(target=read_serial_data, daemon=True).start()
    threading.Thread(target=emergency_manager_loop, daemon=True).start()
    # continuous_listen KAPALI — push-to-talk ile mikrofon cakismasin.
    # Whisper modelini yine de yukluyoruz ki push-to-talk kullanabilsin.
    threading.Thread(target=load_whisper_model, daemon=True).start()
    app.run(debug=False, port=5000, use_reloader=False, threaded=True)
