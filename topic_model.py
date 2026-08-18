"""
Modul pemodelan topik menggunakan BERTopic berbasis embedding IndoBERT.

Fitur:
- build_topic_model()      : membangun pipeline BERTopic (embedding IndoBERT,
                              UMAP untuk reduksi dimensi, HDBSCAN untuk clustering)
- run_topic_modeling()     : menjalankan fit_transform pada kumpulan dokumen
                              dan (opsional) topics_over_time untuk analisis tren
- compute_trending_topics(): menghitung skor "sedang berkembang" tiap topik
                              berdasarkan perubahan frekuensi antar waktu
- get_topic_keywords()     : mengambil kata kunci representatif tiap topik

Model embedding default: firqaaa/indo-sentence-bert-base
(SentenceTransformer berbasis IndoBERT, 768 dimensi, mean pooling).
Bisa diganti lewat env var INDOBERT_MODEL_NAME bila ingin memakai varian lain,
misalnya denaya/indoSBERT-large.
"""

import os
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger("topic_model")

INDOBERT_MODEL_NAME = os.environ.get("INDOBERT_MODEL_NAME", "firqaaa/indo-sentence-bert-base")

_embedding_model = None


def get_embedding_model():
    """Lazy-load model SentenceTransformer berbasis IndoBERT (singleton)."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info(f"Memuat model embedding IndoBERT: {INDOBERT_MODEL_NAME}")
        _embedding_model = SentenceTransformer(INDOBERT_MODEL_NAME)
    return _embedding_model


def build_topic_model(min_topic_size=3, n_neighbors=15, nr_topics=None):
    """
    Membangun instance BERTopic dengan:
    - embedding_model : IndoBERT SentenceTransformer
    - vectorizer_model: CountVectorizer (unigram+bigram) untuk representasi
                        kata kunci topik (stopword sudah dibuang saat preprocessing)
    - umap_model      : reduksi dimensi sebelum clustering
    - hdbscan_model   : algoritma clustering berbasis densitas
    """
    from bertopic import BERTopic
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP
    from hdbscan import HDBSCAN

    embedding_model = get_embedding_model()
    vectorizer_model = CountVectorizer(ngram_range=(1, 2), min_df=1)

    n_neighbors = max(2, min(n_neighbors, 15))
    umap_model = UMAP(
        n_neighbors=n_neighbors,
        n_components=5,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=max(2, min_topic_size),
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=True,
    )

    topic_model = BERTopic(
        embedding_model=embedding_model,
        vectorizer_model=vectorizer_model,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        language="indonesian",
        calculate_probabilities=False,
        nr_topics=nr_topics,
        verbose=True,
    )
    return topic_model


def run_topic_modeling(docs, timestamps=None, min_topic_size=3, nr_topics=None, nr_bins=20):
    """
    Menjalankan pemodelan topik pada `docs` (list string, sudah dipreproses).

    timestamps: list datetime/str sepanjang docs (opsional), dipakai untuk
                menghitung topics_over_time.

    Return dict:
        topic_model         : instance BERTopic terlatih
        topics               : list topic id per dokumen (-1 = outlier)
        topic_info           : DataFrame ringkasan topik (Topic, Count, Name, Representation)
        topics_over_time     : DataFrame (Topic, Words, Frequency, Timestamp) jika timestamps diberikan
    """
    if len(docs) < 5:
        raise ValueError("Minimal 5 dokumen diperlukan untuk menjalankan pemodelan topik BERTopic")

    # min_topic_size tidak boleh lebih besar dari jumlah dokumen
    min_topic_size = max(2, min(min_topic_size, max(2, len(docs) // 5)))

    topic_model = build_topic_model(min_topic_size=min_topic_size, nr_topics=nr_topics)
    topics, probs = topic_model.fit_transform(docs)

    topic_info = topic_model.get_topic_info()

    result = {
        "topic_model": topic_model,
        "topics": topics,
        "topic_info": topic_info,
    }

    if timestamps is not None and len(timestamps) == len(docs):
        try:
            topics_over_time = topic_model.topics_over_time(
                docs, timestamps, nr_bins=nr_bins
            )
            result["topics_over_time"] = topics_over_time
        except Exception as e:
            logger.warning(f"Gagal menghitung topics_over_time: {e}")
            result["topics_over_time_error"] = str(e)

    return result


def get_topic_keywords(topic_model, topic_id, top_n=10):
    """Mengambil daftar (kata, bobot) representatif untuk satu topik."""
    words = topic_model.get_topic(topic_id)
    if not words:
        return []
    return [{"word": w, "weight": float(s)} for w, s in words[:top_n]]


def make_topic_label(keywords, max_words=4):
    """Membuat label singkat topik dari daftar kata kunci teratas."""
    if not keywords:
        return "Topik Tanpa Label"
    words = [k["word"] for k in keywords[:max_words]]
    return " / ".join(words)


def compute_trending_topics(topics_over_time_df):
    """
    Menghitung skor "sedang berkembang" (trend_score) untuk tiap topik
    berdasarkan perubahan frekuensi antara paruh awal dan paruh akhir
    rentang waktu topics_over_time.

    trend_score > 0  -> topik semakin sering muncul (naik daun / trending)
    trend_score <= 0 -> topik stagnan atau menurun

    Return: list of dict {topic, total_frequency, trend_score} terurut
            menurun berdasarkan trend_score.
    """
    if topics_over_time_df is None or len(topics_over_time_df) == 0:
        return []

    df = topics_over_time_df.copy()
    df = df[df["Topic"] != -1]
    df = df.sort_values("Timestamp")

    results = []
    for topic_id, group in df.groupby("Topic"):
        group = group.sort_values("Timestamp")
        n = len(group)
        total_freq = int(group["Frequency"].sum())
        if n < 2:
            trend_score = 0.0
        else:
            half = n // 2
            early = group["Frequency"].iloc[:max(half, 1)].mean()
            late = group["Frequency"].iloc[-max(n - half, 1):].mean()
            trend_score = float(late - early)

        results.append({
            "topic": int(topic_id),
            "total_frequency": total_freq,
            "trend_score": trend_score,
        })

    results.sort(key=lambda r: r["trend_score"], reverse=True)
    return results


def compute_topic_coherence(topic_model, docs, top_n=10, coherence='c_v'):
    """
    Menghitung topic coherence (default: c_v) per topik menggunakan gensim
    CoherenceModel.

    Dua perbaikan penting dari versi sebelumnya:

    1. Tokenisasi dokumen referensi sekarang memakai analyzer yang SAMA dengan
       `topic_model.vectorizer_model` (ngram_range=(1,2)), bukan `doc.split()`
       naif. Ini penting karena kata kunci topik BERTopic bisa berupa bigram
       (dua kata, mis. "harga minyak"). Bila dokumen referensi ditokenisasi
       per-kata-tunggal saja, token bigram tsb tidak akan pernah cocok di
       dictionary gensim, sehingga skor coherence topik yang kata kuncinya
       banyak mengandung bigram jadi bias/underestimated dibanding topik yang
       kata kuncinya unigram semua.
    2. topic_id sekarang dipasangkan dengan skor lewat daftar yang selalu
       sinkron (valid_topic_ids), bukan mengasumsikan index topic_ids selalu
       sejajar dengan topic_words. Sebelumnya, topik dengan kata kunci kosong
       (jarang terjadi, tapi mungkin) akan membuat seluruh pasangan topic_id
       ↔ skor bergeser untuk topik-topik setelahnya.

    Return: list of dict {topic_id, coherence} untuk tiap topik non-outlier.
    """
    from gensim.corpora import Dictionary
    from gensim.models import CoherenceModel

    analyzer = topic_model.vectorizer_model.build_analyzer()

    try:
        cleaned_docs = topic_model._preprocess_text([d for d in docs if d])
    except Exception:
        cleaned_docs = [d for d in docs if d]

    tokenized_docs = [analyzer(doc) for doc in cleaned_docs]
    tokenized_docs = [t for t in tokenized_docs if t]
    if not tokenized_docs:
        return []

    topic_info = topic_model.get_topic_info()
    topic_ids = [int(t) for t in topic_info[topic_info["Topic"] != -1]["Topic"].tolist()]

    valid_topic_ids = []
    topic_words = []
    for topic_id in topic_ids:
        words = [w for w, _ in (topic_model.get_topic(topic_id) or [])][:top_n]
        if words:
            valid_topic_ids.append(topic_id)
            topic_words.append(words)

    if not topic_words:
        return []

    dictionary = Dictionary(tokenized_docs)
    try:
        coherence_model = CoherenceModel(
            topics=topic_words,
            texts=tokenized_docs,
            dictionary=dictionary,
            coherence=coherence,
        )
        scores = coherence_model.get_coherence_per_topic()
    except Exception as e:
        logger.warning(f"Gagal menghitung topic coherence: {e}")
        return []

    return [
        {
            "topic_id": valid_topic_ids[i],
            "coherence": float(scores[i]) if scores[i] is not None else None,
        }
        for i in range(len(valid_topic_ids))
    ]


def compute_topic_diversity(topic_model, top_n=10):
    """
    Menghitung skor diversitas (keunikan) tiap topik dibandingkan topik lain.

    CATATAN PENTING (kenapa pendekatan lama menghasilkan nilai seragam ~0.9-1.0):
    Pendekatan sebelumnya mengukur diversity lewat overlap kata kunci (Jaccard
    similarity) antar top-N kata tiap topik. Masalahnya, BERTopic sudah
    menghasilkan kata kunci topik lewat c-TF-IDF, yang justru dirancang untuk
    MEMAKSIMALKAN keunikan kata antar topik. Akibatnya, dua topik nyaris tidak
    pernah berbagi kata kunci literal — avg_jaccard selalu mendekati 0, sehingga
    diversity = 1 - avg_jaccard selalu mendekati 1 untuk hampir semua topik.
    Metrik ini gagal membedakan topik yang sebenarnya masih berdekatan secara
    makna (mis. topik "ekonomi/inflasi" vs "bisnis/harga" bisa punya kata kunci
    yang sama sekali berbeda, padahal maknanya mirip).

    PERBAIKAN: diversity dihitung dari JARAK SEMANTIK antar embedding topik
    (cosine distance), menggunakan `topic_model.topic_embeddings_` yang sudah
    dihitung BERTopic dari embedding IndoBERT. Skor tiap topik = 1 - rata-rata
    cosine similarity terhadap seluruh topik lain. Ini menangkap kemiripan
    makna yang tidak tertangkap oleh overlap kata literal, sehingga hasilnya
    jauh lebih bervariasi dan lebih informatif dibanding pendekatan lama.

    Return: list of dict {topic_id, diversity} — 0 (mirip topik lain) s.d. 1 (unik).
    Fallback ke metode overlap-kata (Jaccard) bila embedding topik tidak tersedia.
    """
    topic_info = topic_model.get_topic_info()
    topic_ids = [int(t) for t in topic_info[topic_info["Topic"] != -1]["Topic"].tolist()]
    if not topic_ids:
        return []
    if len(topic_ids) == 1:
        return [{"topic_id": topic_ids[0], "diversity": 1.0}]

    embeddings = getattr(topic_model, "topic_embeddings_", None)
    if embeddings is not None:
        try:
            all_ids_sorted = sorted(topic_model.get_topics().keys())
            id_to_row = {tid: idx for idx, tid in enumerate(all_ids_sorted)}
            valid_ids = [tid for tid in topic_ids if tid in id_to_row and id_to_row[tid] < len(embeddings)]

            if valid_ids and len(valid_ids) > 1:
                vectors = np.array([embeddings[id_to_row[tid]] for tid in valid_ids], dtype=float)
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                norms[norms == 0] = 1e-9
                normalized = vectors / norms
                similarity_matrix = normalized @ normalized.T
                np.fill_diagonal(similarity_matrix, np.nan)

                diversities = []
                for i, tid in enumerate(valid_ids):
                    sims = similarity_matrix[i]
                    sims = sims[~np.isnan(sims)]
                    avg_sim = float(np.mean(sims)) if sims.size else 0.0
                    diversities.append({
                        "topic_id": tid,
                        "diversity": float(np.clip(1.0 - avg_sim, 0.0, 1.0)),
                    })
                return diversities
        except Exception as e:
            logger.warning(f"Gagal menghitung diversity berbasis embedding topik, fallback ke overlap kata: {e}")

    return _compute_topic_diversity_word_overlap(topic_model, topic_ids, top_n=top_n or 10)


def _compute_topic_diversity_word_overlap(topic_model, topic_ids, top_n=10):
    """
    Fallback lama: diversitas berbasis overlap kata kunci (Jaccard).
    Hanya dipakai bila `topic_embeddings_` tidak tersedia pada model BERTopic
    (mis. versi BERTopic lama). Lihat catatan di compute_topic_diversity()
    mengenai keterbatasan metode ini.
    """
    topic_terms = {}
    for topic_id in topic_ids:
        terms = topic_model.get_topic(topic_id) or []
        words = [w for w, _ in terms][:top_n]
        topic_terms[topic_id] = set(words)

    diversities = []
    for topic_id, words in topic_terms.items():
        if not words:
            diversities.append({"topic_id": topic_id, "diversity": 0.0})
            continue
        sims = []
        for other_id, other_words in topic_terms.items():
            if other_id == topic_id or not other_words:
                continue
            inter = len(words & other_words)
            union = len(words | other_words)
            sims.append(inter / union if union > 0 else 0.0)
        avg_sim = sum(sims) / len(sims) if sims else 0.0
        diversities.append({"topic_id": topic_id, "diversity": float(1.0 - avg_sim)})
    return diversities


def get_representative_article_indices(topics, topic_id, top_n=3):
    """Mengembalikan index dokumen yang termasuk topic_id tertentu (maks top_n)."""
    return [i for i, t in enumerate(topics) if t == topic_id][:top_n]