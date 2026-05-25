# SeizureGuard - Arkadas Bilgisayari Kurulum Rehberi

Bu rehber, projeyi baska bir bilgisayarda calistirmak icin gereken kurulumlari ve degistirilmesi gereken ayarlari anlatir. Proje internet/API kullanmadan lokal calisacak sekilde tasarlanmistir. Ollama ve Vosk modeli bir kere kurulduktan sonra internet gerekmez.

## 1. Gerekli Programlar

Arkadasinin bilgisayarinda sunlar kurulu olmalidir:

1. Visual Studio Code
2. ESP-IDF Extension
3. ESP-IDF v5.x
4. Python 3
5. Ollama
6. Git opsiyonel

ESP32 kodu icin ESP-IDF gerekir. Web ve yapay zeka tarafi icin Python, Ollama ve Python kutuphaneleri gerekir.

## 2. Proje Klasorleri

Projede iki ana kisim var:

```text
Seizureeguard/
  esp/
    SeizureGuard/
      main/
        main.c
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
web
```

## 3. Donanim Baglantilari

ESP32-S3 pinleri:

| Bilesen | Pin | ESP32 Baglantisi |
|---|---|---|
| MPU6050 SDA | SDA | GPIO4 |
| MPU6050 SCL | SCL | GPIO5 |
| MAX30102 SDA | SDA | GPIO4 |
| MAX30102 SCL | SCL | GPIO5 |
| Buzzer S | S | GPIO6 |
| Buzzer + | VCC/+ | 5V |
| Buzzer - | GND/- | GND |

I2C sensorleri ayni hatta baglanir:

```text
SDA -> GPIO4
SCL -> GPIO5
```

Buzzer icin dogru baglanti:

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

Beklenen JSON cikisi:

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
cd C:\Users\KULLANICI_ADI\Seizureeguard\web
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
vosk
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

## 7. Mikrofon Icin Vosk Modeli

Mikrofonla cevap algilamak icin Vosk modeli gerekir.

Model klasoru varsayilan olarak su yolda aranir:

```text
C:\Users\KULLANICI_ADI\vosk-model-small-en-us-0.15
```

Klasorun icinde sunlar olmalidir:

```text
am
conf
graph
ivector
README
```

Model baska bir klasordeyse uygulamayi calistirmadan once yol verilebilir:

```powershell
$env:SEIZUREGUARD_VOSK_MODEL="C:\MODEL_KLASORU\vosk-model-small-en-us-0.15"
python app.py
```

## 8. COM Port Ayari

