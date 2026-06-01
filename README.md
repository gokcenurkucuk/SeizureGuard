SeizureGuard
Real-time epileptic seizure detection and emergency response system built on ESP32-S3. Fully offline — no internet, no cloud, no API key.

Hardware Requirements
ComponentRoleI2C AddressPinsESP32-S3 DevKitC-1Central microcontroller——MPU6050Accelerometer / Gyroscope0x68SDA=GPIO4, SCL=GPIO5MAX30102Pulse Oximeter / SpO20x57SDA=GPIO4, SCL=GPIO5 (shared bus)Active BuzzerLocal alarm output—GPIO6LaptopRuns Python host app—USB-A to USB-C

How It Works

ESP32-S3 reads MPU6050 and MAX30102 every 20 ms (50 Hz)
Every 500 ms window, calculates vibration magnitude and tremor frequency
If vibration ≥ 2.0G AND tremor 4–12 Hz → seizure confirmed
Buzzer fires 3 beeps immediately at hardware level
JSON packet sent to PC via USB Serial
Flask dashboard updates within 200 ms
Ollama AI dialog activates — speaks to patient and bystanders
faster-whisper listens for voice responses
pyttsx3 delivers spoken instructions


Pin Connections
ESP32-S3 PinComponentComponent Pin3.3VMPU6050VCCGNDMPU6050GNDGPIO4 (pin 30)MPU6050SDAGPIO5 (pin 32)MPU6050SCLGNDMPU6050AD03.3VMAX30102VINGNDMAX30102GNDGPIO4 (pin 30)MAX30102SDAGPIO5 (pin 32)MAX30102SCL5VBuzzer+GNDBuzzer−GPIO6BuzzerS

Installation
1. Flash ESP32-S3 Firmware
bash# Install ESP-IDF v5.x
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh

# Build and flash
cd SeizureGuard/esp/SeizureGuard
idf.py build
idf.py -p COM13 flash monitor
2. Install Python Dependencies
bashpip install flask pyserial ollama pyttsx3 sounddevice numpy faster-whisper
3. Install and Start Ollama
bash# Download Ollama from https://ollama.com
ollama pull llama3.2
ollama serve
4. Run the Host Application
bashcd SeizureGuard/web
python app.py
5. Open Dashboard
http://localhost:5000

Configuration
Open app.py and set your serial port:
pythonSERIAL_PORT = "COM13"   # Windows
# SERIAL_PORT = "/dev/ttyUSB0"  # Linux
# SERIAL_PORT = "/dev/cu.usbserial-0001"  # macOS

Seizure Detection Logic
Vibration ≥ 2.0G  AND  Tremor 4–12 Hz  →  SEIZURE
Heart rate and SpO2 are measured and displayed but are not part of the seizure trigger condition. Optical readings become unreliable during strong physical movement.

JSON Output Format
Sent every 500 ms via USB Serial at 115200 baud:
json{"vibration": 2.30, "tremor_hz": 7.1, "hr": 130.0, "spo2": 88.0, "status": "SEIZURE"}
{"vibration": 0.12, "tremor_hz": 1.2, "hr": 72.0,  "spo2": 97.0, "status": "NORMAL"}

Project Structure
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

Dependencies
LibraryPurposeESP-IDF v5.xESP32-S3 firmware frameworkFlaskWeb server and REST APIpyserialUSB serial JSON readerollama (llama3.2)Local LLM emergency dialogfaster-whisperOffline speech recognitionpyttsx3Text-to-speech outputsounddeviceMicrophone inputnumpyAudio processing

CEN322 — Internet of Things | 2026
Gökçenur Küçük 221401021 • Ayşe Mandıralı 221401039
Responsible Lecturer: Assoc. Prof. Yıldıran YILMAZ
