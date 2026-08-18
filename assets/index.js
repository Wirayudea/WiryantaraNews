// Extracted JavaScript from index.html
const API = window.location.origin;
let currentPage = 1;
let currentSource = '';
let searchTimeout = null;
let pollInterval = null;
let statsInterval = null;

async function ensureChartJsLoaded() {
  if (typeof Chart !== 'undefined') return true;
  const fallbackSources = [
    'https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.3/chart.umd.min.js'
  ];

  for (const src of fallbackSources) {
    try {
      await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.crossOrigin = 'anonymous';
        script.onload = () => resolve(true);
        script.onerror = () => reject(new Error(`Gagal memuat Chart.js dari ${src}`));
        document.head.appendChild(script);
      });
      if (typeof Chart !== 'undefined') return true;
    } catch (e) {
      console.warn(e);
    }
  }
  return false;
}

async function downloadTopicReport() {
  const windowDays = window._trendWindowDays || 30;
  const runId = window._currentTopicRunId;
  if (!runId) {
    alert('Tidak ada run topik aktif. Muat ulang dashboard topik terlebih dahulu.');
    return;
  }

  const url = `${API}/api/topics/report/pdf?run_id=${runId}&window_days=${windowDays}`;
  window.open(url, '_blank');
}

// ── VIEW SWITCHING ────────────────────────────────────────────
function switchView(v) {
  document.getElementById('viewArticles').style.display = v === 'articles' ? 'block' : 'none';
  document.getElementById('viewTopics').style.display = v === 'topics' ? 'block' : 'none';

  document.getElementById('viewLog').style.display = v === 'log' ? 'block' : 'none';
  document.getElementById('viewTopicLog').style.display = v === 'topiclog' ? 'block' : 'none';

  document.getElementById('navArticles').classList.toggle('active', v === 'articles');
  document.getElementById('navTopics').classList.toggle('active', v === 'topics');
  document.getElementById('navTopicLog').classList.toggle('active', v === 'topiclog');
  document.getElementById('navLog').classList.toggle('active', v === 'log');

  if (v === 'topics') loadTopicDashboard();
}

// ── ARTICLES ─────────────────────────────────────────────────
async function loadArticles(page = currentPage) {
  currentPage = page;
  const search = document.getElementById('searchInput').value;
  const sort = document.getElementById('sortSelect').value;

  const params = new URLSearchParams({ page, limit: 20, sort });
  if (search) params.append('search', search);
  if (currentSource) params.append('source', currentSource);

  try {
    const res = await fetch(`${API}/api/articles?${params}`);
    const data = await res.json();
    renderArticles(data);
  } catch (e) {
    console.error(e);
  }
}

function renderArticles(data) {
  const container = document.getElementById('articleList');
  document.getElementById('articlesCount').textContent = `${data.total.toLocaleString()} artikel`;

  if (data.articles.length === 0) {
    container.innerHTML = `
      <div class="article-row header-row">
        <div>Tanggal</div><div>Judul Berita</div><div>Sumber</div><div>Link</div>
      </div>
      <div class="empty-state">
        <div class="empty-icon">🔍</div>
        <div class="empty-text">Tidak ada berita ditemukan</div>
        <div class="empty-sub">Coba ubah filter atau mulai scraping</div>
      </div>`;
    document.getElementById('pagination').innerHTML = '';
    return;
  }

  const rows = data.articles.map(a => {
    const date = a.tanggal_publikasi !== 'Tidak Diketahui'
      ? new Date(a.tanggal_publikasi).toLocaleDateString('id-ID', {day:'2-digit',month:'short',year:'numeric'})
      : '—';
    const time = a.tanggal_publikasi !== 'Tidak Diketahui'
      ? new Date(a.tanggal_publikasi).toLocaleTimeString('id-ID', {hour:'2-digit',minute:'2-digit'})
      : '';
    const preview = a.preview ? a.preview.replace(/\n/g, ' ').trim() : '';
    const domain = a.link_url ? new URL(a.link_url).hostname.replace('www.','') : a.sumber;
    return `
      <div class="article-row" onclick="openModal(${a.id})">
        <div class="article-date">${date}<br>${time}</div>
        <div>
          <div class="article-title">${escHtml(a.judul_berita)}</div>
          <div class="article-preview">${escHtml(preview.substring(0,100))}${preview.length > 100 ? '…' : ''}</div>
        </div>
        <div><span class="article-source">${escHtml(a.sumber || '')}</span></div>
        <div>
          ${a.link_url ? `<a class="article-link" href="${a.link_url}" target="_blank" onclick="e=>e.stopPropagation()">${escHtml(domain)}</a>` : '—'}
        </div>
      </div>`;
  }).join('');

  container.innerHTML = `
    <div class="article-row header-row">
      <div>Tanggal</div><div>Judul Berita</div><div>Sumber</div><div>Link</div>
    </div>${rows}`;

  renderPagination(data);
}

