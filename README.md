# SeizureGuard

Real-time epileptic seizure detection and emergency response system.  
Built on ESP32-S3 — fully offline, no internet, no cloud, no API key required.

---

## Table of Contents

1. [What You Need](#1-what-you-need)
2. [Wiring the Components](#2-wiring-the-components)
3. [Uploading the Firmware to ESP32-S3](#3-uploading-the-firmware-to-esp32-s3)
4. [Setting Up the Python Host Application](#4-setting-up-the-python-host-application)
5. [Installing and Starting Ollama](#5-installing-and-starting-ollama)
6. [Running the System](#6-running-the-system)
7. [Testing the System](#7-testing-the-system)
8. [How the Seizure Detection Works](#8-how-the-seizure-detection-works)
9. [Project Structure](#9-project-structure)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. What You Need

### Hardware

| Component | Model | Quantity |
|-----------|-------|----------|
| Microcontroller | ESP32-S3 DevKitC-1 | 1 |
| Accelerometer / Gyroscope | MPU6050 | 1 |
| Pulse Oximeter / SpO2 Sensor | MAX30102 | 1 |
| Active Buzzer | 3-pin module, 5V | 1 |
| Breadboard | 400-point | 1 |
| Jumper wires | Male-to-Male, Male-to-Female | As needed |
| USB cable | USB-A to USB-C | 1 |
| Laptop | x86-64, with microphone and speakers | 1 |

### Software

- [ESP-IDF v5.x](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/) — ESP32 firmware framework
- [Python 3.11+](https://www.python.org/downloads/)
- [Ollama](https://ollama.com/) — local LLM runtime
- [Visual Studio Code](https://code.visualstudio.com/) + ESP-IDF extension (recommended)

---

## 2. Wiring the Components

All components connect to the ESP32-S3 DevKitC-1 on a breadboard.  
MPU6050 and MAX30102 **share the same I2C bus** (GPIO4 and GPIO5).

### MPU6050 Connections

| MPU6050 Pin | ESP32-S3 Pin | Notes |
|-------------|--------------|-------|
| VCC | 3.3V | Power supply |
| GND | GND | Ground |
| SDA | GPIO4 (pin 30) | I2C data line |
| SCL | GPIO5 (pin 32) | I2C clock line |
| AD0 | GND | Sets I2C address to 0x68 |
| XDA | — | Not connected |
| XCL | — | Not connected |
| INT | — | Not connected |

### MAX30102 Connections

| MAX30102 Pin | ESP32-S3 Pin | Notes |
|--------------|--------------|-------|
| VIN | 3.3V | Power supply |
| GND | GND | Ground |
| SDA | GPIO4 (pin 30) | I2C data line (shared with MPU6050) |
| SCL | GPIO5 (pin 32) | I2C clock line (shared with MPU6050) |

### Active Buzzer Connections

| Buzzer Pin | ESP32-S3 Pin | Notes |
|------------|--------------|-------|
| + (Power) | 5V | Power supply |
| − (Ground) | GND | Ground |
| S (Signal) | GPIO6 | HIGH = buzzer on |

### Important Notes

- MPU6050 and MAX30102 use the same SDA and SCL lines. This works because they have different I2C addresses: MPU6050 is at **0x68**, MAX30102 is at **0x57**.
- The AD0 pin of MPU6050 must be connected to GND. This sets its I2C address to 0x68.
- The buzzer requires 5V power for sufficient volume. Do not connect it to 3.3V.
- Double-check all GND connections before powering on.

---

## 3. Uploading the Firmware to ESP32-S3

### Step 1 — Install ESP-IDF

Follow the official guide for your operating system:  
https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/

After installation, run the setup script:

```bash
# Linux / macOS
cd ~/esp/esp-idf
./install.sh esp32s3
. ./export.sh

# Windows (in ESP-IDF Command Prompt)
cd C:\esp\esp-idf
install.bat esp32s3
export.bat
```

### Step 2 — Clone or Download the Project

```bash
git clone https://github.com/gokcenurkucuk/SeizureGuard.git
cd SeizureGuard
```

### Step 3 — Navigate to the Firmware Folder

```bash
cd esp/SeizureGuard
```

### Step 4 — Set the Target to ESP32-S3

```bash
idf.py set-target esp32s3
```

### Step 5 — Build the Firmware

```bash
idf.py build
```

This will compile all source files. It may take 2–5 minutes the first time.

### Step 6 — Connect the ESP32-S3 via USB

Plug in the USB-A to USB-C cable. The ESP32-S3 should appear as a serial port:

- **Windows:** COM3, COM4, COM13, etc. (check Device Manager)
- **Linux:** /dev/ttyUSB0 or /dev/ttyACM0
- **macOS:** /dev/cu.usbserial-XXXX

### Step 7 — Flash the Firmware

Replace COM13 with your actual port:

```bash
# Windows
idf.py -p COM13 flash

# Linux / macOS
idf.py -p /dev/ttyUSB0 flash
```

### Step 8 — Verify with Serial Monitor (Optional)

```bash
idf.py -p COM13 monitor
```

If everything works, you will see JSON output like this every 500 ms:

```
{"vibration": 0.12, "tremor_hz": 1.2, "hr": 72.0, "spo2": 97.0, "status": "NORMAL"}
```

Press Ctrl + ] to exit the monitor.

### Step 9 — Startup Buzzer Test

When the ESP32 powers on, the buzzer will beep **6 times**. This confirms the firmware is running and the buzzer is wired correctly.

---

## 4. Setting Up the Python Host Application

### Step 1 — Navigate to the Web Folder

```bash
cd SeizureGuard/web
```

### Step 2 — Install Python Dependencies

```bash
pip install flask pyserial ollama pyttsx3 sounddevice numpy faster-whisper
```

### Step 3 — Set Your Serial Port

Open `app.py` in a text editor and find this line near the top:

```python
SERIAL_PORT = os.getenv("SEIZUREGUARD_SERIAL_PORT", "COM13")
```

Change COM13 to match your ESP32-S3 serial port:

```python
# Windows example
SERIAL_PORT = os.getenv("SEIZUREGUARD_SERIAL_PORT", "COM4")

# Linux example
SERIAL_PORT = os.getenv("SEIZUREGUARD_SERIAL_PORT", "/dev/ttyUSB0")

# macOS example
SERIAL_PORT = os.getenv("SEIZUREGUARD_SERIAL_PORT", "/dev/cu.usbserial-0001")
```

Save the file.

---

## 5. Installing and Starting Ollama

Ollama runs the Llama 3.2 language model locally on your laptop. No internet connection is needed after the initial download.

### Step 1 — Download and Install Ollama

Go to https://ollama.com and download the installer for your operating system. Run the installer.

### Step 2 — Download the Llama 3.2 Model

Open a terminal and run:

```bash
ollama pull llama3.2
```

This downloads the model (approximately 2 GB). You only need to do this once.

### Step 3 — Start the Ollama Service

```bash
ollama serve
```

Keep this terminal window open while using SeizureGuard. Ollama must be running in the background for the AI emergency dialog to work.

---

## 6. Running the System

Follow these steps in order every time you use SeizureGuard.

**Step 1** — Connect the ESP32-S3 via USB. The buzzer will beep 6 times on startup.

**Step 2** — Start Ollama in a terminal:

```bash
ollama serve
```

**Step 3** — Open a second terminal and start the Python application:

```bash
cd SeizureGuard/web
python app.py
```

You will see output like this:

```
[IoT Pipeline] Listening on COM13 at 115200 baud.
[VOICE] faster-whisper small model loaded.
* Running on http://127.0.0.1:5000
```

**Step 4** — Open your browser and go to:

```
http://localhost:5000
```

The dashboard will show live sensor values. The status banner turns green when data arrives from the ESP32.

---

## 7. Testing the System

### Test 1 — Normal State

Open the dashboard. Place your finger on the MAX30102 sensor. After a few seconds, heart rate (BPM) and SpO2 (%) values appear. The banner should show SYSTEM NORMAL in green.

### Test 2 — Seizure Detection

Shake the ESP32 and sensor assembly firmly and repeatedly. When vibration reaches 2.0G or above with tremor frequency between 4 and 12 Hz, the system will:

1. Fire the buzzer — 3 beeps (180 ms ON / 300 ms OFF)
2. Switch the dashboard to red emergency mode
3. Activate the Ollama AI emergency dialog
4. The AI will speak: "Hello, can you hear me right now?"

Stop shaking. The system returns to normal mode automatically.

### Test 3 — Push-to-Talk Voice Assistant

On the dashboard, click the **Start Speaking** button. Speak into your microphone. Click **Stop Speaking**. The system will transcribe your speech with faster-whisper, send it to Ollama, display the response, and speak it aloud with pyttsx3. No internet is used.

### Test 4 — Buzzer Startup Test

Disconnect and reconnect the USB cable. The buzzer should beep 6 times within the first 5 seconds. If it does not beep, check the wiring (5V to +, GND to −, GPIO6 to S).

---

## 8. How the Seizure Detection Works

The ESP32-S3 samples both sensors every 20 ms for a 500 ms window (25 samples at 50 Hz).

Vibration magnitude is calculated from the MPU6050:

```
total_g = sqrt(ax^2 + ay^2 + az^2)
```

Tremor frequency is estimated by counting zero-crossings of the G-force signal across the window.

**Seizure is confirmed when both conditions are true at the same time:**

```
Vibration >= 2.0G   AND   Tremor frequency 4-12 Hz   ->   SEIZURE
```

Heart rate and SpO2 are measured and displayed but are not used as seizure triggers because optical readings become unreliable during strong movement.

On seizure confirmation:
- Buzzer fires immediately at hardware level (no PC needed)
- JSON packet sent via USB Serial to Python host
- Flask dashboard switches to emergency mode
- Ollama Llama 3.2 starts the emergency voice dialog

---

## 9. Project Structure

```
SeizureGuard/
├── esp/
│   └── SeizureGuard/
│       └── main/
│           ├── main.c            <- ESP32 firmware (C / ESP-IDF)
│           └── CMakeLists.txt    <- Build configuration
└── web/
    ├── app.py                    <- Python host application
    ├── requirements.txt          <- Python dependencies
    └── templates/
        └── index.html            <- Web dashboard
```

---

## 10. Troubleshooting

**Dashboard shows "Connecting to Edge Gateway" and does not update**
- Check that the correct serial port is set in app.py
- Make sure the ESP32-S3 is connected and firmware is flashed
- Try unplugging and replugging the USB cable

**Buzzer does not beep on startup**
- Check that S pin is connected to GPIO6
- Check that + pin is connected to 5V (not 3.3V)
- Check that − pin is connected to GND

**Heart rate and SpO2 show "--" on dashboard**
- Place your finger firmly on the MAX30102 sensor
- Wait 5-10 seconds for readings to stabilize
- Make sure VIN is connected to 3.3V and GND is connected

**AI dialog does not start after seizure**
- Make sure Ollama is running: ollama serve
- Make sure the model is downloaded: ollama pull llama3.2

**Push-to-talk does not work**
- Check that your microphone is connected and not muted
- Make sure sounddevice and numpy are installed

**Serial port error on Linux**

```bash
sudo usermod -a -G dialout $USER
```

Log out and log back in after running this command.

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
| numpy | Audio signal processing |

---

## CEN322 — Internet of Things | 2026

**Gökçenur Küçük** 221401021  
**Ayşe Mandıralı** 221401039  
Responsible Lecturer: Assoc. Prof. Yıldıran YILMAZ  
T.C. Recep Tayyip Erdoğan University — Department of Computer Engineering  
GitHub: https://github.com/gokcenurkucuk/SeizureGuard
