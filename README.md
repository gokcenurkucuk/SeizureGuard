# SeizureGuard

> Real-time epileptic seizure detection and emergency response system built on ESP32-S3.  
> Fully offline — no internet, no cloud, no API key.

---

## What It Does

SeizureGuard is a wrist-worn IoT prototype that detects epileptic seizures in real time. The ESP32-S3 microcontroller reads motion and biometric data from two sensors, applies a seizure detection algorithm, and triggers an immediate hardware alarm. A Python host application on a connected laptop displays live sensor data on a web dashboard and activates a local AI emergency dialog that speaks to the patient and nearby bystanders — all without any internet connection.

---

## Hardware

| Component | Role | I2C Address | Pins |
|-----------|------|-------------|------|
| ESP32-S3 DevKitC-1 | Central microcontroller | — | — |
| MPU6050 | Accelerometer / Gyroscope | 0x68 | SDA=GPIO4, SCL=GPIO5 |
| MAX30102 | Pulse Oximeter / SpO2 | 0x57 | SDA=GPIO4, SCL=GPIO5 (shared bus) |
| Active Buzzer | Local alarm output | — | GPIO6 |
| Laptop | Runs Python host application | — | USB-A to USB-C |

---

## Pin Connections

| ESP32-S3 Pin | Component | Component Pin | Notes |
|---|---|---|---|
| 3.3V | MPU6050 | VCC | Power |
| GND | MPU6050 | GND | Ground |
| GPIO4 (pin 30) | MPU6050 | SDA | I2C shared bus |
| GPIO5 (pin 32) | MPU6050 | SCL | I2C shared bus |
| GND | MPU6050 | AD0 | Sets address to 0x68 |
| — | MPU6050 | XDA / XCL / INT | Not connected |
| 3.3V | MAX30102 | VIN | Power |
| GND | MAX30102 | GND | Ground |
| GPIO4 (pin 30) | MAX30102 | SDA | I2C shared bus |
| GPIO5 (pin 32) | MAX30102 | SCL | I2C shared bus |
| 5V | Buzzer | + | Power |
| GND | Buzzer | − | Ground |
| GPIO6 | Buzzer | S | HIGH activates buzzer |

---

## How It Works

1. ESP32-S3 reads MPU6050 and MAX30102 every 20 ms (50 Hz)
2. Every 500 ms window (25 samples), calculates vibration magnitude and tremor frequency
3. Seizure confirmed when **both** conditions are true simultaneously:

```
Vibration ≥ 2.0G  AND  Tremor frequency 4–12 Hz  →  SEIZURE
```

4. Buzzer fires 3 beeps immediately at hardware level (independent of PC)
5. JSON packet sent to PC via USB Serial at 115200 baud
6. Flask dashboard updates within 200 ms
7. Ollama (Llama 3.2) AI dialog activates — speaks to patient and bystanders
8. faster-whisper listens for voice responses locally
9. pyttsx3 delivers spoken instructions

> Heart rate and SpO2 are measured and displayed on the dashboard but are **not** used as seizure triggers. Optical readings become unreliable during strong physical movement.

---

## JSON Output

Sent every 500 ms via USB Serial:

```json
{"vibration": 2.30, "tremor_hz": 7.1, "hr": 130.0, "spo2": 88.0, "status": "SEIZURE"}
{"vibration": 0.12, "tremor_hz": 1.2, "hr": 72.0,  "spo2": 97.0, "status": "NORMAL"}
```

---

## Installation

### 1. Flash ESP32-S3 Firmware

```bash
# Install ESP-IDF v5.x
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh

# Build and flash
cd SeizureGuard/esp/SeizureGuard
idf.py build
idf.py -p COM13 flash monitor
```

### 2. Install Python Dependencies

```bash
pip install flask pyserial ollama pyttsx3 sounddevice numpy faster-whisper
```

### 3. Install and Start Ollama

```bash
# Download from https://ollama.com
ollama pull llama3.2
ollama serve
```

### 4. Set Serial Port

Open `web/app.py` and update:

```python
SERIAL_PORT = "COM13"          # Windows
# SERIAL_PORT = "/dev/ttyUSB0"       # Linux
# SERIAL_PORT = "/dev/cu.usbserial"  # macOS
```

### 5. Run Host Application

```bash
cd SeizureGuard/web
python app.py
```

### 6. Open Dashboard

```
http://localhost:5000
```

---

## Project Structure

```
SeizureGuard/
├── esp/
│   └── SeizureGuard/
│       └── main/
│           ├── main.c
│           └── CMakeLists.txt
└── web/
    ├── app.py
    ├── requirements.txt
    └── templates/
        └── index.html
```

---

## Dependencies

| Library | Purpose |
|---------|---------|
| ESP-IDF v5.x | ESP32-S3 firmware framework |
| Flask | Web server and REST API |
| pyserial | USB serial JSON reader |
| ollama (llama3.2) | Local LLM emergency dialog |
| faster-whisper | Offline speech recognition |
| pyttsx3 | Text-to-speech output |
| sounddevice | Microphone input |
| numpy | Audio processing |

---

## SpO2 Calculation

Simplified Beer-Lambert method:

```
R = (red_AC / red_DC) / (ir_AC / ir_DC)
SpO2 ≈ 110 − 25 × R    (clamped to 70–100%)
```

---

## CEN322 — Internet of Things | 2026

**Gökçenur Küçük** 221401021 • **Ayşe Mandıralı** 221401039  
Responsible Lecturer: Assoc. Prof. Yıldıran YILMAZ  
T.C. Recep Tayyip Erdoğan University — Department of Computer Engineering
