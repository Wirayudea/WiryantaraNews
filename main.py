from fastapi import FastAPI, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import csv
import io
import re
import sqlite3
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from datetime import datetime, timedelta, timezone
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import json
import os
from pathlib import Path
from web_scraper import get_article_links, scrape_single_article
from youtube_scraper import scrape_youtube_channels
from preprocessing import preprocess_batch, word_frequencies
from topic_model import (
    run_topic_modeling,
    get_topic_keywords,
    make_topic_label,
    compute_trending_topics,
    compute_topic_coherence,
    compute_topic_diversity,
)

app = FastAPI(title="News Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static assets (CSS/JS) from the assets/ folder next to this file
assets_dir = Path(__file__).resolve().parent / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

DB_PATH = "news.db"
scrape_status = {
    "is_running": False,
    "progress": 0,
    "total": 0,
    "current_source": "",
    "log": [],
    "started_at": None,
    "finished_at": None,
}
status_lock = threading.Lock()

topic_status = {
    "is_running": False,
    "stage": "",
    "log": [],
    "started_at": None,
    "finished_at": None,
    "error": None,
    "last_run_id": None,
}
topic_lock = threading.Lock()

# ─── Database ────────────────────────────────────────────────────────────────

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                judul_berita TEXT NOT NULL,
                isi_berita TEXT,
                link_url TEXT UNIQUE,
                sumber TEXT,
                tanggal_publikasi TEXT,
                tanggal_scraping TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scrape_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT,
                finished_at TEXT,
                total_scraped INTEGER DEFAULT 0,
                total_skipped INTEGER DEFAULT 0,
                duration_seconds REAL,
                sources TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS topic_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT,
                finished_at TEXT,
                num_docs INTEGER DEFAULT 0,
                num_topics INTEGER DEFAULT 0,
                params TEXT,
                topic_diversity REAL DEFAULT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                topic_id INTEGER,
                label TEXT,
                keywords TEXT,
                count INTEGER DEFAULT 0,
                trend_score REAL DEFAULT 0,
                coherence REAL DEFAULT NULL,
                diversity REAL DEFAULT NULL,
                FOREIGN KEY(run_id) REFERENCES topic_runs(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS article_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                article_id INTEGER,
                topic_id INTEGER,
                FOREIGN KEY(run_id) REFERENCES topic_runs(id),
                FOREIGN KEY(article_id) REFERENCES articles(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS topics_over_time (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                topic_id INTEGER,
                timestamp TEXT,
                frequency INTEGER,
                words TEXT,
                FOREIGN KEY(run_id) REFERENCES topic_runs(id)
            )
        """)
        conn.commit()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

init_db()


def migrate_db_schema():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(topic_runs)")
        topic_runs_cols = [row[1] for row in cursor.fetchall()]
        if "topic_diversity" not in topic_runs_cols:
            cursor.execute("ALTER TABLE topic_runs ADD COLUMN topic_diversity REAL DEFAULT NULL")

        cursor.execute("PRAGMA table_info(topics)")
        topics_cols = [row[1] for row in cursor.fetchall()]
        if "coherence" not in topics_cols:
            cursor.execute("ALTER TABLE topics ADD COLUMN coherence REAL DEFAULT NULL")
        if "diversity" not in topics_cols:
            cursor.execute("ALTER TABLE topics ADD COLUMN diversity REAL DEFAULT NULL")
        conn.commit()

migrate_db_schema()

# ─── Scraper Logic ───────────────────────────────────────────────────────────

MAX_WORKERS = 5

SOURCES = [
    {"url": "https://www.detik.com/tag/viral", "label": "Detik - Viral"},
    {"url": "https://www.suara.com/tag/viral", "label": "Suara - Viral"},
    {"url": "https://www.cnnindonesia.com/tag/viral", "label": "CNN Indonesia - Viral"},
    {"url": "https://m.antaranews.com/tag/viral", "label": "Antara - Viral"},
    {"url": "https://www.liputan6.com/tag/viral", "label": "Liputan6 - Viral"},
    {"url": "https://www.detik.com/tag/sumatera-selatan", "label": "Detik - Sumsel"},
    {"url": "https://www.tvonenews.com/tag/viral", "label": "TvOne - Viral"},
]

YOUTUBE_CHANNELS = [
    "detikcom", 
    "Suara.com", 
    "CNN Indonesia", 
    "ANTARA News", 
    "Liputan6", 
    "tvOne News"
]
YOUTUBE_MAX_RESULTS = 20
YOUTUBE_MAX_DAYS = 4
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "AIzaSyDAXrWY0RAyiIXsQY6JWKK6-_ZIFDKHU3A")


def add_log(message, level="info"):
    with status_lock:
        scrape_status["log"].append({
            "time": datetime.now().strftime('%H:%M:%S'),
            "message": message,
            "level": level
        })
        if len(scrape_status["log"]) > 200:
            scrape_status["log"] = scrape_status["log"][-200:]


def add_topic_log(message, level="info"):
    with topic_lock:
        topic_status["log"].append({
            "time": datetime.now().strftime('%H:%M:%S'),
            "message": message,
            "level": level
        })
        if len(topic_status["log"]) > 200:
            topic_status["log"] = topic_status["log"][-200:]

def normalize_header(value):
    return re.sub(r'[^a-z0-9]+', '_', value.strip().lower()) if value else ''


def parse_datetime(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    patterns = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
        '%d-%m-%Y %H:%M:%S',
        '%d-%m-%Y %H:%M',
        '%d/%m/%Y %H:%M:%S',
        '%d/%m/%Y %H:%M',
        '%m/%d/%Y %H:%M:%S',
        '%m/%d/%Y %H:%M',
        '%m/%d/%Y %I:%M:%S %p',
        '%m/%d/%Y %I:%M %p',
        '%d-%m-%Y',
        '%d/%m/%Y',
        '%d %b %Y %H.%M',
        '%d %B %Y %H.%M',
        '%d %b %Y %H:%M',
        '%d %B %Y %H:%M',
        '%d %b %Y',
        '%d %B %Y',
    ]
    for pattern in patterns:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue

    return None


def format_datetime(value):
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value)


def sql_window_filter(field, window_days):
    if window_days == 1:
        return f"datetime({field}) >= datetime('now', '-1 day')", []
    return f"date({field}) >= date('now', ?)", [f'-{window_days} days']


def parse_upload_rows(rows):
    articles = []
    for row in rows:
        if not row:
            continue
        entry = {normalize_header(k): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        if not entry.get('judul_berita') or not entry.get('tanggal_publikasi'):
            continue

        pub_date = parse_datetime(entry.get('tanggal_publikasi'))
        scrape_date = parse_datetime(entry.get('tanggal_scraping')) or datetime.now()

        articles.append({
            'judul_berita': entry.get('judul_berita'),
            'isi_berita': entry.get('isi_berita', ''),
            'link_url': entry.get('link_url', ''),
            'sumber': entry.get('sumber', 'Upload'),
            'tanggal_publikasi': format_datetime(pub_date) if pub_date else entry.get('tanggal_publikasi'),
            'tanggal_scraping': format_datetime(scrape_date),
            '_pub_date_obj': pub_date or datetime.min,
        })

    articles.sort(key=lambda x: x.get('_pub_date_obj', datetime.min), reverse=True)
    for article in articles:
        article.pop('_pub_date_obj', None)
    return articles


def parse_uploaded_file(upload_file: UploadFile):
    filename = upload_file.filename.lower()
    content = upload_file.file.read()
    if filename.endswith('.csv'):
        text = content.decode('utf-8-sig', errors='replace')
        reader = csv.DictReader(io.StringIO(text))
        return parse_upload_rows(reader)
    raise HTTPException(status_code=400, detail='Format file tidak didukung. Gunakan CSV.')


def run_scraper():
    global scrape_status
    with status_lock:
        scrape_status.update({
            "is_running": True, "progress": 0, "total": 0,
            "current_source": "", "log": [],
            "started_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "finished_at": None,
        })

    total_start = time.time()
    all_data = []
    total_scraped = 0
    total_skipped = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    total_units = len(SOURCES) + len(YOUTUBE_CHANNELS)
    with status_lock:
        scrape_status["total"] = total_units

    for i, source in enumerate(SOURCES):
        tag_url = source["url"]
        label = source["label"]

        with status_lock:
            scrape_status["current_source"] = label
            scrape_status["progress"] = i

        add_log(f"📰 Memproses: {label}", "info")

        links = get_article_links(tag_url, max_links=20, log_fn=add_log)
        add_log(f"  🔗 Ditemukan {len(links)} link potensial", "info")

        scraped_count = 0
        skipped_count = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_link = {executor.submit(scrape_single_article, link, None, 100, add_log): link for link in links}
            for future in as_completed(future_to_link):
                if scraped_count >= 10:
                    for f in future_to_link:
                        f.cancel()
                    break

                result = future.result()
                if result is None:
                    continue

                if result.get('_skipped'):
                    skipped_count += 1
                    reason = result.get('reason', '')
                    if reason.startswith('lama:'):
                        add_log(f"  ⏭️ Dilewati ({reason}): {result['link'][-50:]}", "skip")
                    elif reason.startswith('error:'):
                        add_log(f"  ❌ Error: {reason[6:][:80]}", "error")
                    continue

                domain = tag_url.split('/')[2].replace('www.', '').replace('m.', '')
                entry = {k: v for k, v in result.items() if not k.startswith('_') and k != 'pub_date_obj'}
                entry['sumber'] = domain
                all_data.append(entry)
                scraped_count += 1
                total_scraped += 1

                tgl = result['pub_date_obj'].strftime('%Y-%m-%d') if result.get('pub_date_obj') else '?'
                add_log(f"  ✅ [{scraped_count}/10] ({tgl}) {result['judul_berita'][:60]}...", "success")

        total_skipped += skipped_count
        with status_lock:
            scrape_status["progress"] = i + 1
        add_log(f"  📊 Berhasil: {scraped_count} | Dilewati: {skipped_count}", "info")

    # Save web results to DB
    saved = 0
    with get_db() as conn:
        for item in all_data:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO articles
                    (judul_berita, isi_berita, link_url, sumber, tanggal_publikasi, tanggal_scraping)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    item.get('judul_berita'), item.get('isi_berita'),
                    item.get('link_url'), item.get('sumber'),
                    item.get('tanggal_publikasi'), item.get('tanggal_scraping')
                ))
                if conn.execute("SELECT changes()").fetchone()[0]:
                    saved += 1
            except Exception:
                pass
        conn.commit()

    saved_yt = 0
    add_log(f"✅ Web selesai: {total_scraped} berita, {saved} baru disimpan ({time.time() - total_start:.1f}s)", "success")

    sources_run = [s["label"] for s in SOURCES]
    finished = None

    if YOUTUBE_API_KEY:
        try:
            add_log("🔗 Memulai scraping YouTube...", "info")
            with status_lock:
                scrape_status["current_source"] = "YouTube"
                scrape_status["progress"] = len(SOURCES)

            yt_items = scrape_youtube_channels(
                YOUTUBE_API_KEY,
                YOUTUBE_CHANNELS,
                max_results=YOUTUBE_MAX_RESULTS,
                max_days=YOUTUBE_MAX_DAYS,
                log_fn=add_log
            )

            if yt_items:
                total_scraped += len(yt_items)
                saved_yt = 0
                with get_db() as conn:
                    for idx, item in enumerate(yt_items, start=1):
                        try:
                            conn.execute("""
                                INSERT OR IGNORE INTO articles
                                (judul_berita, isi_berita, link_url, sumber, tanggal_publikasi, tanggal_scraping)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                                item.get('judul_berita'), item.get('isi_berita'),
                                item.get('link_url'), item.get('sumber'),
                                item.get('tanggal_publikasi'), item.get('tanggal_scraping')
                            ))
                            if conn.execute("SELECT changes()").fetchone()[0]:
                                saved_yt += 1
                                add_log(
                                    f"  ✅ [YouTube {idx}/{len(yt_items)}] {item.get('judul_berita')[:80]}",
                                    "success"
                                )
                            else:
                                add_log(
                                    f"  ⚠️ [YouTube {idx}/{len(yt_items)}] Sudah ada: {item.get('judul_berita')[:80]}",
                                    "info"
                                )
                        except Exception as e:
                            add_log(f"❌ Gagal simpan YouTube item: {e}", "error")
                    conn.commit()
                add_log(f"✅ YouTube: {len(yt_items)} item, {saved_yt} baru disimpan", "success")
            else:
                add_log("ℹ️ Tidak ditemukan video YouTube baru", "info")
        except Exception as e:
            add_log(f"❌ Error scraping YouTube: {e}", "error")
        finally:
            finished = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if "YouTube" not in sources_run:
                sources_run.append("YouTube")
    else:
        finished = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Record full scrape session after all work completes
    with get_db() as conn:
        conn.execute("""
            INSERT INTO scrape_sessions (started_at, finished_at, total_scraped, total_skipped, duration_seconds, sources)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            scrape_status["started_at"],
            finished,
            total_scraped, total_skipped,
            round(time.time() - total_start, 1),
            json.dumps(sources_run)
        ))
        conn.commit()

    with status_lock:
        scrape_status["is_running"] = False
        scrape_status["progress"] = total_units
        scrape_status["finished_at"] = finished

# ─── Topic Modeling (BERTopic + IndoBERT) ───────────────────────────────────

TOPIC_MIN_ARTICLES = 5


def run_topic_analysis(min_topic_size=3, limit_articles=None):
    """
    Background job:
    1. Ambil artikel dari DB (judul + isi)
    2. Preprocessing teks (case folding, cleaning, tokenization, stopword removal)
    3. Jalankan BERTopic (embedding IndoBERT) -> topik per artikel
    4. Hitung topics_over_time -> identifikasi topik yang sedang berkembang (trending)
    5. Simpan hasil ke DB (topic_runs, topics, article_topics, topics_over_time)
    """
    global topic_status
    with topic_lock:
        topic_status.update({
            "is_running": True, "stage": "Mengambil data artikel", "log": [],
            "started_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "finished_at": None, "error": None,
        })

    start_time = time.time()
    try:
        with get_db() as conn:
            total_available = conn.execute(
                "SELECT COUNT(*) FROM articles "
                "WHERE judul_berita IS NOT NULL AND length(judul_berita) > 5 "
                "AND date(tanggal_publikasi) >= date('now','-30 days')"
            ).fetchone()[0]
            if limit_articles is not None:
                rows = conn.execute(
                    "SELECT id, judul_berita, tanggal_publikasi "
                    "FROM articles WHERE judul_berita IS NOT NULL AND length(judul_berita) > 5 "
                    "AND date(tanggal_publikasi) >= date('now','-30 days') "
                    "ORDER BY tanggal_publikasi DESC LIMIT ?",
                    (limit_articles,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, judul_berita, tanggal_publikasi "
                    "FROM articles WHERE judul_berita IS NOT NULL AND length(judul_berita) > 5 "
                    "AND date(tanggal_publikasi) >= date('now','-30 days') "
                    "ORDER BY tanggal_publikasi DESC"
                ).fetchall()

        articles = [dict(r) for r in rows]
        log_message = f"📚 {len(articles)} artikel terbaru dari {total_available} artikel 1 bulan terakhir diambil dari database"
        if limit_articles is not None:
            log_message += f" (maks. {limit_articles})"
        add_topic_log(log_message, "info")

        if len(articles) < TOPIC_MIN_ARTICLES:
            raise ValueError(
                f"Minimal {TOPIC_MIN_ARTICLES} artikel diperlukan untuk pemodelan topik "
                f"(saat ini hanya {len(articles)}). Jalankan scraping atau upload data dulu."
            )

        with topic_lock:
            topic_status["stage"] = "Pra-pemrosesan judul berita (case folding, cleaning, tokenization, stopword removal)"
        add_topic_log("🧹 Menjalankan pra-pemrosesan judul berita (Sastrawi + NLTK)...", "info")

        raw_texts = [a['judul_berita'] for a in articles]
        docs = preprocess_batch(raw_texts)

        # Buang dokumen yang jadi kosong setelah dibersihkan
        valid = [(i, d) for i, d in enumerate(docs) if d and len(d.split()) >= 3]
        if len(valid) < TOPIC_MIN_ARTICLES:
            raise ValueError("Terlalu sedikit dokumen valid setelah preprocessing untuk pemodelan topik")

        valid_idx = [i for i, _ in valid]
        clean_docs = [d for _, d in valid]
        valid_articles = [articles[i] for i in valid_idx]
        timestamps = [
            parse_datetime(a["tanggal_publikasi"]) or datetime.now()
            for a in valid_articles
        ]

        add_topic_log(f"✅ {len(clean_docs)} dokumen siap dimodelkan", "success")

        with topic_lock:
            topic_status["stage"] = "Menjalankan BERTopic (embedding IndoBERT)"
        add_topic_log("🤖 Menghitung embedding IndoBERT & clustering topik (BERTopic)...", "info")

        result = run_topic_modeling(clean_docs, timestamps=timestamps, min_topic_size=min_topic_size)
        topic_model = result["topic_model"]
        topics = result["topics"]
        topic_info = result["topic_info"]

        num_topics = int((topic_info["Topic"] != -1).sum())
        add_topic_log(f"📊 {num_topics} topik ditemukan dari {len(clean_docs)} dokumen", "success")

        with topic_lock:
            topic_status["stage"] = "Menghitung tren topik dari waktu ke waktu"
        trending = []
        tot_df = result.get("topics_over_time")
        if tot_df is not None:
            trending = compute_trending_topics(tot_df)
            add_topic_log("📈 Analisis topics_over_time selesai", "success")
        else:
            add_topic_log("⚠️ topics_over_time tidak tersedia (rentang waktu data terlalu sempit)", "skip")

        trend_map = {t["topic"]: t["trend_score"] for t in trending}

        # ── Simpan ke DB ──────────────────────────────────────────────────
        with topic_lock:
            topic_status["stage"] = "Menyimpan hasil ke database"

        add_topic_log("🧠 Menghitung koherensi dan diversitas topik...", "info")
        topic_coherence = compute_topic_coherence(topic_model, clean_docs, top_n=10)
        topic_diversity = compute_topic_diversity(topic_model)
        coherence_map = {c["topic_id"]: c["coherence"] for c in topic_coherence}
        diversity_map = {d["topic_id"]: d["diversity"] for d in topic_diversity}
        avg_diversity = sum(d["diversity"] for d in topic_diversity) / len(topic_diversity) if topic_diversity else None
        add_topic_log(f"✅ Koherensi dihitung untuk {len(topic_coherence)} topik. Diversitas topik rata-rata: {avg_diversity:.3f}", "success")

        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO topic_runs (started_at, finished_at, num_docs, num_topics, params, topic_diversity) VALUES (?, ?, ?, ?, ?, ?)",
                (topic_status["started_at"], None, len(clean_docs), num_topics,
                 json.dumps({"min_topic_size": min_topic_size, "limit_articles": limit_articles}), avg_diversity)
            )
            run_id = cur.lastrowid

            for _, row in topic_info.iterrows():
                tid = int(row["Topic"])
                keywords = get_topic_keywords(topic_model, tid, top_n=10)
                label = make_topic_label(keywords) if tid != -1 else "Tidak Terkategori"
                conn.execute(
                    "INSERT INTO topics (run_id, topic_id, label, keywords, count, trend_score, coherence, diversity) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, tid, label, json.dumps(keywords), int(row["Count"]), trend_map.get(tid, 0.0), coherence_map.get(tid), diversity_map.get(tid))
                )

            for article, tid in zip(valid_articles, topics):
                conn.execute(
                    "INSERT INTO article_topics (run_id, article_id, topic_id) VALUES (?, ?, ?)",
                    (run_id, article["id"], int(tid))
                )

            if tot_df is not None:
                for _, row in tot_df.iterrows():
                    ts = row["Timestamp"]
                    ts_str = ts.strftime('%Y-%m-%d %H:%M:%S') if hasattr(ts, "strftime") else str(ts)
                    conn.execute(
                        "INSERT INTO topics_over_time (run_id, topic_id, timestamp, frequency, words) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (run_id, int(row["Topic"]), ts_str, int(row["Frequency"]), str(row.get("Words", "")))
                    )

            # Hanya simpan hasil dari 5 run terakhir agar DB tidak membengkak
            old_runs = conn.execute(
                "SELECT id FROM topic_runs WHERE id NOT IN "
                "(SELECT id FROM topic_runs ORDER BY id DESC LIMIT 5)"
            ).fetchall()
            for r in old_runs:
                conn.execute("DELETE FROM topics WHERE run_id = ?", (r["id"],))
                conn.execute("DELETE FROM article_topics WHERE run_id = ?", (r["id"],))
                conn.execute("DELETE FROM topics_over_time WHERE run_id = ?", (r["id"],))
                conn.execute("DELETE FROM topic_runs WHERE id = ?", (r["id"],))

            finished = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("UPDATE topic_runs SET finished_at = ? WHERE id = ?", (finished, run_id))
            conn.commit()

        add_topic_log(
            f"✅ Selesai: {num_topics} topik tersimpan ({time.time() - start_time:.1f}s)", "success"
        )
        with topic_lock:
            topic_status["last_run_id"] = run_id
            topic_status["finished_at"] = finished

    except Exception as e:
        add_topic_log(f"❌ Error: {e}", "error")
        with topic_lock:
            topic_status["error"] = str(e)
            topic_status["finished_at"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    finally:
        with topic_lock:
            topic_status["is_running"] = False
            topic_status["stage"] = "Selesai"


def _get_latest_run_id(conn):
    row = conn.execute("SELECT id FROM topic_runs ORDER BY id DESC LIMIT 1").fetchone()
    return row["id"] if row else None


# ─── API Routes ──────────────────────────────────────────────────────────────

@app.post("/api/scrape/start")
async def start_scrape(background_tasks: BackgroundTasks):
    with status_lock:
        if scrape_status["is_running"]:
            raise HTTPException(status_code=400, detail="Scraping sedang berjalan")
    background_tasks.add_task(run_scraper)
    return {"message": "Scraping dimulai"}

@app.get("/api/scrape/status")
async def get_status():
    with status_lock:
        return dict(scrape_status)

@app.get("/api/articles")
async def get_articles(
    page: int = 1,
    limit: int = 20,
    search: str = "",
    source: str = "",
    sort: str = "tanggal_publikasi"
):
    offset = (page - 1) * limit
    conditions = []
    params = []

    if search:
        conditions.append("(judul_berita LIKE ? OR isi_berita LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if source:
        conditions.append("sumber = ?")
        params.append(source)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sort_col = sort if sort in ["tanggal_publikasi", "tanggal_scraping", "sumber"] else "tanggal_publikasi"

    with get_db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM articles {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, judul_berita, link_url, sumber, tanggal_publikasi, tanggal_scraping, substr(isi_berita,1,200) as preview "
            f"FROM articles {where} ORDER BY {sort_col} DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()

    return {
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "articles": [dict(r) for r in rows]
    }

@app.get("/api/articles/{article_id}")
async def get_article(article_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Artikel tidak ditemukan")
    return dict(row)

@app.get("/api/stats")
async def get_stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        sources = conn.execute("SELECT sumber, COUNT(*) as c FROM articles GROUP BY sumber ORDER BY c DESC").fetchall()
        recent = conn.execute("SELECT COUNT(*) FROM articles WHERE tanggal_scraping >= date('now', '-1 day')").fetchone()[0]
        sessions = conn.execute("SELECT * FROM scrape_sessions ORDER BY id DESC LIMIT 5").fetchall()
        latest = conn.execute("SELECT tanggal_scraping FROM articles ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "total_articles": total,
        "recent_24h": recent,
        "sources": [dict(r) for r in sources],
        "sessions": [dict(r) for r in sessions],
        "last_scraped": latest[0] if latest else None
    }

@app.delete("/api/articles")
async def clear_articles():
    with get_db() as conn:
        conn.execute("DELETE FROM articles")
        conn.commit()
    return {"message": "Semua artikel dihapus"}

@app.post("/api/articles/upload")
async def upload_articles(file: UploadFile):
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail='Format file tidak didukung. Gunakan CSV.')

    articles = parse_uploaded_file(file)
    if not articles:
        raise HTTPException(status_code=400, detail='Tidak ada data valid yang ditemukan untuk diunggah.')

    saved = 0
    with get_db() as conn:
        for item in articles:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO articles
                    (judul_berita, isi_berita, link_url, sumber, tanggal_publikasi, tanggal_scraping)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    item['judul_berita'], item['isi_berita'],
                    item['link_url'], item['sumber'],
                    item['tanggal_publikasi'], item['tanggal_scraping']
                ))
                if conn.execute("SELECT changes()").fetchone()[0]:
                    saved += 1
            except Exception:
                continue
        conn.commit()

    add_log(f"✅ Upload: {len(articles)} item, {saved} baru disimpan", "success")
    return {"uploaded": len(articles), "saved": saved}

@app.get("/api/articles/template/csv")
async def get_upload_template_csv():
    path = Path(__file__).resolve().parent / 'upload_templates' / 'upload-template.csv'
    if not path.exists():
        raise HTTPException(status_code=404, detail='Template tidak ditemukan')
    return FileResponse(path, media_type='text/csv', filename='upload-template.csv')

@app.get("/api/articles/export/csv")
async def export_articles_csv():
    def format_db_date(value):
        if isinstance(value, datetime):
            formatted = value.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(value, str):
            parsed = parse_datetime(value)
            formatted = parsed.strftime('%Y-%m-%d %H:%M:%S') if parsed else value
        else:
            formatted = str(value) if value is not None else ''
        if formatted:
            return f'="{formatted}"'
        return ''

    def generate():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'id',
            'judul_berita',
            'isi_berita',
            'link_url',
            'sumber',
            'tanggal_publikasi',
            'tanggal_scraping',
            'created_at'
        ])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        with get_db() as conn:
            cursor = conn.execute(
                "SELECT id, judul_berita, isi_berita, link_url, sumber, tanggal_publikasi, tanggal_scraping, created_at "
                "FROM articles ORDER BY tanggal_publikasi DESC"
            )
            for row in cursor:
                writer.writerow([
                    row['id'],
                    row['judul_berita'],
                    row['isi_berita'],
                    row['link_url'],
                    row['sumber'],
                    format_db_date(row['tanggal_publikasi']),
                    format_db_date(row['tanggal_scraping']),
                    format_db_date(row['created_at']),
                ])
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

    headers = {'Content-Disposition': 'attachment; filename="articles_export.csv"'}
    return StreamingResponse(generate(), media_type='text/csv', headers=headers)

@app.get("/api/sources")
async def get_sources():
    return [{"url": s["url"], "label": s["label"]} for s in SOURCES]

@app.post("/api/topics/analyze")
async def start_topic_analysis(background_tasks: BackgroundTasks, min_topic_size: int = 3, limit_articles: int = None):
    with topic_lock:
        if topic_status["is_running"]:
            raise HTTPException(status_code=400, detail="Analisis topik sedang berjalan")
    background_tasks.add_task(run_topic_analysis, min_topic_size, limit_articles)
    return {"message": "Analisis topik dimulai"}


@app.get("/api/topics/status")
async def get_topic_status():
    with topic_lock:
        return dict(topic_status)


@app.get("/api/topics")
async def list_topics(run_id: int = None, window_days: int = None):
    with get_db() as conn:
        rid = run_id or _get_latest_run_id(conn)
        if rid is None:
            return {"run_id": None, "topics": []}

        if window_days is not None:
            date_filter, params = sql_window_filter('a.tanggal_publikasi', window_days)
            rows = conn.execute(
                "SELECT t.topic_id, t.label, t.keywords, COUNT(*) AS count, t.trend_score, t.coherence, t.diversity "
                "FROM article_topics at "
                "JOIN articles a ON a.id = at.article_id "
                "JOIN topics t ON t.run_id = at.run_id AND t.topic_id = at.topic_id "
                "WHERE at.run_id = ? AND at.topic_id != -1 "
                f"AND {date_filter} "
                "GROUP BY t.topic_id, t.label, t.keywords, t.trend_score, t.coherence, t.diversity "
                "ORDER BY count DESC",
                (rid, *params)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT topic_id, label, keywords, count, trend_score, coherence, diversity FROM topics "
                "WHERE run_id = ? AND topic_id != -1 ORDER BY count DESC",
                (rid,)
            ).fetchall()
    topics = []
    for r in rows:
        d = dict(r)
        d["keywords"] = json.loads(d["keywords"]) if d.get("keywords") else []
        d["coherence"] = float(d["coherence"]) if d.get("coherence") is not None else None
        d["diversity"] = float(d["diversity"]) if d.get("diversity") is not None else None
        topics.append(d)
    return {"run_id": rid, "topics": topics}


@app.get("/api/topics/{topic_id}/articles")
async def get_topic_articles(topic_id: int, run_id: int = None, window_days: int = None):
    with get_db() as conn:
        rid = run_id or _get_latest_run_id(conn)
        if rid is None:
            return {"run_id": None, "topic_id": topic_id, "articles": []}

        if window_days is not None:
            date_filter, params = sql_window_filter('a.tanggal_publikasi', window_days)
            rows = conn.execute(
                "SELECT a.id, a.judul_berita, a.link_url, a.sumber, a.tanggal_publikasi "
                "FROM article_topics at "
                "JOIN articles a ON a.id = at.article_id "
                "WHERE at.run_id = ? AND at.topic_id = ? " +
                f"AND {date_filter} "
                "ORDER BY a.tanggal_publikasi DESC",
                (rid, topic_id, *params)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT a.id, a.judul_berita, a.link_url, a.sumber, a.tanggal_publikasi "
                "FROM article_topics at "
                "JOIN articles a ON a.id = at.article_id "
                "WHERE at.run_id = ? AND at.topic_id = ? "
                "ORDER BY a.tanggal_publikasi DESC",
                (rid, topic_id)
            ).fetchall()

    return {
        "run_id": rid,
        "topic_id": topic_id,
        "articles": [dict(r) for r in rows],
    }


@app.get("/api/topics/metrics")
async def get_topic_metrics(run_id: int = None, window_days: int = None):
    """
    Mengembalikan metrik ringkasan topik.

    Bila `window_days` diberikan (1/7/14/30), rata-rata koherensi dan diversitas
    dihitung hanya dari topik yang muncul dalam jendela waktu tersebut.
    """
    with get_db() as conn:
        rid = run_id or _get_latest_run_id(conn)
        if rid is None:
            return {"run_id": None, "topic_diversity": None, "avg_coherence": None, "avg_diversity": None}

        run_row = conn.execute(
            "SELECT topic_diversity FROM topic_runs WHERE id = ?",
            (rid,)
        ).fetchone()

        if window_days is not None:
            # Ambil topik yang memiliki artikel dalam jendela waktu, lalu hitung rata-rata
            date_filter, params = sql_window_filter('a.tanggal_publikasi', window_days)
            topic_rows = conn.execute(
                "SELECT t.topic_id, t.coherence, t.diversity "
                "FROM article_topics at "
                "JOIN articles a ON a.id = at.article_id "
                "JOIN topics t ON t.run_id = at.run_id AND t.topic_id = at.topic_id "
                "WHERE at.run_id = ? AND at.topic_id != -1 " +
                f"AND {date_filter} "
                "GROUP BY t.topic_id, t.coherence, t.diversity",
                (rid, *params)
            ).fetchall()
            # Fallback: jika tidak ada data article_topics untuk window singkat, coba topics_over_time
            if not topic_rows and window_days == 1:
                timestamp_filter, ts_params = sql_window_filter('timestamp', window_days)
                topic_rows = conn.execute(
                    "SELECT t.topic_id, t.coherence, t.diversity "
                    "FROM topics_over_time tot "
                    "JOIN topics t ON t.run_id = tot.run_id AND t.topic_id = tot.topic_id "
                    "WHERE tot.run_id = ? AND tot.topic_id != -1 " +
                    f"AND {timestamp_filter} "
                    "GROUP BY t.topic_id, t.coherence, t.diversity",
                    (rid, *ts_params)
                ).fetchall()
        else:
            topic_rows = conn.execute(
                "SELECT coherence, diversity FROM topics WHERE run_id = ? AND topic_id != -1",
                (rid,)
            ).fetchall()

    coherences = [float(r["coherence"]) for r in topic_rows if r["coherence"] is not None]
    diversities = [float(r["diversity"]) for r in topic_rows if r["diversity"] is not None]
    avg_coherence = sum(coherences) / len(coherences) if coherences else None
    avg_diversity = sum(diversities) / len(diversities) if diversities else None
    return {
        "run_id": rid,
        "topic_diversity": float(run_row["topic_diversity"]) if run_row and run_row["topic_diversity"] is not None else None,
        "avg_coherence": avg_coherence,
        "avg_diversity": avg_diversity,
    }


@app.get("/api/topics/report/pdf")
async def get_topic_report_pdf(run_id: int = None, window_days: int = None):
    rid = run_id
    if rid is None:
        with get_db() as conn:
            rid = _get_latest_run_id(conn)
    if rid is None:
        raise HTTPException(status_code=404, detail='Tidak ada run topik tersedia.')

    topics_data = await list_topics(run_id=rid, window_days=window_days)
    metrics_data = await get_topic_metrics(run_id=rid, window_days=window_days)
    trending_data = await get_trending_topics(run_id=rid, window_days=window_days)
    reco_data = await get_recommended_titles(run_id=rid, window_days=window_days)
    wordcloud_data = await get_wordcloud_data(run_id=rid, window_days=window_days, top_n=30)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph('Laporan Analitik Topik', styles['Title']))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f'Tanggal laporan: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', styles['Normal']))
    story.append(Paragraph(f'Periode analisis: {window_days or "seluruh data"} hari', styles['Normal']))
    story.append(Paragraph(f'Run ID: {rid}', styles['Normal']))
    story.append(Spacer(1, 18))

    story.append(Paragraph('Ringkasan Metrik', styles['Heading2']))
    story.append(Spacer(1, 8))
    metric_rows = [
        ['Rata-rata Diversitas Topik', f"{metrics_data.get('avg_diversity'):.3f}" if metrics_data.get('avg_diversity') is not None else '–'],
        ['Rata-rata Koherensi', f"{metrics_data.get('avg_coherence'):.3f}" if metrics_data.get('avg_coherence') is not None else '–'],
        ['Jumlah Topik', str(len(topics_data.get('topics', [])))],
    ]
    metric_table = Table(metric_rows, colWidths=[10*cm, 6*cm])
    metric_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f4f4f4')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.gray),
    ]))
    story.append(metric_table)
    story.append(Spacer(1, 18))

    story.append(Paragraph('Topik Utama', styles['Heading2']))
    story.append(Spacer(1, 8))
    topic_rows = [[
        'Topik', 'Jumlah Berita', 'Koherensi', 'Diversitas', 'Trend'
    ]] + [
        [
            t.get('label') or f"Topik {t.get('topic_id')}",
            str(t.get('count', '–')),
            f"{t.get('coherence'):.2f}" if t.get('coherence') is not None else '–',
            f"{t.get('diversity'):.2f}" if t.get('diversity') is not None else '–',
            f"{t.get('trend_score'):.1f}" if t.get('trend_score') is not None else '–'
        ]
        for t in topics_data.get('topics', [])
    ]
    if len(topic_rows) == 1:
        topic_rows.append(['Tidak ada topik', '', '', '', ''])
    topic_table = Table(topic_rows, colWidths=[7*cm, 2.5*cm, 2*cm, 2*cm, 2*cm])
    topic_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f4f4f4')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.gray),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(topic_table)
    story.append(Spacer(1, 18))

    story.append(Paragraph('Topik Trending', styles['Heading2']))
    story.append(Spacer(1, 8))
    trending_rows = [[
        'Topik', 'Trend Score', 'Frekuensi'
    ]] + [
        [
            t.get('label') or f"Topik {t.get('topic_id')}",
            f"{t.get('trend_score'):.1f}" if t.get('trend_score') is not None else '–',
            str(t.get('window_frequency', '–'))
        ]
        for t in trending_data.get('trending_topics', [])
    ]
    if len(trending_rows) == 1:
        trending_rows.append(['Tidak ada data trending', '', ''])
    trending_table = Table(trending_rows, colWidths=[9*cm, 3*cm, 3*cm])
    trending_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f4f4f4')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.gray),
    ]))
    story.append(trending_table)
    story.append(Spacer(1, 18))

    story.append(Paragraph('Rekomendasi Judul Berita', styles['Heading2']))
    story.append(Spacer(1, 8))
    recommendations = reco_data.get('recommendations', [])
    if recommendations:
        for idx, item in enumerate(recommendations[:15], start=1):
            title = item.get('title') or item.get('judul') or item.get('judul_berita') or '–'
            meta = item.get('source') or item.get('sumber') or 'Sumber tidak tersedia'
            topic_label = item.get('topic_label') or item.get('label') or ''
            story.append(Paragraph(f'{idx}. {title}', styles['Normal']))
            story.append(Paragraph(f'<i>{meta} {topic_label}</i>', styles['Italic']))
            story.append(Spacer(1, 6))
    else:
        story.append(Paragraph('Tidak ada rekomendasi tersedia.', styles['Normal']))
    story.append(Spacer(1, 18))

    story.append(Paragraph('Kata Kunci Utama', styles['Heading2']))
    story.append(Spacer(1, 8))
    keywords = wordcloud_data.get('words', [])[:30]
    if keywords:
        for item in keywords:
            story.append(Paragraph(f'• {item.get("word")}: {round(item.get("weight", 0))}', styles['Normal']))
    else:
        story.append(Paragraph('Tidak ada kata kunci tersedia.', styles['Normal']))

    doc.build(story)
    buffer.seek(0)
    filename = f'laporan_analitik_topik_{datetime.now().strftime("%Y-%m-%d")}.pdf'
    headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
    return StreamingResponse(buffer, media_type='application/pdf', headers=headers)


@app.get("/api/topics/trending")
async def get_trending_topics(run_id: int = None, top_n: int = 6, window_days: int = None):
    with get_db() as conn:
        rid = run_id or _get_latest_run_id(conn)
        if rid is None:
            return {"run_id": None, "trending_topics": [], "series": []}

        if window_days is not None:
            timestamp_filter, params = sql_window_filter('tot.timestamp', window_days)
            rows = conn.execute(
                "SELECT t.topic_id, t.label, t.trend_score, SUM(tot.frequency) AS window_frequency "
                "FROM topics_over_time tot "
                "JOIN topics t ON t.run_id = tot.run_id AND t.topic_id = tot.topic_id "
                "WHERE tot.run_id = ? AND tot.topic_id != -1 "
                f"AND {timestamp_filter} "
                "GROUP BY t.topic_id, t.label, t.trend_score "
                "ORDER BY window_frequency DESC LIMIT ?",
                (rid, *params, top_n)
            ).fetchall()
            if not rows and window_days == 1:
                # fallback when no topics_over_time entries exist for last 1 day
                rows = conn.execute(
                    "SELECT t.topic_id, t.label, t.trend_score, COUNT(*) AS window_frequency "
                    "FROM article_topics at "
                    "JOIN articles a ON a.id = at.article_id "
                    "JOIN topics t ON t.run_id = at.run_id AND t.topic_id = at.topic_id "
                    "WHERE at.run_id = ? AND at.topic_id != -1 "
                    "AND datetime(a.tanggal_publikasi) >= datetime('now', '-1 day') "
                    "GROUP BY t.topic_id, t.label, t.trend_score "
                    "ORDER BY window_frequency DESC LIMIT ?",
                    (rid, top_n)
                ).fetchall()
        else:
            rows = conn.execute(
                "SELECT topic_id, label, trend_score, count FROM topics "
                "WHERE run_id = ? AND topic_id != -1 ORDER BY trend_score DESC LIMIT ?",
                (rid, top_n)
            ).fetchall()
        top_topics = [dict(r) for r in rows]
        top_ids = [r["topic_id"] for r in top_topics]

        series = []
        if top_ids:
            placeholders = ",".join("?" for _ in top_ids)
            if window_days is not None:
                timestamp_filter, params = sql_window_filter('timestamp', window_days)
                rows = conn.execute(
                    f"SELECT topic_id, timestamp, frequency FROM topics_over_time "
                    f"WHERE run_id = ? AND topic_id IN ({placeholders}) "
                    f"AND {timestamp_filter} ORDER BY timestamp",
                    [rid, *top_ids, *params]
                ).fetchall()
                if not rows and window_days == 1:
                    rows = conn.execute(
                        f"SELECT at.topic_id AS topic_id, date(a.tanggal_publikasi) AS timestamp, COUNT(*) AS frequency "
                        f"FROM article_topics at "
                        f"JOIN articles a ON a.id = at.article_id "
                        f"WHERE at.run_id = ? AND at.topic_id IN ({placeholders}) "
                        f"AND datetime(a.tanggal_publikasi) >= datetime('now', '-1 day') "
                        f"GROUP BY at.topic_id, date(a.tanggal_publikasi) "
                        f"ORDER BY timestamp",
                        [rid, *top_ids]
                    ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT topic_id, timestamp, frequency FROM topics_over_time "
                    f"WHERE run_id = ? AND topic_id IN ({placeholders}) ORDER BY timestamp",
                    [rid] + top_ids
                ).fetchall()
            series = [dict(r) for r in rows]

    return {
        "run_id": rid,
        "trending_topics": [dict(r) for r in top_topics],
        "series": series,
    }


@app.get("/api/topics/wordcloud")
async def get_wordcloud_data(run_id: int = None, topic_id: int = None, top_n: int = 60, window_days: int = None):
    """
    Data word cloud. Bila topic_id diberikan: kata kunci topik tersebut saja.
    Bila tidak: gabungan kata kunci dari seluruh topik pada run terbaru,
    berbobot jumlah artikel di tiap topik.
    """
    with get_db() as conn:
        rid = run_id or _get_latest_run_id(conn)
        if rid is None:
            return {"run_id": None, "words": []}

        if topic_id is not None:
            row = conn.execute(
                "SELECT keywords FROM topics WHERE run_id = ? AND topic_id = ?",
                (rid, topic_id)
            ).fetchone()
            words = json.loads(row["keywords"]) if row and row["keywords"] else []
            return {"run_id": rid, "topic_id": topic_id, "words": words[:top_n]}

        if window_days is not None:
            timestamp_filter, params = sql_window_filter('tot.timestamp', window_days)
            rows = conn.execute(
                "SELECT t.keywords, SUM(tot.frequency) AS window_frequency "
                "FROM topics_over_time tot "
                "JOIN topics t ON t.run_id = tot.run_id AND t.topic_id = tot.topic_id "
                "WHERE tot.run_id = ? AND tot.topic_id != -1 "
                f"AND {timestamp_filter} "
                "GROUP BY t.keywords "
                "ORDER BY window_frequency DESC",
                (rid, *params)
            ).fetchall()
            if not rows and window_days == 1:
                rows = conn.execute(
                    "SELECT t.keywords, COUNT(*) AS window_frequency "
                    "FROM article_topics at "
                    "JOIN articles a ON a.id = at.article_id "
                    "JOIN topics t ON t.run_id = at.run_id AND t.topic_id = at.topic_id "
                    "WHERE at.run_id = ? AND at.topic_id != -1 "
                    "AND datetime(a.tanggal_publikasi) >= datetime('now', '-1 day') "
                    "GROUP BY t.keywords "
                    "ORDER BY window_frequency DESC",
                    (rid,)
                ).fetchall()
        else:
            rows = conn.execute(
                "SELECT keywords, count FROM topics WHERE run_id = ? AND topic_id != -1",
                (rid,)
            ).fetchall()

    from collections import defaultdict
    combined = defaultdict(float)
    for r in rows:
        keywords = json.loads(r["keywords"]) if r["keywords"] else []
        row_keys = list(r.keys())
        weight_factor = max(
            1,
            r["count"] if "count" in row_keys else 0,
            r["window_frequency"] if "window_frequency" in row_keys else 0,
        )
        for kw in keywords:
            combined[kw["word"]] += kw["weight"] * weight_factor

    words = [{"word": w, "weight": s} for w, s in combined.items()]
    words.sort(key=lambda x: x["weight"], reverse=True)
    return {"run_id": rid, "topic_id": None, "words": words[:top_n]}


@app.get("/api/topics/recommendations")
async def get_recommended_titles(run_id: int = None, limit: int = 10, window_days: int = None):
    """
    Rekomendasi judul berita populer: diambil satu artikel teratas per topik
    dari topik-topik paling trending pada periode yang dipilih.
    """
    with get_db() as conn:
        rid = run_id or _get_latest_run_id(conn)
        if rid is None:
            return {"run_id": None, "recommendations": []}

        recommendations = []
        if window_days is not None:
            timestamp_filter, ts_params = sql_window_filter('tot.timestamp', window_days)
            topic_rows = conn.execute(
                """SELECT t.topic_id, t.label AS topic_label, SUM(tot.frequency) AS window_frequency
                   FROM topics_over_time tot
                   JOIN topics t ON t.run_id = tot.run_id AND t.topic_id = tot.topic_id
                   WHERE tot.run_id = ? AND tot.topic_id != -1
                     AND """ + timestamp_filter + """
                   GROUP BY t.topic_id, t.label
                   ORDER BY window_frequency DESC
                   LIMIT ?""",
                (rid, *ts_params, limit)
            ).fetchall()
            if not topic_rows and window_days == 1:
                topic_rows = conn.execute(
                    """SELECT t.topic_id, t.label AS topic_label, COUNT(*) AS window_frequency
                       FROM article_topics at
                       JOIN articles a ON a.id = at.article_id
                       JOIN topics t ON t.run_id = at.run_id AND t.topic_id = at.topic_id
                       WHERE at.run_id = ? AND at.topic_id != -1
                         AND datetime(a.tanggal_publikasi) >= datetime('now', '-1 day')
                       GROUP BY t.topic_id, t.label
                       ORDER BY window_frequency DESC
                       LIMIT ?""",
                    (rid, limit)
                ).fetchall()

            for topic in topic_rows:
                date_filter, date_params = sql_window_filter('a.tanggal_publikasi', window_days)
                article = conn.execute(
                    """SELECT a.id, a.judul_berita, a.link_url, a.sumber, a.tanggal_publikasi
                       FROM article_topics at
                       JOIN articles a ON a.id = at.article_id
                       WHERE at.run_id = ? AND at.topic_id = ?
                         AND """ + date_filter + """
                       ORDER BY a.tanggal_publikasi DESC
                       LIMIT 1""",
                    (rid, topic["topic_id"], *date_params)
                ).fetchone()
                if not article and window_days == 1:
                    article = conn.execute(
                        """SELECT a.id, a.judul_berita, a.link_url, a.sumber, a.tanggal_publikasi
                           FROM article_topics at
                           JOIN articles a ON a.id = at.article_id
                           WHERE at.run_id = ? AND at.topic_id = ?
                             AND datetime(a.tanggal_publikasi) >= datetime('now', '-1 day')
                           ORDER BY a.tanggal_publikasi DESC
                           LIMIT 1""",
                        (rid, topic["topic_id"])
                    ).fetchone()
                if article:
                    rec = dict(article)
                    rec["topic_id"] = topic["topic_id"]
                    rec["topic_label"] = topic["topic_label"]
                    rec["window_frequency"] = topic["window_frequency"]
                    recommendations.append(rec)
        else:
            topic_rows = conn.execute(
                """SELECT topic_id, label AS topic_label
                   FROM topics
                   WHERE run_id = ? AND topic_id != -1
                   ORDER BY trend_score DESC, count DESC
                   LIMIT ?""",
                (rid, limit)
            ).fetchall()

            for topic in topic_rows:
                article = conn.execute(
                    """SELECT a.id, a.judul_berita, a.link_url, a.sumber, a.tanggal_publikasi
                       FROM article_topics at
                       JOIN articles a ON a.id = at.article_id
                       WHERE at.run_id = ? AND at.topic_id = ?
                       ORDER BY a.tanggal_publikasi DESC
                       LIMIT 1""",
                    (rid, topic["topic_id"])
                ).fetchone()
                if article:
                    rec = dict(article)
                    rec["topic_id"] = topic["topic_id"]
                    rec["topic_label"] = topic["topic_label"]
                    recommendations.append(rec)

    return {"run_id": rid, "recommendations": recommendations}


@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = Path(__file__).resolve().parent / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    raise HTTPException(status_code=404, detail="index.html not found")

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
