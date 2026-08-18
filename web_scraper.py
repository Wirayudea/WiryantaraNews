import requests
from bs4 import BeautifulSoup
from newspaper import Article
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

CUTOFF_DAYS = 7
MAX_WORKERS = 5
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}
SKIP_KEYWORDS = ['/tag/', '/category/', '/kanal/', '/foto/', '/video/', '/indeks/', '/about/', '/contact/']


def parse_date_from_soup(soup):
    date_metas = [
        {'property': 'article:published_time'},
        {'name': 'publishdate'},
        {'name': 'date'},
        {'itemprop': 'datePublished'},
        {'name': 'pubdate'},
    ]
    for attrs in date_metas:
        tag = soup.find('meta', attrs=attrs)
        if tag and tag.get('content'):
            try:
                raw = tag['content']
                if '+' in raw[10:]:
                    raw = raw[:raw.rfind('+')]
                if raw.endswith('Z'):
                    raw = raw[:-1]
                for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                    try:
                        return datetime.strptime(raw[:19], fmt).replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
            except Exception:
                continue
    time_tag = soup.find('time')
    if time_tag:
        dt_str = time_tag.get('datetime') or time_tag.get_text()
        try:
            return datetime.fromisoformat(dt_str[:19]).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def get_article_links(tag_url, max_links=20, headers=None, log_fn=lambda m, level='info': None):
    headers = headers or HEADERS
    article_links = set()
    try:
        response = requests.get(tag_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        domain_key = tag_url.split('/')[2].replace('www.', '').replace('m.', '')

        if 'tvonenews.com' in domain_key:
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/berita/' in href:
                    if not href.startswith('http'):
                        href = 'https://www.tvonenews.com' + href
                    article_links.add(href)
                    if len(article_links) >= max_links:
                        break
        else:
            selectors = []
            if 'detik.com' in domain_key:
                selectors = ['div.list-content article a', 'article.mg-card a', 'a.media__link', 'h2.title a']
            elif 'suara.com' in domain_key:
                selectors = ['li.is-news a', 'div.post-card a', 'h3.post-title a', 'a.post-link', 'a.url']
            elif 'cnnindonesia.com' in domain_key:
                selectors = ['article a', 'div.list-berita a', 'h2.title a']

            generic_selectors = ['h2 a', 'h3 a', 'div.title a', 'article a', 'li a', 'a.post-title', 'div.item-content a']

            for selector in selectors + generic_selectors:
                for item in soup.select(selector):
                    link = item.get('href')
                    if link:
                        if not link.startswith('http'):
                            link = requests.compat.urljoin(tag_url, link)
                        if any(kw in link for kw in SKIP_KEYWORDS):
                            continue
                        if domain_key in link:
                            article_links.add(link)
                    if len(article_links) >= max_links:
                        break
                if len(article_links) >= max_links:
                    break
    except Exception as e:
        log_fn(f"❌ Error ambil link dari {tag_url}: {e}", "error")
    return list(article_links)[:max_links]


def scrape_single_article(link, headers=None, max_content_chars=100, log_fn=lambda m, level='info': None):
    headers = headers or HEADERS
    try:
        resp = requests.get(link, headers=headers, timeout=15)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, 'html.parser')
        pub_date = parse_date_from_soup(soup)

        cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
        if pub_date and pub_date < cutoff:
            return {'_skipped': True, 'reason': f"lama:{pub_date.strftime('%Y-%m-%d')}", 'link': link}

        article = Article(link, language='id')
        article.download(input_html=html)
        article.parse()

        if not pub_date and article.publish_date:
            pub_date = article.publish_date
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            if pub_date < cutoff:
                return {'_skipped': True, 'reason': 'lama', 'link': link}

        if not pub_date:
            return {'_skipped': True, 'reason': 'no_date', 'link': link}

        if article.title and len(article.text) > max_content_chars:
            return {
                '_skipped': False,
                'tanggal_scraping': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'tanggal_publikasi': pub_date.strftime('%Y-%m-%d %H:%M:%S'),
                'pub_date_obj': pub_date,
                'judul_berita': article.title,
                'isi_berita': article.text,
                'link_url': article.url,
            }
    except Exception as e:
        return {'_skipped': True, 'reason': f"error:{e}", 'link': link}
    return None