function renderPagination(data) {
  const pg = document.getElementById('pagination');
  if (data.pages <= 1) { pg.innerHTML = ''; return; }

  let html = '';
  html += `<button class="page-btn" onclick="loadArticles(${currentPage-1})" ${currentPage===1?'disabled':''}>‹</button>`;

  const range = [];
  for (let i = Math.max(1, currentPage-2); i <= Math.min(data.pages, currentPage+2); i++) range.push(i);
  if (range[0] > 1) { html += `<button class="page-btn" onclick="loadArticles(1)">1</button>`; if (range[0] > 2) html += `<span style="padding:0 4px;font-family:var(--mono);font-size:0.7rem;color:var(--warm-gray)">…</span>`; }
  range.forEach(p => {
    html += `<button class="page-btn ${p===currentPage?'active':''}" onclick="loadArticles(${p})">${p}</button>`;
  });
  if (range[range.length-1] < data.pages) { if (range[range.length-1] < data.pages-1) html += `<span style="padding:0 4px;font-family:var(--mono);font-size:0.7rem;color:var(--warm-gray)">…</span>`; html += `<button class="page-btn" onclick="loadArticles(${data.pages})">${data.pages}</button>`; }
  html += `<button class="page-btn" onclick="loadArticles(${currentPage+1})" ${currentPage===data.pages?'disabled':''}>›</button>`;

  pg.innerHTML = html;
}

// ── FILTER ───────────────────────────────────────────────────
function filterSource(src) {
  currentSource = src;
  currentPage = 1;
  document.querySelectorAll('.source-item').forEach(el => {
    el.classList.toggle('active', el.dataset.src === src);
  });
  loadArticles();
}

function debounceSearch() {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => { currentPage = 1; loadArticles(); }, 350);
}

// ── STATS ────────────────────────────────────────────────────
async function loadStats() {
  try {
    const res = await fetch(`${API}/api/stats`);
    const data = await res.json();

    document.getElementById('statTotal').textContent = data.total_articles.toLocaleString();
    document.getElementById('statRecent').textContent = data.recent_24h.toLocaleString();
    document.getElementById('countAll').textContent = data.total_articles;

    // Source list
    const srcList = document.getElementById('sourceList');
    srcList.innerHTML = `<div class="source-item" data-src="" onclick="filterSource('')">
      <span>Semua Sumber</span>
      <span class="source-count" id="countAll">${data.total_articles}</span>
    </div>`;
    data.sources.forEach(s => {
      const div = document.createElement('div');
      div.className = 'source-item' + (currentSource === s.sumber ? ' active' : '');
      div.dataset.src = s.sumber;
      div.onclick = () => filterSource(s.sumber);
      div.innerHTML = `<span>${s.sumber}</span><span class="source-count">${s.c}</span>`;
      srcList.appendChild(div);
    });

    // Session info
    if (data.sessions.length > 0) {
      const sess = data.sessions[0];
      document.getElementById('sessionInfo').innerHTML = `
        <span>📅 ${sess.started_at || '—'}</span><br>
        <span>✅ ${sess.total_scraped} berita</span><br>
        <span>⏭️ ${sess.total_skipped} dilewati</span><br>
        <span>⏱ ${sess.duration_seconds}s</span>
      `;
    }

    // Ticker
    if (data.sources.length > 0) {
      const tickerItems = data.sources.map(s => `<span class="ticker-item">${s.sumber}: ${s.c} berita<span class="ticker-sep">◆</span></span>`).join('');
      document.getElementById('tickerInner').innerHTML = tickerItems + tickerItems;
    }
  } catch(e) {}
}

// ── SCRAPING ──────────────────────────────────────────────────
async function startScrape() {
  try {
    const res = await fetch(`${API}/api/scrape/start`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || 'Gagal memulai scraping');
      return;
    }
    setBtnState(true);
    startPolling();
  } catch(e) {
    alert('Gagal terhubung ke server');
  }
}

function startPolling() {
  clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`${API}/api/scrape/status`);
      const data = await res.json();
      updateScrapeUI(data);
      if (!data.is_running) {
        clearInterval(pollInterval);
        setBtnState(false);
        loadArticles();
        loadStats();
      }
    } catch(e) {}
  }, 1200);
}

function updateScrapeUI(data) {
  const badge = document.getElementById('statusBadge');
  const pct = data.total > 0 ? (data.progress / data.total * 100) : 0;

  document.getElementById('progressFill').style.width = pct + '%';
  document.getElementById('progressText').textContent = `${data.progress} / ${data.total}`;
  document.getElementById('progressSource').textContent = data.current_source || '';

  if (data.is_running) {
    badge.className = 'status-badge running';
    badge.textContent = 'SCRAPING';
    document.getElementById('progressWrap').classList.add('active');
  } else if (data.finished_at) {
    badge.className = 'status-badge done';
    badge.textContent = 'SELESAI';
  } else {
    badge.className = 'status-badge idle';
    badge.textContent = 'IDLE';
  }

  // Render logs
  const panel = document.getElementById('logPanel');
  if (data.log && data.log.length > 0) {
    panel.innerHTML = data.log.slice().reverse().map(l => `
      <div class="log-entry">
        <span class="log-time">${l.time}</span>
        <span class="log-msg ${l.level}">${escHtml(l.message)}</span>
      </div>`).join('');
  }
}

