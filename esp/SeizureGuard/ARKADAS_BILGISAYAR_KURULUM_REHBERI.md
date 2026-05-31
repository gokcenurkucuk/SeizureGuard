# SeizureGuard - Arkadas Bilgisayari Kurulum Rehberi

Bu rehber, projeyi baska bir bilgisayarda calistirmak icin gereken kurulumlari ve degistirilmesi gereken ayarlari anlatir. Proje internet/API kullanmadan lokal calisacak sekilde tasarlanmistir. Ollama ve Whisper modeli bir kere kurulduktan sonra internet gerekmez.

## 1. Gerekli Programlar

Arkadasinin bilgisayarinda sunlar kurulu olmalidir:

1. Visual Studio Code
2. ESP-IDF Extension
3. ESP-IDF v5.x
4. Python 3
5. Ollama
6. Git (opsiyonel)

ESP32 kodu icin ESP-IDF gerekir. Web ve yapay zeka tarafi icin Python, Ollama ve Python kutuphaneleri gerekir.

## 2. Proje Klasorleri

Projede iki ana kisim var:

```text
SeizureGuard/
  esp/
    SeizureGuard/
      main/
        main.c
        CMakeLists.txt
      CMakeLists.txt
  web/
    app.py
    requirements.txt
    templates/
      index.html
```

ESP32 firmware:

```text
esp/SeizureGuard
```

Web dashboard + lokal AI:

```text
web/
```

## 3. Donanim Baglantilari

ESP32-S3 pinleri:

| Bilesen | Sensor Pini | ESP32-S3 Pini |
|---|---|---|
| MPU6050 SDA | SDA | GPIO4 |
| MPU6050 SCL | SCL | GPIO5 |
| MPU6050 VCC | VCC | 3.3V |
| MPU6050 GND | GND | GND |
| MAX30102 SDA | SDA | GPIO4 |
| MAX30102 SCL | SCL | GPIO5 |
| MAX30102 VCC | VCC | 3.3V |
| MAX30102 GND | GND | GND |
| Buzzer S | S | GPIO6 |
| Buzzer + | VCC/+ | 5V |
| Buzzer - | GND/- | GND |

MPU6050 ve MAX30102 ayni I2C hattini paylasir (farkli I2C adresleri):

```text
MPU6050 adresi: 0x68
MAX30102 adresi: 0x57
SDA -> GPIO4
SCL -> GPIO5
```

Buzzer 3 pinli moduldur:

```text
S  -> GPIO6
+  -> 5V
-  -> GND
```

## 4. ESP32 Kodunu Yukleme

VS Code icinde:

1. `esp/SeizureGuard` klasorunu ac.
2. ESP-IDF hedef karti `ESP32-S3` sec.
3. ESP32'nin bagli oldugu COM portunu sec.
4. Su komutu calistir:

```text
ESP-IDF: Build, Flash and Monitor
```

Serial monitor ayari:

```text
115200 baud
```

Beklenen JSON cikisi (normal durum):

```json
{"vibration": 0.12, "tremor_hz": 0.0, "hr": 78.0, "spo2": 97.0, "status": "NORMAL"}
```

Kriz durumunda:

```json
{"vibration": 1.80, "tremor_hz": 6.0, "hr": 125.0, "spo2": 89.0, "status": "SEIZURE"}
```

## 5. Web Tarafi Python Kurulumu

Terminalde web klasorune git:

```powershell
cd C:\Users\KULLANICI_ADI\SeizureGuard\web
```

Gerekli Python kutuphanelerini kur:

```powershell
pip install -r requirements.txt
```

`requirements.txt` icinde gerekenler:

```text
Flask
pyserial
ollama
pyttsx3
sounddevice
numpy
openai-whisper
```

## 6. Ollama Kurulumu

Ollama kurulduktan sonra model indirilmelidir:

```powershell
ollama pull llama3.2
```

Kontrol:

```powershell
ollama list
```

`llama3.2` listede gorunmelidir.

Web uygulamasi Ollama'yi lokal olarak kullanir. Internet API anahtari yoktur.

## 7. Mikrofon Icin Whisper Kurulumu

Ses algilamak icin OpenAI Whisper kullanilir. Kurulum:

```powershell
pip install openai-whisper
```

Whisper modeli ilk calistirildiginda otomatik indirilir. Ekstra klasor veya dosya hazirlamak gerekmez.

```text
Varsayilan model: base
Dil: Ingilizce (en)
```

Ilk calistirmada model indirme suresi internet hizina gore degisir. Sonraki calistirmalarda hazir gelir.

Not: `ffmpeg` kurulu olmasi gerekebilir. Yoksa:

```powershell
winget install ffmpeg
```

## 8. COM Port Ayari

`web/app.py` varsayilan olarak `COM13` dinler.

Arkadasinin ESP32 portu farkliysa uygulamayi calistirmadan once ayarlasin:

```powershell
$env:SEIZUREGUARD_SERIAL_PORT="COM5"
python app.py
```

