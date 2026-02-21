import feedparser
import datetime
import pytz
import os
from dateutil import parser as date_parser
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from googletrans import Translator

# --- 設定與清單 ---
TW_TZ = pytz.timezone('Asia/Taipei')
translator = Translator()

# IT 新聞排除關鍵字黑名單
BLACKLIST = [
    "暗物質", "哈伯望遠鏡", "韋伯望遠鏡", "黑洞", "超新星", "銀河系", "天文", "太空探測",
    "關稅", "經貿", "外交", "政情", "碳排放", "氣候變遷", "考古", "恐龍", "疫苗"
]

FEEDS_TW = [
    "https://www.digitimes.com.tw/rss/news.xml", "https://technews.tw/feed/",
    "https://www.ithome.com.tw/rss", "https://www.bnext.com.tw/rss",
    "https://www.ctee.com.tw/rss/tech", "https://money.udn.com/rssfeed/news/1001/5591/1059?ch=money",
    "https://futurecity.cw.com.tw/rss", "https://www.managertoday.com.tw/rss",
    "https://www.cna.com.tw/cna2018/api/jsnews.aspx?type=ait", "https://www.cio.com.tw/feed/"
]

FEEDS_INTL = [
    "https://feeds.bloomberg.com/technology/news.rss", "https://www.ft.com/technology?format=rss",
    "https://www.wired.com/feed/rss", "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/partner/techmeme-full-article/rss.xml",
    "https://www.cnbc.com/id/19854910/device/rss/rss.html", "https://www.theinformation.com/feed",
    "https://feeds.arstechnica.com/arstechnica/index/", "https://www.bleepingcomputer.com/feed/",
    "https://www.androidauthority.com/feed/", "https://www.forbes.com/news/index.xml",
    "https://9to5google.com/feed/", "https://feeds.macrumors.com/MacRumors-All"
]

def fetch_data(urls):
    data_by_date = {}
    stats = {}
    now_utc = datetime.datetime.now(pytz.utc)
    limit_48h = now_utc - datetime.timedelta(hours=48)
    
    for url in urls:
        feed = feedparser.parse(url)
        s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
        stats[s_name] = 0
        for entry in feed.entries[:12]:
            try:
                # 排除過濾邏輯
                title_lower = entry.title.lower()
                if any(kw in title_lower for kw in BLACKLIST):
                    continue
                
                p_date = date_parser.parse(entry.published)
                if p_date.tzinfo is None: p_date = pytz.utc.localize(p_date)
                if p_date < limit_48h: continue
                p_date_tw = p_date.astimezone(TW_TZ)
                date_str = p_date_tw.strftime('%Y-%m-%d')
                
                author = entry.get('author', entry.get('author_detail', {}).get('name', ''))
                if not author and 'dc_creator' in entry: author = entry['dc_creator']
                
                data_by_date.setdefault(date_str, []).append({
                    'title': entry.title, 'link': entry.link, 'source': s_name,
                    'time': p_date_tw, 'author': author
                })
                stats[s_name] += 1
            except: continue
    return data_by_date, stats

def cluster_and_translate(daily_data, is_intl=False):
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    results = {}
    for d_str, news_list in daily_data.items():
        if not news_list: continue
        titles = [n['title'] for n in news_list]
        embeddings = model.encode(titles)
        clusters = DBSCAN(eps=0.42, min_samples=1, metric="cosine").fit_predict(embeddings)
        groups = {}
        for i, cid in enumerate(clusters):
            groups.setdefault(cid, []).append(news_list[i])
        for cid, articles in groups.items():
            articles.sort(key=lambda x: x['time'])
            if is_intl:
                try:
                    articles[0]['trans_title'] = translator.translate(articles[0]['title'], dest='zh-tw').text
                except: articles[0]['trans_title'] = articles[0]['title']
        results[d_str] = groups
    return results

def render_column(daily_clusters, title_prefix):
    html = f"<div class='river'><div class='river-title'>{title_prefix}</div>"
    sorted_dates = sorted(daily_clusters.keys(), reverse=True)
    for d_str in sorted_dates:
        html += f"<div class='date-header'>{d_str}</div>"
        sorted_groups = sorted(daily_clusters[d_str].values(), key=lambda x: x[0]['time'], reverse=True)
        for articles in sorted_groups:
            articles.sort(key=lambda x: x['time'])
            first = articles[0]
            latest_updates = sorted([a for a in articles[1:]], key=lambda x: x['time'], reverse=True)[:5]
            others = [a for a in articles if a not in [first] + latest_updates]
            
            display_title = first.get('trans_title', first['title'])
            safe_id = first['link'].replace('"', '&quot;')
            
            time_info = first['time'].strftime('%H:%M')
            author_info = f" by {first['author']}" if first['author'] else ""
            meta_info = f" — {first['source']} {time_info}{author_info}"
            
            html += f"<div class='story-block' data-id=\"{safe_id}\">"
            html += f"<div class='headline-wrapper'>"
            html += f"<span class='star-btn' onclick='toggleStar(\"{safe_id}\")'>★</span>"
            html += f"<a class='headline' href='{first['link']}'>{display_title} <span class='source-tag'>{meta_info}</span></a>"
            html += f"</div>"
            if 'trans_title' in first:
                html += f"<div class='original-title'>{first['title']}</div>"
            for up in latest_updates:
                up_title = up.get('trans_title', up['title'])
                u_author = f" by {up['author']}" if up['author'] else ""
                html += f"<a class='sub-link' href='{up['link']}'>↳ <span class='source-name'>{up['source']} ({up['time'].strftime('%H:%M')}){u_author}</span>: {up_title}</a>"
            if others:
                other_str = ", ".join([f"{o['source']}" for o in others[:12]])
                html += f"<div class='other-mentions'>Also: {other_str}</div>"
            html += "</div>"
    html += "</div>"
    return html