`web/app.py` varsayilan olarak `COM3` dinler.

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
[IoT Pipeline] Listening on COMx at 115200 baud.
[VOICE] Microphone listener active.
```

Tarayicida ac:

```text
http://localhost:5000
```

## 10. AI Konusma Akisi

Sistem `SEIZURE` algiladiginda:

1. Hastaya seslenir:
   - "Hello, can you hear me right now?"
2. Cevap bekler.
3. Cevap yoksa tekrar hastaya seslenir:
   - "If you can hear me, squeeze a hand or make any sound."
4. Yine cevap yoksa cevredekilere doner:
   - Kisiyi tutmayin.
   - Basinin altina yumusak bir sey koyun.
   - Sert nesneleri uzaklastirin.
   - Agzina bir sey sokmayin.
   - Sureyi takip edin.
   - 5 dakikayi gecerse acil servisi arayin.

Durum normale donerse acil durum konusmasi durur ve sistem toparlama mesaji verir.

## 11. Arkadasinin Degistirmesi Gerekebilecek Ayarlar

Genelde sadece bunlar degisir:

| Ayar | Ne zaman degisir? | Nasil degistirilir? |
|---|---|---|
| COM port | ESP32 farkli porta takiliysa | `$env:SEIZUREGUARD_SERIAL_PORT="COMx"` |
| Vosk model yolu | Model baska klasordeyse | `$env:SEIZUREGUARD_VOSK_MODEL="..."` |
| Ollama modeli | Baska model kullanilacaksa | `$env:SEIZUREGUARD_OLLAMA_MODEL="llama3.2"` |

Kod icinde degistirmesi gereken ana yer yoktur.

## 12. Test Sirasi

1. ESP32'yi flash et.
2. Serial monitorde JSON geliyor mu kontrol et.
3. MAX30102 isigi yaniyor mu kontrol et.
4. Parmak/bilek yokken `hr=0`, `spo2=0` olmali.
5. Parmak/bilek koyunca birkac saniye sonra nabiz gelmeli.
6. Buzzer acilista test sesi vermeli.
7. Web uygulamasini ac.
8. Dashboard verileri guncelliyor mu kontrol et.
9. Ollama calisiyor mu kontrol et.
10. Mikrofon aktif mi kontrol et.

## 13. Sık  Hatalar

### Serial port error

Sebep: COM port yanlis veya ESP-IDF monitor portu kullaniyor.

Cozum:

```powershell
$env:SEIZUREGUARD_SERIAL_PORT="COMx"
python app.py
```

### Vosk model not found

Sebep: Mikrofon modeli yok veya yol yanlis.

Cozum:

```powershell
$env:SEIZUREGUARD_VOSK_MODEL="C:\model\yolu"
python app.py
```

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

Bu proje lokal calisir:

- API key yoktur.
- Internet uzerinden LLM servisi yoktur.
- Ollama lokal calisir.
- Vosk modeli lokal calisir.
- ESP32 veriyi USB serial ile bilgisayara gonderir.

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
| `vibration` | MPU6050 hareket siddeti |
| `tremor_hz` | MPU6050 verisinden yaklasik titreme frekansi |
| `hr` | MAX30102 IR sinyalinden hesaplanan nabiz |
| `spo2` | MAX30102 RED/IR oranindan yaklasik SpO2 |
| `status` | `NORMAL` veya `SEIZURE` |

### 15.2 Guncel Kriz Karari

ESP32 tarafinda temel kriz mantigi:

```text
vibration >= 1.5
tremor_hz 4-12 Hz araliginda
hr >= 120 veya spo2 <= 90
```

Kriz algilaninca durum hemen normale dusmesin diye kisa sureli `SEIZURE` hold uygulanir. Bu, AI konusurken tek bir normal sensor ornegi yuzunden acil durum akisini kesmemek icindir.

### 15.3 MAX30102 Guncel Not

MAX30102 icin son mantik:

- Parmak/bilek yokken `hr=0`, `spo2=0` hedeflenir.
- Parmak/bilek varken RED/IR seviyesi kontrol edilir.
- Nabiz, MAX30102 IR sinyalindeki tepe araliklarindan hesaplanir.
- Fake veya random nabiz uretilmez.
- Bilekte olcum parmaktan daha zordur; sensor sabit durmalidir.
- Ortam isigi, gevsek temas ve hareket olcumu bozabilir.

Test ederken:

```text
Parmak yok -> hr=0, spo2=0
Parmak/bilek var -> birkac saniye sonra hr/spo2 gelmeli
```

### 15.4 Buzzer Guncel Ayari

Buzzer 3 pinli moduldur. Dogru baglanti:

```text
S  -> GPIO6
+  -> 5V
-  -> GND
```

Kodda guncel ayar:

```c
#define BUZZER_GPIO           6
#define BUZZER_ACTIVE_LEVEL   1
#define BUZZER_IDLE_LEVEL     0
```

Beklenen davranis:

- Kart acilinca test bip sesi gelir.
- Normal durumda buzzer susar.
- `SEIZURE` durumunda sadece 3 kez bip yapar ve susar.

### 15.5 AI ve Mikrofon Guncel Akisi

Web tarafinda `app.py` lokal Ollama, pyttsx3 ve Vosk kullanir.

AI akisi:

1. Sistem `danger/SEIZURE` algilar.
2. AI once hastaya sorar:

```text
Hello, can you hear me right now?
```

3. 3 saniye cevap bekler.
4. Cevap yoksa tekrar sorar:

```text
If you can hear me, squeeze a hand or make any sound.
```

5. Yine cevap yoksa cevredekilere doner:

```text
Attention, this person may be having a seizure.
Please stay calm and follow my instructions one by one.
```

6. Cevredekilere tek tek ilk yardim komutlari verir:

```text
Do not restrain the person or try to stop their movements.
Place something soft under their head and move hard objects away.
Do not put anything in their mouth; they cannot swallow their tongue.
Check the time and wait for the shaking to stop.
If it lasts longer than five minutes, call emergency services immediately.
```

7. Durum normale donerse acil durum dongusu iptal olur ve toparlama mesaji verilir.

Mikrofon notu:

- Mikrofon sadece acil durum sirasinda cevap olarak kabul edilir.
- Normal durumda mikrofon duyduklarini acil durum cevabi olarak islemez.
- Vosk `partial` sonuclari cevap sayilmaz; sadece tamamlanmis sonuc dikkate alinir.
- Vosk her kelimeyi dogru yazmak zorunda degildir. Bu projede mikrofon cevabi daha cok "yanit var mi yok mu" sinyali olarak kullanilir.

Kisa Ingilizce cevaplar daha iyi algilanir:

```text
yes
I can hear you
someone is here
help me
I am okay
```

### 15.6 Guncel Web Requirements

`web/requirements.txt` icinde su paketler olmalidir:

```text
Flask
pyserial
ollama
pyttsx3
sounddevice
numpy
vosk
```

Kurulum:

```powershell
cd C:\Users\KULLANICI_ADI\Seizureeguard\web
pip install -r requirements.txt
```

### 15.7 Vosk Modeli

Mikrofon icin su model klasoru gerekir:

```text
C:\Users\KULLANICI_ADI\vosk-model-small-en-us-0.15
```

Klasor icinde sunlar dogrudan bulunmalidir:

```text
am
conf
graph
ivector
README
```

Eger model baska yerdeyse:

```powershell
$env:SEIZUREGUARD_VOSK_MODEL="C:\MODEL_KLASORU\vosk-model-small-en-us-0.15"
python app.py
```

### 15.8 COM Port Cakismasi

ESP-IDF monitor acikken Flask uygulamasi ayni COM portunu okuyamaz.

Dogru sira:

1. ESP32'yi flash et.
2. ESP-IDF monitoru kapat.
3. Web klasorunde `python app.py` calistir.

COM port farkliysa:

```powershell
$env:SEIZUREGUARD_SERIAL_PORT="COM5"
python app.py
```

### 15.9 ESP-IDF Build Sorunu: esp_lcd Hatası

Bazen build sirasinda su hata gorulebilir:

```text
esp_lcd_panel_rgb.c
internal compiler error: Segmentation fault
```

Bu hata proje kodundan degil, ESP-IDF/toolchain derleme probleminden kaynaklanir. Proje LCD kullanmaz.

Kalici azaltma icin ust seviye `CMakeLists.txt` dosyasina su satir eklenmistir:

```cmake
set(COMPONENTS main)
```

Eger hata devam ederse:

```powershell
idf.py fullclean
idf.py build
```

VS Code icinden:

```text
ESP-IDF: Full Clean Project
ESP-IDF: Build Project
```

### 15.10 Son Demo Kontrol Listesi

Arkadasin projeyi calistirdiginda sirayla sunlari kontrol etsin:

1. ESP32 build/flash basarili mi?
2. Buzzer acilista test sesi veriyor mu?
3. Serial JSON geliyor mu?
4. Parmak/bilek yokken `hr=0`, `spo2=0` mu?
5. Parmak/bilek varken birkac saniye sonra nabiz geliyor mu?
6. Web dashboard `http://localhost:5000` aciliyor mu?
7. Terminalde serial dinleme gorunuyor mu?

```text
[IoT Pipeline] Listening on COMx at 115200 baud.
```

8. Mikrofon aktif mi?

```text
[VOICE] Microphone listener active.
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
```