COM portunu Windows Aygit Yoneticisi'nden veya ESP-IDF monitor ciktisindan gorebilir.

Baud ayari:

```text
115200
```

## 9. Web Uygulamasini Calistirma

Web klasorunde:

```powershell
python app.py
```

Beklenen terminal mesajlari:

```text
[IoT Pipeline] Listening on COM13 at 115200 baud.
[VOICE] Whisper model loaded (base).
[VOICE] Whisper microphone listener active.
```

Tarayicida ac:

```text
http://localhost:5000
```

## 10. AI Konusma Akisi

Sistem `SEIZURE` algiladiginda:

1. Hastaya seslenir:
   - "Hello, can you hear me right now?"
2. 3 saniye cevap bekler.
3. Cevap yoksa tekrar hastaya seslenir:
   - "If you can hear me, squeeze a hand or make any sound."
4. Yine cevap yoksa cevredekilere doner:
   - "Attention, this person may be having a seizure."
   - "Please stay calm and follow my instructions one by one."
5. Cevredekilere tek tek ilk yardim komutlari verir:
   - Kisiyi tutmayin.
   - Basinin altina yumusak bir sey koyun.
   - Agzina bir sey sokmayin.
   - Sureyi takip edin.
   - 5 dakikayi gecerse acil servisi arayin.
6. Durum normale donerse acil durum konusmasi durur ve toparlama mesaji verilir.

## 11. Arkadasinin Degistirmesi Gerekebilecek Ayarlar

Genelde sadece bunlar degisir:

| Ayar | Ne zaman degisir? | Nasil degistirilir? |
|---|---|---|
| COM port | ESP32 farkli porta takiliysa | `$env:SEIZUREGUARD_SERIAL_PORT="COMx"` |
| Ollama modeli | Baska model kullanilacaksa | `$env:SEIZUREGUARD_OLLAMA_MODEL="llama3.2"` |
| Ses ozelligi | Kapatmak istersen | `$env:SEIZUREGUARD_ENABLE_VOICE="0"` |

Kod icinde degistirmesi gereken ana yer yoktur.

## 12. Test Sirasi

1. ESP32'yi flash et.
2. Serial monitorde JSON geliyor mu kontrol et.
3. MAX30102 isigi yaniyor mu kontrol et.
4. Parmak yokken `hr=0`, `spo2=0` olmali.
5. Parmak/bilek koyunca birkac saniye sonra nabiz gelmeli.
6. Buzzer acilista test sesi vermeli (6 bip).
7. Web uygulamasini ac.
8. Dashboard verileri guncelliyor mu kontrol et.
9. Ollama calisiyor mu kontrol et.
10. Mikrofon aktif mi kontrol et.

## 13. Sik Hatalar

### Serial port error

Sebep: COM port yanlis veya ESP-IDF monitor portu kullaniyor.

Cozum:

```powershell
$env:SEIZUREGUARD_SERIAL_PORT="COMx"
python app.py
```

### Whisper / ffmpeg hatasi

Sebep: ffmpeg kurulu degil.

Cozum:

```powershell
winget install ffmpeg
```

ffmpeg kurulduktan sonra terminali kapatip ac, tekrar dene.

### Ollama error

Sebep: Ollama calismiyor veya model yok.

Cozum:

```powershell
ollama pull llama3.2
ollama list
```

### Buzzer ses vermiyor

Dogru baglanti:

```text
S  -> GPIO6
+  -> 5V
-  -> GND
```

### Nabiz yanlis veya 0

MAX30102 temas sensorudur. Parmak/bilek sabit durmalidir. Hareket, gevsek temas ve ortam isigi olcumu bozabilir.

## 14. Teslim Notu

Bu proje tamamen lokal calisir:

- API key yoktur.
- Internet uzerinden LLM servisi yoktur.
- Ollama lokal calisir.
- Whisper lokal calisir (model bir kere indirilir).
- ESP32 veriyi USB serial ile bilgisayara gonderir.

---

## 15. Guncel Proje Durumu ve Son Ayarlar

Bu bolum projede son yapilan degisiklikleri ozetler. Arkadasin projeyi kurarken ozellikle bu bolume dikkat etmelidir.

### 15.1 Guncel ESP32 JSON Formati

ESP32 artik serial porta su formatta JSON basar:

```json
{"vibration": 0.12, "tremor_hz": 0.0, "hr": 78.0, "spo2": 97.0, "status": "NORMAL"}
```

Kriz durumunda ornek:

```json
{"vibration": 1.80, "tremor_hz": 6.0, "hr": 125.0, "spo2": 89.0, "status": "SEIZURE"}
```

Alanlar:

| Alan | Anlam |
|---|---|
| `vibration` | MPU6050 hareket siddeti (G-force) |
| `tremor_hz` | MPU6050 verisinden yaklasik titreme frekansi |
| `hr` | MAX30102 IR sinyalinden hesaplanan nabiz (BPM) |
| `spo2` | MAX30102 RED/IR oranindan yaklasik SpO2 (%) |
| `status` | `NORMAL` veya `SEIZURE` |