function setBtnState(running) {
  const btn = document.getElementById('btnScrape');
  btn.disabled = running;
  btn.innerHTML = running
    ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg> Sedang Scraping…`
    : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg> Mulai Scraping`;
  if (!running) document.getElementById('progressWrap').classList.remove('active');
}

async function clearLog() {
  document.getElementById('logPanel').innerHTML = `<div style="font-family:var(--mono);font-size:0.72rem;color:var(--warm-gray);text-align:center;padding:2rem;">Log dibersihkan.</div>`;
}

async function clearTopicLog() {
  document.getElementById('topicLogPanel').innerHTML = `<div style="font-family:var(--mono);font-size:0.72rem;color:var(--warm-gray);text-align:center;padding:2rem;">Log dibersihkan.</div>`;
}

async function clearArticles() {
  if (!confirm('Hapus semua artikel dari database?')) return;
  await fetch(`${API}/api/articles`, { method: 'DELETE' });
  loadArticles();
  loadStats();
}

async function uploadFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  try {
    const res = await fetch(`${API}/api/articles/upload`, {
      method: 'POST',
      body: form
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || 'Gagal upload file');
      return;
    }
    const data = await res.json();
    alert(`Upload berhasil: ${data.uploaded} item, ${data.saved} baru disimpan.`);
    loadArticles();
    loadStats();
  } catch (e) {
    console.error(e);
    alert('Gagal mengunggah file. Pastikan format CSV.');
  } finally {
    event.target.value = null;
  }
}

// ── TOPIC ANALYTICS ──────────────────────────────────────────
let topicPollInterval = null;
let trendChartInstance = null;
let topicSearchTimeout = null;
let allTopicItems = [];

async function startTopicAnalysis() {
  try {
    const res = await fetch(`${API}/api/topics/analyze`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || 'Gagal memulai analisis topik');
      return;
    }
    setTopicBtnState(true);
    startTopicPolling();
  } catch (e) {
    alert('Gagal terhubung ke server');
  }
}

function startTopicPolling() {
  clearInterval(topicPollInterval);
  topicPollInterval = setInterval(async () => {
    try {
      const res = await fetch(`${API}/api/topics/status`);
      const data = await res.json();
      updateTopicStatusUI(data);
      if (!data.is_running) {
        clearInterval(topicPollInterval);
        setTopicBtnState(false);
        if (!data.error) loadTopicDashboard();
      }
    } catch (e) {}
  }, 1500);
}

function updateTopicStatusUI(data) {
  const badge = document.getElementById('topicStatusBadge');
  document.getElementById('topicStage').textContent = data.stage || '';
  if (data.is_running) {
    badge.className = 'status-badge running';
    badge.textContent = 'MEMPROSES';
  } else if (data.error) {
    badge.className = 'status-badge';
    badge.style.borderColor = 'var(--accent)';
    badge.style.color = 'var(--accent)';
    badge.textContent = 'GAGAL';
    document.getElementById('topicStage').textContent = data.error;
  } else if (data.finished_at) {
    badge.className = 'status-badge done';
    badge.textContent = 'SELESAI';
  } else {
    badge.className = 'status-badge idle';
    badge.textContent = 'IDLE';
  }

  // Render topic logs into topicLogPanel (mirip updateScrapeUI)
  const tpanel = document.getElementById('topicLogPanel');
  if (data.log && data.log.length > 0) {
    tpanel.innerHTML = data.log.slice().reverse().map(l => `
      <div class="log-entry">
        <span class="log-time">${l.time}</span>
        <span class="log-msg ${l.level}">${escHtml(l.message)}</span>
      </div>`).join('');
  } else {
    tpanel.innerHTML = `<div style="font-family:var(--mono);font-size:0.72rem;color:var(--warm-gray);text-align:center;padding:1.5rem;">Belum ada log analisis topik. Jalankan analisis untuk melihat proses.</div>`;
  }
}

function setTopicBtnState(running) {
  const btn = document.getElementById('btnAnalyzeTopics');
  btn.disabled = running;
  btn.textContent = running ? 'Sedang Menganalisis…' : 'Jalankan Analisis Topik';
}

