from datetime import datetime, timezone, timedelta
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def scrape_youtube_channels(api_key, names, max_results=20, max_days=4, log_fn=lambda m, level='info': None):
    """Scrape recent videos from YouTube channels by name using YouTube Data API.
    Returns a list of dict entries compatible with the articles DB schema.
    """
    results = []
    batas_waktu = datetime.now(timezone.utc) - timedelta(days=max_days)
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
    except Exception as e:
        log_fn(f"❌ Gagal inisialisasi YouTube client: {e}", "error")
        return results

    for name in names:
        try:
            search_ch = youtube.search().list(q=name, type="channel", part="id,snippet", maxResults=1).execute()
            if not search_ch.get("items"):
                log_fn(f"ℹ️ Channel tidak ditemukan: {name}", "info")
                continue

            channel_id = search_ch["items"][0]["id"]["channelId"]
            actual_name = search_ch["items"][0]["snippet"]["title"]

            ch_info = youtube.channels().list(part="contentDetails", id=channel_id).execute()
            uploads_id = ch_info["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

            playlist_res = youtube.playlistItems().list(
                part="snippet",
                playlistId=uploads_id,
                maxResults=50
            ).execute()

            items = playlist_res.get("items", [])
            count = 0
            for item in items:
                if count >= max_results:
                    break
                snippet = item.get("snippet") or {}
                published_str = snippet.get("publishedAt")
                if not published_str:
                    continue
                try:
                    published_at = datetime.strptime(published_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                if published_at < batas_waktu:
                    continue

                video_id = snippet.get("resourceId", {}).get("videoId")
                if not video_id:
                    continue

                count += 1
                scrape_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                entry = {
                    "judul_berita": snippet.get("title"),
                    "isi_berita": snippet.get("description"),
                    "link_url": f"https://www.youtube.com/watch?v={video_id}",
                    "sumber": actual_name,
                    "tanggal_publikasi": published_at.strftime('%Y-%m-%d %H:%M:%S'),
                    "tanggal_scraping": scrape_time,
                }
                results.append(entry)

        except HttpError as e:
            log_fn(f"❌ YouTube API error untuk {name}: {e}", "error")
        except Exception as e:
            log_fn(f"❌ Error scraping YouTube untuk {name}: {e}", "error")

    return results
