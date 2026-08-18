# Deploy ke Render.com - Panduan Lengkap

## Siapa yang Perlu Disiapkan

Saya sudah menyiapkan file-file berikut untuk deploy:

- ✅ `main.py` - Updated dengan PORT environment variable
- ✅ `requirements.txt` - Sudah ada, berisi semua dependencies
- ✅ `render.yaml` - Konfigurasi Render (auto-config)
- ✅ `.gitignore` - Exclude file yang tidak perlu di-push

## Langkah-Langkah Deploy

### 1. **Pastikan Punya GitHub Account**

- Jika belum, daftar di https://github.com

### 2. **Push Kode ke GitHub**

```bash
# Buka PowerShell di folder project
cd "c:\laragon\www\WebBERTopicBARU"

# Initialize git (jika belum)
git init

# Add semua file
git add .

# Commit
git commit -m "Initial commit: NewsRadar Topic Analyzer"

# Tambahkan remote (ganti USERNAME dan REPO_NAME)
git remote add origin https://github.com/USERNAME/newsradar.git

# Push ke GitHub
git branch -M main
git push -u origin main
```

### 3. **Daftar & Setup di Render.com**

1.  Buka https://render.com
2.  Klik "Sign Up" → pilih "GitHub"
3.  Authorize Render untuk akses GitHub Anda
4.  Klik "New +" → pilih "Web Service"
5.  Connect repository → pilih repo `newsradar` (atau nama Anda)
6.  Render akan auto-detect `render.yaml`

### 4. **Konfigurasi di Render Dashboard**

Pastikan setting ini sudah benar:

- **Name:** newsradar (atau nama lain)
- **Environment:** Python 3
- **Build Command:** _(akan auto-read dari render.yaml)_
- **Start Command:** _(akan auto-read dari render.yaml)_
- **Free Plan:** Checked (akan auto-sleep saat tidak dipakai)

### 5. **Deploy!**

Klik **"Deploy"** → tunggu ~3-5 menit untuk build selesai

Render akan:

- Install dependencies dari `requirements.txt`
- Download NLTK data untuk preprocessing
- Start aplikasi dengan uvicorn

### 6. **Akses Aplikasi**

Setelah deploy sukses, Render kasih URL seperti:

```
https://newsradar.onrender.com
```

Klik link tersebut untuk buka aplikasi!

---

## Troubleshooting

### ❌ Build Gagal - "ModuleNotFoundError"

**Solusi:** Pastikan semua dependencies ada di `requirements.txt`. Render akan install otomatis.

### ❌ App Timeout / 502 Error

**Penyebab:** Instance sedang build model BERTopic (lama, karena download embedding IndoBERT ~500MB)
**Solusi:** Tunggu ~5-10 menit pertama kali, biarkan build log jalan

### ❌ Database Hilang Setelah Restart

**Penyebab:** Render instance auto-restart, SQLite data tidak persist
**Solusi Kalau Butuh Persistent DB:**

- Upgrade ke PostgreSQL (bayar, minimal $12/bulan)
- Atau: Backup database ke cloud storage (S3, dll)
- Atau: Update database schema pakai PostgreSQL driver

### ❌ Static Files (CSS/JS) 404

**Solusi:** Pastikan folder `assets/` dengan file `styles.css` dan `index.js` sudah di-push ke GitHub

---

## Monitoring & Logs

Di Render Dashboard:

- **Logs** tab: Lihat live logs aplikasi
- **Metrics** tab: CPU, Memory, Request count
- **Events** tab: Deploy history

---

## Membuat Update Setelah Deploy

Setiap kali ada perubahan:

```bash
git add .
git commit -m "Update: deskripsi perubahan"
git push origin main
```

Render akan **otomatis** detect perubahan dan re-deploy!

---

## Catatan Penting

1. **Cold Start:** Pertama kali buka aplikasi bisa lambat (~10-20 detik) karena instance bangun dari sleep
2. **Free Plan Limitations:**
   - Max 0.5GB RAM
   - Max 0.5vCPU
   - Auto-sleep setelah 15 menit idle
   - Cocok untuk testing/demo, bukan production

3. **NLTK Data:** Build command sudah include download NLTK data untuk preprocessing Bahasa Indonesia

---

## Upgrade ke Paid (Opsional)

Kalau traffic naik dan perlu:

- Instance yang tidak auto-sleep
- PostgreSQL database
- Lebih banyak RAM/CPU

Render punya paid plans mulai dari $7/bulan.

---

**Butuh bantuan? Hubungi saya jika ada error di deployment steps!**