### 15.2 Guncel Kriz Karari Mantigi

ESP32 tarafinda temel kriz kriteri:

```text
vibration >= 1.5 G
tremor_hz 4-12 Hz araliginda
hr >= 120 BPM  VEYA  spo2 <= 90%
```

Tum kosullar ayni anda saglanirsa `SEIZURE` basilir.

Kriz algilaninca durum hemen normale dusmesin diye 2.5 saniyelik `SEIZURE` hold uygulanir (5 pencere × 500ms). Bu, AI konusurken tek bir normal sensor ornegi yuzunden acil durum akisini kesmemek icindir.

### 15.3 Sensor Pencere Ayarlari

```c
#define SENSOR_SAMPLE_COUNT   25   // 25 ornek x 20ms = 500ms pencere
#define SENSOR_SAMPLE_MS      20   // 50 Hz ornekleme
#define SEIZURE_HOLD_WINDOWS  5    // 5 pencere = 2.5 saniye hold
```

500ms pencere sayesinde sallama hareketi 1 saniye degil yarim saniyede algilanir.

### 15.4 MAX30102 Guncel Not

- Parmak/bilek yokken `hr=0`, `spo2=0` hedeflenir.
- Parmak/bilek varken RED/IR seviyesi kontrol edilir.
- Nabiz, MAX30102 IR sinyalindeki tepe araliklarindan hesaplanir.
- Bir pencerede beat alinmazsa son bilinen nabiz korunur (sifirlanmaz).
- Bilekte olcum parmaktan daha zordur; sensor sabit durmalidir.
- Ortam isigi, gevsek temas ve hareket olcumu bozabilir.

### 15.5 Buzzer Guncel Ayari

```c
#define BUZZER_GPIO           6
#define BUZZER_ACTIVE_LEVEL   1
#define BUZZER_IDLE_LEVEL     0
```

Beklenen davranis:

- Kart acilinca 6 bip test sesi gelir.
- Normal durumda buzzer susar.
- `SEIZURE` durumunda 3 bip yapar ve susar.

### 15.6 AI ve Mikrofon Guncel Akisi

Web tarafinda `app.py` lokal Ollama, pyttsx3 ve OpenAI Whisper kullanir.

Mikrofon davranisi:

- Whisper `base` modeli ile Ingilizce ses algilanir.
- Mikrofon sadece acil durum sirasinda cevap olarak aktif olur.
- Normal durumda duyulanlar soru olarak islenir ve AI yanit verir.
- Kisa Ingilizce cevaplar daha iyi algilanir:

```text
yes
I can hear you
someone is here
help me
I am okay
```

### 15.7 Guncel Web Requirements

`web/requirements.txt`:

```text
Flask
pyserial
ollama
pyttsx3
sounddevice
numpy
openai-whisper
```

Kurulum:

```powershell
cd C:\Users\KULLANICI_ADI\SeizureGuard\web
pip install -r requirements.txt
```

### 15.8 COM Port Cakismasi

ESP-IDF monitor acikken Flask uygulamasi ayni COM portunu okuyamaz.

Dogru sira:

1. ESP32'yi flash et.
2. ESP-IDF monitoru kapat.
3. Web klasorunde `python app.py` calistir.

### 15.9 ESP-IDF Build Sorunu

Bazen build sirasinda su hata gorulebilir:

```text
esp_lcd_panel_rgb.c
internal compiler error: Segmentation fault
```

Bu hata proje kodundan degil, ESP-IDF/toolchain derleme probleminden kaynaklanir. Proje LCD kullanmaz. Ust seviye `CMakeLists.txt` dosyasinda `set(COMPONENTS main)` satiri bu hatayı azaltmak icin eklenmistir.

Eger hata devam ederse:

```powershell
idf.py fullclean
idf.py build
```

### 15.10 Son Demo Kontrol Listesi

1. ESP32 build/flash basarili mi?
2. Buzzer acilista 6 bip test sesi veriyor mu?
3. Serial JSON geliyor mu?
4. Parmak yokken `hr=0`, `spo2=0` mu?
5. Parmak/bilek varken birkac saniye sonra nabiz geliyor mu?
6. Web dashboard `http://localhost:5000` aciliyor mu?
7. Terminalde serial dinleme gorunuyor mu?

```text
[IoT Pipeline] Listening on COM13 at 115200 baud.
```

8. Whisper aktif mi?

```text
[VOICE] Whisper model loaded (base).
[VOICE] Whisper microphone listener active.
```

9. Ollama modeli var mi?

```powershell
ollama list
```

10. Kriz durumunda:

```text
status = SEIZURE / danger
buzzer 3 bip
AI hasta/cevre konusma akisi
kirmizi banner: EMERGENCY: EPILEPSY SEIZURE DETECTED
```
