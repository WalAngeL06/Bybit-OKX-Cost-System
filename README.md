# 🚀 Bybit & OKX Hacim & Maliyet Takip Sistemi (Lokal & AI Destekli)

Kripto para airdrop ve borsa etkinlikleri (Bybit Token Splash, Alpha, Stock Buzz, Puzzle Hunt; OKX Flash Earn vb.) için **otomatik işlem geçmişi dinleyici, maliyet/makas hesaplayıcı ve Excel senkronizasyon sistemi**.

Tamamen yerel bilgisayarınızda (`localhost:8000`) çalışır; **harici domain, sunucu veya bulut aboneliği gerektirmez**.

---

## ✨ Temel Özellikler

* **🔒 %100 Güvenli & Yerel Mimari:**
  * Sadece **"Sadece Okuma" (Read-Only)** yetkisine sahip API anahtarlarıyla çalışır. Alım-satım veya para çekme izni kesinlikle gerekmez.
  * API anahtarları asla üçüncü parti bir sunucuya gönderilmez; yalnızca kendi bilgisayarınızdaki yerel `.env` dosyasında tutulur.
* **⚡ Tek Tıkla Başlatma (`start.bat` / `start.sh`):**
  * Windows kullanıcıları `start.bat` dosyasına çift tıklayarak Python sanal ortamını ve kütüphaneleri otomatik kurup tarayıcıyı başlatabilir.
* **🎯 Akıllı Etkinlik Algılama & Eşleştirme Motoru:**
  * Bybit V5 ve OKX V5 API'lerinden emir dolum geçmişinizi (`fills / execution list`) çeker.
  * Takibe aldığınız etkinliklerle (coin, tarih aralığı, piyasa türü) otomatik eşleştirir.
  * Kasılan hacmi, ödenen kesin komisyonu (fee) ve tahta alış-satış farkından (spread/slippage) kaynaklanan makas maliyetini kuruşu kuruşuna hesaplar.
* **💰 Otomatik Komisyon İadesi (Rebate / Cashback) Hesaplama:**
  * **Bybit Alpha:** Fix **Binde 3** iade ($3 / $1.000 hacim).
  * **Bybit Spot / Futures:** Ortalama **%55.00** iade.
  * **OKX:** Ortalama **%47.50** iade.
  * İadeler düşülerek cebinizden fiilen çıkan **Net Total Maliyet** hesaplanır.
* **📊 Excel Canlı Senkronizasyon:**
  * Elde edilen verileri doğrudan masaüstündeki **`bybit-okx_maliyet.xlsx`** dosyasındaki ilgili sayfaya (`Bybit Maliyetleri` veya `OKX Maliyetleri`) yazar veya devam eden etkinliği günceller.
  * Formülleri, hücre stillerini ve üst KPI dashboard'unu korur.
* **🤖 Yapay Zekâ (Gemini AI) Entegrasyonu:**
  * Telegram veya duyuru kanallarından kopyaladığınız etkinlik metinlerini tek tıkla analiz ederek coin, tarih ve tür bilgilerini forma otomatik doldurur.

---

## 🛠️ Hızlı Kurulum ve Çalıştırma

### Yöntem 1: Windows Tek Tıkla Çalıştırma (En Kolay)
1. Bu projeyi GitHub'dan indirin (ZIP veya `git clone`).
2. Proje klasöründeki **`start.bat`** dosyasına çift tıklayın.
3. Gerekli sanal ortam otomatik kurulur ve tarayıcınızda `http://localhost:8000` açılır.

### Yöntem 2: macOS / Linux
Terminalde proje dizinine gidip şu komutu verin:
```bash
chmod +x start.sh
./start.sh
```

### Yöntem 3: Manuel Python ile Çalıştırma
```bash
# 1. Sanal ortam oluşturun ve aktif edin
python -m venv .venv
source .venv/bin/activate  # Windows için: .venv\Scripts\activate

# 2. Gereksinimleri yükleyin
pip install -r requirements.txt

# 3. .env dosyanızı oluşturun
cp .env.example .env

# 4. Sunucuyu başlatın
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Tarayıcınızda **`http://localhost:8000`** adresine gidin.

---

## 🔑 API Anahtarları Nasıl Alınır?

1. **Bybit:**
   * Bybit hesabınıza giriş yapın ➔ **Profil ➔ API Yönetimi**.
   * Yeni API Key oluşturun.
   * Tür: **Sistem Tarafından Oluşturulan API Anahtarı**.
   * Yetkiler: **YALNIZCA "Sadece Okuma" (Read-Only)** işaretleyin.
   * İzinler: **Emirler (Orders) & İşlemler (Trade History)**.
2. **OKX:**
   * OKX hesabınıza giriş yapın ➔ **Profil ➔ API Anahtarları**.
   * Yeni API Key oluşturun.
   * İzin: **Sadece Okuma (Read-Only)**.
   * Passphrase belirleyin ve bir kenara not edin.

### ⚙️ API Anahtarlarını Sisteme Girme

Aldığınız API bilgilerini sisteme iki şekilde girebilirsiniz:

* **Yöntem 1 (Web Arayüzü - En Kolay):** Projeyi çalıştırıp `http://localhost:8000` adresine girdikten sonra sağ üst menüdeki **Ayarlar (Settings) ⚙️** butonuna tıklayın. Açılan pencerede ilgili borsaların alanlarına oluşturduğunuz API anahtarlarını yapıştırıp "Kaydet" demeniz yeterlidir.
* **Yöntem 2 (.env Dosyası ile):** Proje klasöründeki `.env.example` dosyasının adını `.env` olarak değiştirin ve içini herhangi bir metin düzenleyiciyle (Not Defteri vb.) açıp anahtarlarınızı oraya doğrudan yazıp kaydedin.

---

## 📁 Proje Dizin Yapısı

```
├── start.bat                 # Windows tek tıkla başlatıcı
├── start.sh                  # macOS/Linux tek tıkla başlatıcı
├── requirements.txt          # Python bağımlılıkları
├── .env.example              # Ortam değişkenleri şablonu
├── bybit-okx_maliyet.xlsx    # Profesyonel Excel tablosu
├── app/
│   ├── main.py               # FastAPI uygulaması & API rotaları
│   ├── config.py             # .env ve ayar yöneticisi
│   ├── static/               # Web arayüzü (HTML, CSS, JS)
│   ├── core/
│   │   ├── bybit_client.py   # Bybit V5 REST API istemcisi
│   │   ├── okx_client.py     # OKX V5 REST API istemcisi
│   │   ├── detector.py       # Hacim, fee ve makas eşleştirme motoru
│   │   ├── excel_writer.py   # Excel'e otomatik yazıcı
│   │   └── ai_agent.py       # Gemini AI duyuru ayrıştırıcı
│   └── database/
│       ├── db.py             # SQLite veritabanı
│       └── models.py         # Etkinlik ve trade modelleri
```

---

## ⚖️ Lisans ve Sorumluluk Reddi
Bu yazılım yalnızca kişisel muhasebe ve maliyet analizi amacıyla geliştirilmiştir. Finansal veya yatırım tavsiyesi içermez.
