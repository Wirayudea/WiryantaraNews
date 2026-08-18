"""
Modul pra-pemrosesan teks Bahasa Indonesia.

Tahapan:
1. Case folding      - menyamakan semua huruf menjadi huruf kecil
2. Data cleaning     - membuang URL, HTML tag, email, angka, tanda baca, dan
                       karakter non-alfabet lainnya
3. Tokenization      - memecah teks menjadi token/kata menggunakan NLTK
4. Stopword removal  - membuang kata umum (stopword) Bahasa Indonesia
                       menggunakan gabungan kamus PySastrawi dan NLTK

Modul ini didesain agar aman dipanggil berulang kali (idempotent) dan akan
otomatis mengunduh resource NLTK yang dibutuhkan (punkt, stopwords) bila
belum tersedia di environment saat runtime.
"""

import re
import logging

logger = logging.getLogger("preprocessing")

# ─── Setup NLTK ──────────────────────────────────────────────────────────────
import nltk


def _ensure_nltk_resource(resource_path, download_name):
    try:
        nltk.data.find(resource_path)
    except LookupError:
        try:
            nltk.download(download_name, quiet=True)
        except Exception as e:
            logger.warning(f"Gagal mengunduh resource NLTK '{download_name}': {e}")


_ensure_nltk_resource("tokenizers/punkt", "punkt")
_ensure_nltk_resource("tokenizers/punkt_tab", "punkt_tab")
_ensure_nltk_resource("corpora/stopwords", "stopwords")

from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords as nltk_stopwords

# ─── Setup Sastrawi ──────────────────────────────────────────────────────────
from Sastrawi.StopWordRemover.StopWordRemoverFactory import StopWordRemoverFactory
from Sastrawi.Stemmer.StemmerFactory import StemmerFactory

_stopword_factory = StopWordRemoverFactory()
_sastrawi_stopwords = set(_stopword_factory.get_stop_words())

try:
    _nltk_id_stopwords = set(nltk_stopwords.words("indonesian"))
except Exception:
    _nltk_id_stopwords = set()

# Stopword tambahan yang sering muncul pada artikel berita/YouTube namun
# tidak selalu tercakup di kamus baku (singkatan, sisa boilerplate, dsb).
CUSTOM_STOPWORDS = {
    "nya", "yg", "dgn", "utk", "dr", "tsb", "dll", "dst", "sih", "deh",
    "loh", "lho", "kok", "toh", "gitu", "gini", "kayak", "kaya", "banget",
    "baca", "juga", "video", "foto", "detikcom", "liputan", "antara",
    "kompas", "berita", "artikel", "halaman", "klik", "subscribe",
    "like", "comment", "share", "channel",
}

STOPWORDS = _sastrawi_stopwords | _nltk_id_stopwords | CUSTOM_STOPWORDS

# Stemmer Sastrawi bersifat opsional (lebih lambat). Dipakai hanya bila
# use_stemming=True dipanggil secara eksplisit, agar preprocessing default
# tetap cepat untuk ratusan dokumen.
_stemmer = None


def _get_stemmer():
    global _stemmer
    if _stemmer is None:
        _stemmer = StemmerFactory().create_stemmer()
    return _stemmer


# ─── Tahapan Preprocessing ───────────────────────────────────────────────────

def case_folding(text):
    """Menyamakan semua huruf menjadi huruf kecil."""
    if not text:
        return ""
    return text.lower()


def clean_text(text):
    """Membersihkan teks dari URL, tag HTML, email, angka, dan simbol."""
    if not text:
        return ""
    text = re.sub(r"http\S+|www\.\S+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\S+@\S+", " ", text)
    text = re.sub(r"[^a-zA-Z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text):
    """Memecah teks menjadi daftar token/kata."""
    if not text:
        return []
    try:
        return word_tokenize(text)
    except Exception:
        return text.split()


def remove_stopwords(tokens, min_len=3):
    """Membuang stopword dan token yang terlalu pendek."""
    return [t for t in tokens if t not in STOPWORDS and len(t) >= min_len]


def preprocess_text(raw_text, use_stemming=False, min_token_len=3):
    """
    Menjalankan seluruh pipeline preprocessing pada satu dokumen teks
    dan mengembalikan string yang sudah bersih (siap untuk embedding).
    """
    text = case_folding(raw_text)
    text = clean_text(text)
    tokens = tokenize(text)
    tokens = remove_stopwords(tokens, min_len=min_token_len)

    if use_stemming and tokens:
        stemmer = _get_stemmer()
        tokens = [stemmer.stem(t) for t in tokens]

    return " ".join(tokens)


def preprocess_batch(texts, use_stemming=False, min_token_len=3):
    """Menjalankan preprocess_text untuk sekumpulan dokumen sekaligus."""
    return [preprocess_text(t, use_stemming=use_stemming, min_token_len=min_token_len) for t in texts]


def word_frequencies(texts, top_n=100):
    """
    Menghitung frekuensi kata dari sekumpulan teks yang SUDAH dipreproses
    (dipakai untuk data word cloud).
    """
    from collections import Counter
    counter = Counter()
    for t in texts:
        if not t:
            continue
        counter.update(t.split())
    return counter.most_common(top_n)