def main():
    tw_raw, tw_stats = fetch_data(FEEDS_TW)
    intl_raw, intl_stats = fetch_data(FEEDS_INTL)
    tw_clusters = cluster_and_translate(tw_raw, is_intl=False)
    intl_clusters = cluster_and_translate(intl_raw, is_intl=True)
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    all_stats = {**tw_stats, **intl_stats}
    stats_html = "".join([f"<div class='stat-item'>{k}: <span>{v}</span></div>" for k, v in sorted(all_stats.items())])
    
    full_html = f"""
    <html><head><meta charset='UTF-8'><title>台版 Techmeme</title><style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fff; margin: 0; line-height: 1.2; }}
        .header {{ background: #fff; padding: 10px 20px; border-bottom: 2px solid #000; display: flex; justify-content: space-between; align-items: center; }}
        .header h1 {{ margin: 0; font-size: 22px; font-weight: 900; }}
        .stats-summary {{ background: #f0f0f0; padding: 5px 20px; font-size: 11px; cursor: pointer; border-bottom: 1px solid #ddd; color: #555; }}
        .stats-details {{ display: none; background: #fff; padding: 15px 20px; border-bottom: 1px solid #ddd; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 5px; }}
        .stat-item {{ font-size: 11px; }}
        .wrapper {{ display: flex; width: 100%; margin: 0 auto; gap: 1px; background: #ddd; min-height: 100vh; }}
        .river {{ flex: 1; background: #fff; padding: 10px 15px; }}
        .river-title {{ font-size: 18px; font-weight: bold; border-bottom: 1px solid #000; margin-bottom: 10px; padding-bottom: 3px; color: #333; }}
        .date-header {{ background: #444; color: #fff; padding: 2px 8px; font-size: 11px; margin: 15px 0 5px; display: inline-block; font-weight: bold; }}
        .story-block {{ padding: 6px 0; margin-bottom: 2px; border-bottom: 1px solid #f0f0f0; }}
        .headline-wrapper {{ display: flex; align-items: flex-start; }}
        .star-btn {{ cursor: pointer; color: #ccc; font-size: 14px; margin-right: 6px; user-select: none; margin-top: 1px; transition: color 0.2s; }}
        .star-btn.active {{ color: #f1c40f; }}
        .headline {{ color: #0000ee; text-decoration: none; font-size: 15px; font-weight: bold; line-height: 1.3; flex: 1; }}
        .headline:hover {{ text-decoration: underline; }}
        .original-title {{ font-size: 11px; color: #888; margin: 1px 0 3px 20px; }}
        .sub-link {{ display: block; font-size: 11px; color: #555; margin-top: 2px; text-decoration: none; padding-left: 20px; }}
        .source-tag {{ font-size: 11px; color: #777; font-weight: normal; }}
        .other-mentions {{ font-size: 11px; color: #999; margin-top: 3px; padding-left: 20px; font-style: italic; }}
    </style></head><body>
        <div class='header'><h1>台版 Techmeme</h1><div style="text-align: right; font-size: 11px; color: #666;">{now_str} (台北)</div></div>
        <div class="stats-summary" onclick="toggleStats()">📊 抓取 {len(all_stats)} 媒體共 {sum(all_stats.values())} 報導 <span id="toggle-txt">▼</span></div>
        <div id="stats-details" class="stats-details">{stats_html}</div>
        <div class='wrapper'>
            {render_column(intl_clusters, "Global News River")}
            {render_column(tw_clusters, "Taiwan News River")}
        </div>
        <script>
            function toggleStats() {{
                const p = document.getElementById('stats-details');
                const t = document.getElementById('toggle-txt');
                const isHidden = p.style.display !== 'grid';
                p.style.display = isHidden ? 'grid' : 'none';
                t.innerText = isHidden ? '▲' : '▼';
            }}
            function toggleStar(link) {{
                let b = JSON.parse(localStorage.getItem('tech_bookmarks') || '[]');
                const el = document.querySelector(`[data-id="${{link}}"]`);
                const s = el.querySelector('.star-btn');
                if (b.includes(link)) {{ b = b.filter(i => i !== link); s.classList.remove('active'); }}
                else {{ b.push(link); s.classList.add('active'); }}
                localStorage.setItem('tech_bookmarks', JSON.stringify(b));
            }}
            document.addEventListener('DOMContentLoaded', () => {{
                const b = JSON.parse(localStorage.getItem('tech_bookmarks') || '[]');
                b.forEach(link => {{
                    const el = document.querySelector(`[data-id="${{link}}"]`);
                    if (el) {{ el.querySelector('.star-btn').classList.add('active'); }}
                }});
            }});
        </script>
    </body></html>
    """
    os.makedirs('output', exist_ok=True)
    with open('output/index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__":
    main()