async function loadTopicDashboard() {
  try {
    const windowDays = window._trendWindowDays || 30;
    const statusRes = await fetch(`${API}/api/topics/status`);
    const status = await statusRes.json();
    updateTopicStatusUI(status);
    if (status.is_running) { setTopicBtnState(true); startTopicPolling(); }

    const topicsRes = await fetch(`${API}/api/topics?window_days=${windowDays}`);
    const allTopicsData = await topicsRes.json();
    window._currentTopicRunId = allTopicsData.run_id;

    if (!allTopicsData.run_id || allTopicsData.topics.length === 0) {
      document.getElementById('topicEmptyState').style.display = 'block';
      document.getElementById('topicResults').style.display = 'none';
      return;
    }

    document.getElementById('topicEmptyState').style.display = 'none';
    document.getElementById('topicResults').style.display = 'block';

    allTopicItems = allTopicsData.topics;
    renderTopicList(allTopicItems);

    const [trendingRes, wordcloudRes, recoRes, topicRes, metricsRes] = await Promise.all([
      fetch(`${API}/api/topics/trending?run_id=${allTopicsData.run_id}&window_days=${windowDays}`),
      fetch(`${API}/api/topics/wordcloud?run_id=${allTopicsData.run_id}&window_days=${windowDays}`),
      fetch(`${API}/api/topics/recommendations?run_id=${allTopicsData.run_id}&window_days=${windowDays}`),
      fetch(`${API}/api/topics?run_id=${allTopicsData.run_id}&window_days=${windowDays}`),
      fetch(`${API}/api/topics/metrics?run_id=${allTopicsData.run_id}&window_days=${windowDays}`),
    ]);

    try {
      const trendingData = trendingRes.ok ? await trendingRes.json() : { trending_topics: [], series: [] };
      console.debug('Trending data', trendingData);
      window._trendingDataCache = trendingData;
      const chartLoaded = await ensureChartJsLoaded();
      if (!chartLoaded) {
        throw new Error('Chart.js gagal dimuat');
      }
      renderTrendChart(trendingData, windowDays);
    } catch (e) {
      console.error('Trend chart error', e, { status: trendingRes.status, ok: trendingRes.ok });
      renderTrendChartError();
    }

    try {
      const wordcloudData = wordcloudRes.ok ? await wordcloudRes.json() : { words: [] };
      renderWordCloud(wordcloudData);
    } catch (e) {
      console.error('Word cloud error', e);
      renderWordCloudError();
    }

    try {
      const recoData = recoRes.ok ? await recoRes.json() : { recommendations: [] };
      renderRecommendations(recoData);
    } catch (e) {
      console.error('Recommendations error', e);
      renderRecommendationsError();
    }

    let topicData = { topics: [] };
    try {
      topicData = topicRes.ok ? await topicRes.json() : { topics: [] };
      renderTopicList(topicData.topics);
    } catch (e) {
      console.error('Topic list error', e);
      document.getElementById('topicListPanel').innerHTML = `<div style="font-family:var(--mono);font-size:0.75rem;color:var(--warm-gray);">Tidak dapat menampilkan daftar topik.</div>`;
    }

    let metricsData = { topic_diversity: null, avg_coherence: null, avg_diversity: null };
    try {
      metricsData = metricsRes.ok ? await metricsRes.json() : metricsData;
      renderTopicMetrics(metricsData);
    } catch (e) {
      console.error('Topic metrics error', e);
      renderTopicMetrics(metricsData);
    }

    renderQualityChart(metricsData, topicData.topics);
  } catch (e) {
    console.error('loadTopicDashboard', e);
    renderTrendChartError();
    renderWordCloudError();
    renderRecommendationsError();
  }
}

const TOPIC_CATEGORY_KEYWORDS = {
  all: [],

  // Hukum & Kriminal
  kriminal: [
    'kriminal', 'pidana', 'narkoba', 'pencurian', 'penipuan',
    'korupsi', 'kejahatan', 'polisi', 'penculikan', 'perampokan',
    'pembunuhan', 'kekerasan', 'penangkapan'
  ],
  hukum: [
    'hukum', 'pengadilan', 'sidang', 'hakim', 'putusan',
    'legal', 'advokat', 'peradilan', 'jaksa', 'terdakwa', 'vonis'
  ],

  // Pemerintahan & Ekonomi
  politik: [
    'politik', 'pemilu', 'partai', 'presiden', 'menteri',
    'dpr', 'pilkada', 'capres', 'legislatif', 'parlemen', 'kebijakan'
  ],
  ekonomi: [
    'ekonomi', 'bisnis', 'investasi', 'saham', 'rupiah',
    'inflasi', 'perdagangan', 'ekspor', 'impor', 'pajak', 'umkm', 'harga'
  ],

  // Sosial & Budaya
  sosial: [
    'sosial', 'masyarakat', 'komunitas', 'lingkungan', 'desa',
    'kesejahteraan', 'keluarga', 'budaya', 'gotong royong', 'kemiskinan'
  ],
  bencana: [
    'bencana', 'banjir', 'gempa', 'kebakaran', 'longsor',
    'korban', 'evakuasi', 'tsunami', 'erupsi', 'cuaca ekstrem'
  ],

  // Pendidikan & Kesehatan
  pendidikan: [
    'pendidikan', 'sekolah', 'mahasiswa', 'kampus', 'guru',
    'universitas', 'dosen', 'belajar', 'akademik', 'siswa', 'kurikulum'
  ],
  kesehatan: [
    'kesehatan', 'rumah sakit', 'dokter', 'penyakit', 'vaksin',
    'pandemi', 'obat', 'covid', 'gizi', 'puskesmas'
  ],

  // Gaya Hidup & Hiburan
  olahraga: [
    'olahraga', 'sepak bola', 'liga', 'atlet', 'pemain',
    'basket', 'badminton', 'tenis', 'medali', 'pertandingan', 'turnamen'
  ],
  hiburan: [
    'hiburan', 'artis', 'film', 'musik', 'selebriti',
    'konser', 'sinetron', 'aktor', 'aktris'
  ],
  otomotif: [
    'otomotif', 'mobil', 'motor', 'kendaraan',
    'lalu lintas', 'kecelakaan', 'jalan raya'
  ],

  // Teknologi & Global
  teknologi: [
    'teknologi', 'digital', 'internet', 'aplikasi',
    'startup', 'gadget', 'artificial intelligence', 'siber', 'inovasi'
  ],
  internasional: [
    'internasional', 'dunia', 'luar negeri', 'global', 'diplomatik'
  ]
};

