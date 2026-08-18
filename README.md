# NewsRadar — Scraper Berita Indonesia

Aplikasi web scraping berita dari sumber Indonesia dengan FastAPI, SQLite, dan tampilan modern serta pengimplementasian Algoritma BERTopic Untuk Pemodelan Trending Berita Online dengan visualisasi dasboard analytyc.

## Fitur

- 🔴 Web Scraping paralel dari 7 sumber (70 berita) + YouTube dari 6 channel (120 video) = total 190 berita
- YouTube scraping dijalankan bila `YOUTUBE_API_KEY` tersedia
- 📤 **Upload CSV** — tambah berita dari file CSV dengan normalisasi tanggal otomatis
- � **Export Berita CSV** — ekspor semua berita dalam format CSV yang sama dengan tanggal database
- 🧾 **Download Laporan PDF** — unduh ringkasan analitik topik sebagai laporan PDF
- 📋 Template CSV download untuk memudahkan format upload
- Penyimpanan ke SQLite otomatis
- 📊 Dashboard statistik real-time
- 🔍 Pencarian & filter berdasarkan sumber
- 🔎 Pencarian topik di daftar topik Analitik Topik
- 📝 Log scraping live
- 📱 Tampilan responsif
- 🧹 **Pra-pemrosesan teks otomatis** — case folding, data cleaning, tokenization,
  dan penghapusan stopword Bahasa Indonesia (PySastrawi + NLTK)
- 🧠 **Pemodelan topik BERTopic berbasis IndoBERT** — mengelompokkan artikel
  berdasarkan kemiripan semantik (embedding `firqaaa/indo-sentence-bert-base`)
- 📈 **Analisis tren topik** (`topics_over_time`) untuk mengidentifikasi topik
  yang sedang berkembang dari waktu ke waktu
- 📊 **Dashboard Analitik Topik** — grafik tren topik, word cloud kata kunci,
  dan rekomendasi judul berita populer, dapat diakses lewat tab "Analitik Topik"
- � **Metrik kualitas topik** — koherensi topik & diversitas istilah ditampilkan di dashboard
- �🕒 **Filter periode topik** — dukungan 1 hari, 7 hari, 14 hari, dan 30 hari untuk tren, wordcloud, dan rekomendasi
- 🧾 **Log analisis topik** — riwayat proses pemodelan topik ditampilkan langsung di UI

## Pemodelan Topik (BERTopic)

Buka tab **Analitik Topik** di aplikasi, lalu klik **"Jalankan Analisis Topik"**.
Proses ini akan:

1. Mengambil artikel 1 bulan terakhir dari tanggal publikasi berita untuk diproses
2. Melakukan pra-pemrosesan teks (case folding → cleaning → tokenisasi → stopword removal)
3. Menghitung embedding kalimat dengan IndoBERT dan mengelompokkan artikel menjadi topik dengan BERTopic (UMAP + HDBSCAN)
4. Menghitung `topics_over_time` untuk melihat topik mana yang frekuensinya meningkat (trending)
5. Menyajikan kontrol periode topik: 1 hari, 7 hari, 14 hari, dan 30 hari
6. Menyimpan hasil ke SQLite dan menampilkannya di dashboard (grafik tren, word cloud, rekomendasi judul, log analisis)

Model embedding default dapat diganti lewat environment variable `INDOBERT_MODEL_NAME`
(default: `firqaaa/indo-sentence-bert-base`).

> Catatan: proses ini mengunduh model IndoBERT (~400MB) saat pertama kali dijalankan,
> sehingga membutuhkan koneksi internet dan beberapa menit untuk run pertama.

## Cara Pakai Tab Analitik Topik

1. Buka aplikasi di browser dan klik tab **Analitik Topik**.
2. Tekan tombol **Jalankan Analisis Topik** untuk memulai pemodelan topik.
3. Setelah analisis selesai, pilih periode waktu:
   - `1 Hari`
   - `7 Hari`
   - `14 Hari`
   - `30 Hari`
4. Lihat hasil visual di dashboard:
   - grafik tren topik berdasarkan frekuensi per periode
   - word cloud kata kunci topik
   - rekomendasi judul berita populer per topik
   - log analisis topik untuk melihat langkah dan status proses

Contoh tampilan tab Analitik Topik akan menampilkan panel tren di sebelah kiri,
word cloud di tengah, rekomendasi judul di bawah, dan log analisis di panel kanan.

### Screenshot Example

Jika Anda ingin menambahkan screenshot sendiri:

1. Jalankan aplikasi dan buka tab **Analitik Topik**.
2. Pilih periode `1 Hari`, `7 Hari`, `14 Hari`, atau `30 Hari`.
3. Ambil screenshot halaman dengan fitur tren, word cloud, rekomendasi, dan log terlihat.
4. Simpan file gambar, misalnya `screenshots/topic-analytics.png`.
5. Masukkan gambar ke README dengan sintaks Markdown:

```md
![Analitik Topik](screenshots/topic-analytics.png)
```

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Jalankan server

```bash
cd WebBERTopicBARU
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Buka browser

Akses di: http://localhost:8000

## Sumber Berita

- detik.com/tag/viral
- suara.com/tag/viral
- cnnindonesia.com/tag/viral
- antaranews.com/tag/viral
- liputan6.com/tag/viral
- detik.com/tag/sumatera-selatan
- tvonenews.com/tag/viral

## API Endpoints

| Method | Endpoint                        | Deskripsi                                    |
| ------ | ------------------------------- | -------------------------------------------- |
| POST   | /api/scrape/start               | Mulai scraping                               |
| GET    | /api/scrape/status              | Status & log scraping                        |
| GET    | /api/articles                   | Daftar berita (pagination, search, filter)   |
| GET    | /api/articles/{id}              | Detail satu berita                           |
| POST   | /api/articles/upload            | Upload berita dari CSV                       |
| GET    | /api/articles/template/csv      | Download template CSV                        |
| GET    | /api/articles/export/csv        | Export semua berita ke CSV                   |
| GET    | /api/stats                      | Statistik database                           |
| DELETE | /api/articles                   | Hapus semua berita                           |
| GET    | /api/sources                    | Daftar sumber scraping                       |
| POST   | /api/topics/analyze             | Mulai pemodelan topik (BERTopic)             |
| GET    | /api/topics/status              | Status & log pemodelan topik                 |
| GET    | /api/topics                     | Daftar topik hasil pemodelan                 |
| GET    | /api/topics/{topic_id}          | Detail topik + artikel terkait               |
| GET    | /api/topics/{topic_id}/articles | Judul berita terkait per topik               |
| GET    | /api/topics/trending            | Data tren topik dari waktu ke waktu          |
| GET    | /api/topics/wordcloud           | Data word cloud (kata kunci topik)           |
| GET    | /api/topics/recommendations     | Rekomendasi judul berita populer             |
| GET    | /api/topics/metrics             | Metrik kualitas topik (koherensi/diversitas) |
| GET    | /api/topics/report/pdf          | Download laporan PDF analitik topik          |

## Struktur File

```
news-scraper/
├── main.py            # FastAPI backend + scraper & topic modeling logic
├── preprocessing.py    # Pra-pemrosesan teks (Sastrawi + NLTK)
├── topic_model.py      # Pemodelan topik BERTopic + IndoBERT
├── web_scraper.py
├── youtube_scraper.py
├── index.html         # Frontend UI (termasuk dashboard Analitik Topik)
├── requirements.txt
├── news.db            # SQLite database (auto-created)
└── README.md
```