function getTopicCategoryMatches(topic) {
  const text = [
    topic.label || '',
    Array.isArray(topic.keywords) ? topic.keywords.map(k => (typeof k === 'string' ? k : (k.word || ''))).join(' ') : '',
  ].join(' ').toLowerCase();

  return Object.entries(TOPIC_CATEGORY_KEYWORDS)
    .filter(([key]) => key !== 'all')
    .filter(([key, words]) => words.some(word => text.includes(word)))
    .map(([key]) => key);
}

function getFilteredTopicList(topics) {
  const categoryEl = document.getElementById('topicCategorySelect');
  const queryEl = document.getElementById('topicSearchInput');
  const selectedCategory = categoryEl ? categoryEl.value : 'all';
  const query = queryEl ? queryEl.value.trim().toLowerCase() : '';

  return (topics || []).filter(topic => {
    const label = (topic.label || '').toLowerCase();
    const keywordText = Array.isArray(topic.keywords)
      ? topic.keywords.map(k => (typeof k === 'string' ? k : (k.word || ''))).join(' ').toLowerCase()
      : '';
    const categoryMatches = selectedCategory === 'all' || getTopicCategoryMatches(topic).includes(selectedCategory);
    const searchMatches = !query || label.includes(query) || keywordText.includes(query) || String(topic.count || '').includes(query);
    return categoryMatches && searchMatches;
  });
}

function renderTopicList(topics) {
  const panel = document.getElementById('topicListPanel');
  const filteredTopics = getFilteredTopicList(topics || []);

  if (filteredTopics.length === 0) {
    const categoryEl = document.getElementById('topicCategorySelect');
    const selectedCategory = categoryEl ? categoryEl.value : 'all';
    const categoryText = selectedCategory === 'all' ? 'dengan pencarian' : `dalam kategori "${selectedCategory}"`;
    panel.innerHTML = `<div style="font-family:var(--mono);font-size:0.75rem;color:var(--warm-gray);">Tidak ada topik yang cocok ${categoryText}.</div>`;
    return;
  }

  // Sorting: respect user selection (trend or frequency)
  const sortEl = document.getElementById('topicSortSelect');
  const sortBy = sortEl ? sortEl.value : 'frequency';
  const sorted = filteredTopics.slice();
  if (sortBy === 'trend') {
    sorted.sort((a, b) => (b.trend_score || 0) - (a.trend_score || 0));
  } else if (sortBy === 'frequency') {
    sorted.sort((a, b) => (b.count || 0) - (a.count || 0));
  }

  panel.innerHTML = sorted.map(t => `
    <div class="topic-item" style="margin-bottom:1.25rem;border-bottom:1px solid var(--border);padding-bottom:0.85rem;">
      <div class="source-item" style="cursor:pointer;display:grid;grid-template-columns:1fr auto;gap:0.5rem;align-items:center;" onclick="toggleTopicArticles(${t.topic_id})">
        <div>
          <div>${escHtml(t.label)} <span style="color:var(--warm-gray);">(${t.count} berita)</span></div>
          <div style="font-family:var(--mono);font-size:0.7rem;color:var(--warm-gray);margin-top:0.25rem;">
            Koherensi: ${t.coherence !== null ? t.coherence.toFixed(2) : '–'} · Diversitas: ${t.diversity !== null ? t.diversity.toFixed(2) : '–'}
          </div>
        </div>
        <span class="source-count" style="background:${t.trend_score > 0 ? 'var(--green)' : 'var(--warm-gray)'};">
          ${t.trend_score > 0 ? '▲' : '–'} ${t.trend_score.toFixed(1)}
        </span>
      </div>
      <div id="topicArticles_${t.topic_id}" class="topic-article-list" style="display:none;margin-top:0.85rem;padding-top:0.75rem;border-top:1px solid var(--border);"></div>
    </div>`).join('');
}

function debounceTopicSearch() {
  clearTimeout(topicSearchTimeout);
  topicSearchTimeout = setTimeout(() => {
    renderTopicList(allTopicItems || []);
  }, 200);
}

async function toggleTopicArticles(topicId) {
  const container = document.getElementById(`topicArticles_${topicId}`);
  if (!container) return;

  const isVisible = container.style.display === 'block';
  if (isVisible) {
    container.style.display = 'none';
    return;
  }

  const windowDays = window._trendWindowDays || 30;
  const runId = window._currentTopicRunId;
  container.style.display = 'block';
  container.innerHTML = `<div style="font-family:var(--mono);font-size:0.9rem;color:var(--warm-gray);">Memuat judul berita…</div>`;

  try {
    const res = await fetch(`${API}/api/topics/${topicId}/articles?run_id=${runId}&window_days=${windowDays}`);
    if (!res.ok) throw new Error('Gagal memuat data');
    const data = await res.json();
    if (!data.articles || data.articles.length === 0) {
      container.innerHTML = `<div style="font-family:var(--mono);font-size:0.9rem;color:var(--warm-gray);">Tidak ada judul berita terkait topik ini dalam periode terpilih.</div>`;
      return;
    }

    container.innerHTML = data.articles.map(a => `
      <div style="padding:0.65rem 0;border-bottom:1px solid rgba(0,0,0,0.04);">
        <a href="${escHtml(a.link_url || '#')}" target="_blank" style="color:var(--ink);font-weight:700;text-decoration:none;">${escHtml(a.judul_berita)}</a>
        <div style="font-family:var(--mono);font-size:0.78rem;color:var(--warm-gray);margin-top:0.25rem;">${a.sumber || 'Sumber tidak tersedia'} · ${a.tanggal_publikasi || 'Tanggal tidak tersedia'}</div>
      </div>
    `).join('');
  } catch (e) {
    console.error('toggleTopicArticles', e);
    container.innerHTML = `<div style="font-family:var(--mono);font-size:0.9rem;color:var(--warm-gray);">Gagal memuat judul berita.</div>`;
  }
}

function renderTopicMetrics(data) {
  const panel = document.getElementById('topicQualityPanel');
  if (!data || (data.topic_diversity === null && data.avg_coherence === null)) {
    panel.innerHTML = `
      <div style="font-family:var(--mono);font-size:0.75rem;color:var(--warm-gray);">
        Metode koherensi dan keanekaragaman topik belum tersedia.
      </div>`;
    return;
  }

  panel.innerHTML = `
    <div style="background:rgba(59,130,246,0.08);border:1px solid rgba(59,130,246,0.14);padding:0.85rem 1rem;border-radius:0.75rem;min-width:180px;">
      <div style="font-family:var(--mono);font-size:0.68rem;color:var(--warm-gray);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.35rem;">Rata-rata Diversitas Topik</div>
      <div style="font-size:1rem;font-weight:700;color:var(--ink);">${data.avg_diversity !== null ? data.avg_diversity.toFixed(3) : '–'}</div>
      <div style="font-family:var(--mono);font-size:0.72rem;color:var(--warm-gray);margin-top:0.25rem;">Per topik</div>
    </div>
    <div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.14);padding:0.85rem 1rem;border-radius:0.75rem;min-width:180px;">
      <div style="font-family:var(--mono);font-size:0.68rem;color:var(--warm-gray);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.35rem;">Rata-rata Koherensi</div>
      <div style="font-size:1rem;font-weight:700;color:var(--ink);">${data.avg_coherence !== null ? data.avg_coherence.toFixed(3) : '–'}</div>
      <div style="font-family:var(--mono);font-size:0.72rem;color:var(--warm-gray);margin-top:0.25rem;">Per topik</div>
    </div>`;
}

let qualityChartInstance = null;
function renderQualityChart(metrics, topics) {
  const canvas = document.getElementById('topicQualityChart');
  const wrapper = document.getElementById('topicQualityChartWrapper');
  if (!canvas || !wrapper) return;

  if (qualityChartInstance && typeof qualityChartInstance.destroy === 'function') {
    qualityChartInstance.destroy();
  }

  const topicPoints = topics
    .filter(t => t.coherence !== null && t.diversity !== null)
    .map(t => ({
      label: t.label || `Topik ${t.topic_id}`,
      coherence: t.coherence,
      diversity: t.diversity,
    }));

  if (!topicPoints || topicPoints.length === 0) {
    wrapper.innerHTML = `<div style="font-family:var(--mono);font-size:0.75rem;color:var(--warm-gray);">Data kualitas topik belum tersedia.</div>`;
    return;
  }

  const labels = topicPoints.map((item, index) => {
    const text = item.label.length > 18 ? item.label.slice(0, 18) + '…' : item.label;
    return `${index + 1}. ${text}`;
  });
  const coherenceValues = topicPoints.map(item => item.coherence);
  const diversityValues = topicPoints.map(item => item.diversity);

  wrapper.innerHTML = `<canvas id="topicQualityChart" style="display:block;width:100%;height:100%;"></canvas>`;
  const newCanvas = document.getElementById('topicQualityChart');
  const newCtx = newCanvas.getContext('2d');

  qualityChartInstance = new Chart(newCtx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Koherensi Topik',
          data: coherenceValues,
          borderColor: '#1a4d7a',
          backgroundColor: 'rgba(26,77,122,0.16)',
          tension: 0.3,
          fill: true,
          pointRadius: 4,
          yAxisID: 'y',
        },
        {
          label: 'Diversitas Topik',
          data: diversityValues,
          borderColor: '#d4a843',
          backgroundColor: 'rgba(212,168,67,0.12)',
          tension: 0.3,
          fill: true,
          pointRadius: 4,
          pointStyle: 'circle',
          pointBackgroundColor: '#d4a843',
          yAxisID: 'y',
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { font: { family: 'DM Mono', size: 10 } }
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              const val = context.parsed && typeof context.parsed.y === 'number' ? context.parsed.y : null;
              const label = context.dataset && context.dataset.label ? context.dataset.label + ': ' : '';
              if (val === null) return label + '–';
              const trimmed = Number(val.toFixed(3)).toString();
              return label + trimmed.replace('.', ',');
            }
          }
        }
      },
      scales: {
        x: {
          ticks: { font: { family: 'DM Mono', size: 9 }, autoSkip: true, maxTicksLimit: 12 },
        },
        y: {
          beginAtZero: true,
          max: 1.05,
          ticks: { font: { family: 'DM Mono', size: 9 } },
        },
      },
    },
  });
}

function renderTrendChart(data, days = (window._trendWindowDays || 30)) {
  const canvas = document.getElementById('trendChart');
  if (!canvas) {
    console.error('Trend chart canvas tidak ditemukan');
    return renderTrendChartError();
  }
  const ctx = canvas.getContext('2d');
  if (trendChartInstance && typeof trendChartInstance.destroy === 'function') {
    trendChartInstance.destroy();
  }

  if (typeof Chart === 'undefined') {
    console.error('Chart.js tidak tersedia di browser');
    return renderTrendChartError();
  }

  if (!data.series || data.series.length === 0 || !data.trending_topics || data.trending_topics.length === 0) {
    trendChartInstance = null;
    const parent = canvas.parentElement;
    parent.innerHTML = `<div style="font-family:var(--mono);font-size:0.75rem;color:var(--warm-gray);">Data tren tidak tersedia.</div>`;
    return;
  }

  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  const filteredSeries = (data.series || []).filter(s => {
    const ts = new Date(s.timestamp);
    return ts >= cutoff;
  });

  const labels = [...new Set(filteredSeries.map(s => s.timestamp.substring(0, 10)))].sort();
  const colors = ['#c8392b', '#1a4d7a', '#d4a843', '#2d7a4f', '#7a3f9a', '#0e0e0f'];

  const datasets = (data.trending_topics || []).map((t, i) => {
    const seriesForTopic = (filteredSeries || []).filter(s => s.topic_id === t.topic_id);
    const points = labels.map(l => {
      const match = seriesForTopic.find(s => s.timestamp.substring(0, 10) === l);
      return match ? match.frequency : 0;
    });
    return {
      label: t.label,
      data: points,
      borderColor: colors[i % colors.length],
      backgroundColor: colors[i % colors.length],
      tension: 0.3,
      fill: false,
    };
  });

  trendChartInstance = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { font: { family: 'DM Mono', size: 10 } } } },
      scales: {
        x: { ticks: { font: { family: 'DM Mono', size: 9 } } },
        y: { beginAtZero: true, ticks: { font: { family: 'DM Mono', size: 9 } } },
      },
    },
  });
}

function renderWordCloud(data) {
  const panel = document.getElementById('wordCloudPanel');
  panel.style.display = 'flex';
  panel.style.flexWrap = 'wrap';
  panel.style.alignContent = 'flex-start';
  panel.style.gap = '0.4rem 0.9rem';
  if (!data.words || data.words.length === 0) {
    panel.innerHTML = `<span style="font-family:var(--mono);font-size:0.75rem;color:var(--warm-gray);">Belum ada data</span>`;
    return;
  }
  const weights = data.words.map(w => w.weight);
  const maxW = Math.max(...weights), minW = Math.min(...weights);
  const colors = ['#c8392b', '#1a4d7a', '#2d7a4f', '#d4a843', '#0e0e0f'];

  panel.innerHTML = data.words.map((w, i) => {
    const scale = maxW > minW ? (w.weight - minW) / (maxW - minW) : 0.5;
    const size = 0.75 + scale * 1.8;
    const color = colors[i % colors.length];
    return `<span style="font-family:var(--display);font-weight:700;font-size:${size}rem;color:${color};line-height:1;">${escHtml(w.word)}</span>`;
  }).join('');
}

function renderRecommendations(data) {
  const panel = document.getElementById('recoPanel');
  if (!data.recommendations || data.recommendations.length === 0) {
    panel.innerHTML = `<span style="font-family:var(--mono);font-size:0.75rem;color:var(--warm-gray);">Belum ada rekomendasi</span>`;
    return;
  }
  panel.innerHTML = data.recommendations.map(r => {
    const topicColor = getTopicColor(r.topic_label || 'topik');
    return `
      <div style="padding:0.6rem 0;border-bottom:1px solid var(--border);">
        <div class="article-title" style="font-size:0.82rem;">${r.link_url ? `<a href="${r.link_url}" target="_blank" style="color:var(--ink);text-decoration:none;">${escHtml(r.judul_berita)}</a>` : escHtml(r.judul_berita)}</div>
        <div style="display:flex;flex-wrap:wrap;gap:0.4rem;align-items:center;margin-top:0.35rem;">
          <span style="display:flex;align-items:center;gap:0.3rem;font-family:var(--mono);font-size:0.62rem;color:${topicColor.text};background:${topicColor.bg};border:1px solid ${topicColor.border};border-radius:0.55rem;padding:0.28rem 0.55rem;">
            <span style="width:0.55rem;height:0.55rem;border-radius:50%;background:${topicColor.dot};display:inline-block;flex-shrink:0;"></span>
            ${escHtml(r.topic_label)}
          </span>
          <span style="font-family:var(--mono);font-size:0.62rem;color:var(--warm-gray);">
            ${escHtml(r.sumber || '')}${r.tanggal_publikasi ? ` · ${escHtml(r.tanggal_publikasi)}` : ''}
          </span>
        </div>
      </div>`;
  }).join('');
}

function getTopicColor(label) {
  const colors = [
    { bg: '#f8e1e1', border: '#e0a5a5', dot: '#c8392b', text: '#6b1f1f' },
    { bg: '#e7eff8', border: '#b5cfe4', dot: '#1a4d7a', text: '#243f5d' },
    { bg: '#eef6e9', border: '#bdd6b4', dot: '#2d7a4f', text: '#315c3f' },
    { bg: '#f8f1e3', border: '#d7bf8d', dot: '#d4a843', text: '#6d562d' },
    { bg: '#f3edf8', border: '#c4aed8', dot: '#7a3f9a', text: '#4d3561' },
    { bg: '#ecebeb', border: '#a8a5a5', dot: '#0e0e0f', text: '#2d2d2d' },
  ];
  let hash = 0;
  for (let i = 0; i < label.length; i++) {
    hash = (hash * 31 + label.charCodeAt(i)) % colors.length;
  }
  return colors[hash];
}

// Trend window control: set days and re-render chart using cached trending data
function setTrendWindow(days) {
  window._trendWindowDays = days;
  document.getElementById('trendBtn1').classList.toggle('active', days === 1);
  document.getElementById('trendBtn7').classList.toggle('active', days === 7);
  document.getElementById('trendBtn14').classList.toggle('active', days === 14);
  document.getElementById('trendBtn30').classList.toggle('active', days === 30);
  const label = document.getElementById('topicPeriodLabel');
  if (label) {
    label.textContent = `Periode: ${days} hari`;
  }
  loadTopicDashboard();
}

function renderTrendChartError() {
  const parent = document.getElementById('trendChart').parentElement;
  parent.innerHTML = `<div style="font-family:var(--mono);font-size:0.75rem;color:var(--warm-gray);">Grafik tren tidak dapat ditampilkan. Pastikan Chart.js tersedia di browser Anda.</div>`;
}

function renderWordCloudError() {
  const panel = document.getElementById('wordCloudPanel');
  panel.innerHTML = `<span style="font-family:var(--mono);font-size:0.75rem;color:var(--warm-gray);">Word cloud tidak dapat ditampilkan.</span>`;
}

function renderRecommendationsError() {
  const panel = document.getElementById('recoPanel');
  panel.innerHTML = `<span style="font-family:var(--mono);font-size:0.75rem;color:var(--warm-gray);">Rekomendasi tidak dapat ditampilkan.</span>`;
}

// ── MODAL ────────────────────────────────────────────────────
async function openModal(id) {
  try {
    const res = await fetch(`${API}/api/articles/${id}`);
    const a = await res.json();

    document.getElementById('modalTitle').textContent = a.judul_berita;
    document.getElementById('modalMeta').innerHTML = `
      <div class="modal-meta-item">📅 <strong>Publikasi:</strong> ${a.tanggal_publikasi || '—'}</div>
      <div class="modal-meta-item">🕐 <strong>Scraping:</strong> ${a.tanggal_scraping || '—'}</div>
      <div class="modal-meta-item">📰 <strong>Sumber:</strong> ${a.sumber || '—'}</div>
    `;

    const paras = (a.isi_berita || '').split('\n').filter(p => p.trim());
    const bodyHtml = paras.slice(0, 8).map(p => `<p>${escHtml(p)}</p>`).join('') +
      (paras.length > 8 ? `<p style="color:var(--warm-gray);font-style:italic;">… dan ${paras.length - 8} paragraf lagi</p>` : '') +
      (a.link_url ? `<a class="modal-link" href="${a.link_url}" target="_blank">Baca artikel lengkap ↗</a>` : '');

    document.getElementById('modalBody').innerHTML = bodyHtml;
    document.getElementById('modalOverlay').classList.add('open');
    document.body.style.overflow = 'hidden';
  } catch(e) {}
}

function closeModal(e) {
  if (e.target === document.getElementById('modalOverlay')) closeModalDirect();
}
function closeModalDirect() {
  document.getElementById('modalOverlay').classList.remove('open');
  document.body.style.overflow = '';
}

// ── UTILS ────────────────────────────────────────────────────
function escHtml(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── ESC KEY ──────────────────────────────────────────────────
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModalDirect(); });

// ── INIT ─────────────────────────────────────────────────────
(async function init() {
  await loadStats();
  await loadArticles();
  // Check if already running
  const res = await fetch(`${API}/api/scrape/status`);
  const status = await res.json();
  if (status.is_running) {
    setBtnState(true);
    startPolling();
  }
  statsInterval = setInterval(loadStats, 30000);
})();
