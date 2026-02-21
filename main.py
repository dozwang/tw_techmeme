import feedparser
import datetime
import pytz
import os
import difflib
from dateutil import parser as date_parser
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from googletrans import Translator

# --- 設定 ---
TW_TZ = pytz.timezone('Asia/Taipei')
translator = Translator()

BLACKLIST = ["暗物質", "哈伯望遠鏡", "韋伯望遠鏡", "黑洞", "銀河系", "關稅", "經貿", "外交", "考古", "疫苗"]
WHITELIST = [
    "AI", "生成式AI", "雲原生", "軟體", "軟體開發", "CLOUD", "CIO", "CISO", 
    "DEVOPS", "DEVSECOPS", "FINOPS", "平台工程", "DOCKER", "KUBERNETES"
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

def is_similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio() > 0.85

def fetch_data(urls):
    data_by_date = {}
    stats = {}
    now_utc = datetime.datetime.now(pytz.utc)
    limit_48h = now_utc - datetime.timedelta(hours=48)
    seen_titles = []
    
    for url in urls:
        feed = feedparser.parse(url)
        s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
        stats[s_name] = 0
        for entry in feed.entries[:12]:
            try:
                title = entry.title.strip()
                if any(kw in title.lower() for kw in BLACKLIST): continue
                if any(is_similar(title, seen) for seen in seen_titles): continue
                
                p_date = date_parser.parse(entry.published)
                if p_date.tzinfo is None: p_date = pytz.utc.localize(p_date)
                if p_date < limit_48h: continue
                
                p_date_tw = p_date.astimezone(TW_TZ)
                date_str = p_date_tw.strftime('%Y-%m-%d')
                author = entry.get('author', entry.get('author_detail', {}).get('name', ''))
                if not author and 'dc_creator' in entry: author = entry['dc_creator']
                
                data_by_date.setdefault(date_str, []).append({
                    'title': title, 'link': entry.link, 'source': s_name,
                    'time': p_date_tw, 'author': author
                })
                seen_titles.append(title)
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
        
        final_groups = []
        for cid, articles in groups.items():
            articles.sort(key=lambda x: x['time'])
            first = articles[0]
            if is_intl:
                try: first['trans_title'] = translator.translate(first['title'], dest='zh-tw').text
                except: first['trans_title'] = first['title']
            is_priority = any(kw.lower() in first['title'].lower() for kw in WHITELIST)
            final_groups.append({'articles': articles, 'priority': is_priority})
        
        final_groups.sort(key=lambda x: (x['priority'], x['articles'][0]['time']), reverse=True)
        results[d_str] = final_groups
    return results

def render_column(daily_clusters, title_prefix):
    html = f"<div class='river'><div class='river-title'>{title_prefix}</div>"
    sorted_dates = sorted(daily_clusters.keys(), reverse=True)
    for d_str in sorted_dates:
        html += f"<div class='date-header'>{d_str}</div>"
        for group in daily_clusters[d_str]:
            articles = group['articles']
            first = articles[0]
            latest_updates = sorted(articles[1:], key=lambda x: x['time'], reverse=True)[:5]
            others = [a for a in articles if a not in [first] + latest_updates]
            
            display_title = first.get('trans_title', first['title'])
            safe_id = first['link'].replace('"', '&quot;')
            meta = f" — {first['source']} {first['time'].strftime('%H:%M')}{' by '+first['author'] if first['author'] else ''}"
            pri_class = "priority" if group['priority'] else ""
            
            html += f"<div class='story-block {pri_class}' data-id=\"{safe_id}\">"
            html += f"<div class='headline-wrapper'>"
            html += f"<span class='star-btn' onclick='toggleStar(\"{safe_id}\")'>★</span>"
            html += f"<a class='headline' href='{first['link']}'>{display_title} <span class='source-tag'>{meta}</span></a>"
            html += f"</div>"
            if 'trans_title' in first:
                html += f"<div class='original-title'>{first['title']}</div>"
            for up in latest_updates:
                u_m = f"({up['time'].strftime('%H:%M')}{' by '+up['author'] if up['author'] else ''})"
                html += f"<a class='sub-link' href='{up['link']}'>↳ <span class='source-name'>{up['source']} {u_m}</span>: {up.get('trans_title', up['title'])}</a>"
            if others:
                html += f"<div class='other-mentions'>Also: {', '.join([o['source'] for o in others[:8]])}</div>"
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
        :root {{ --bg: #ffffff; --text: #000000; --link: #0000ee; --meta: #777777; --border: #f0f0f0; --header-bg: #f0f0f0; --river-bg: #ffffff; }}
        @media (prefers-color-scheme: dark) {{
            :root {{ --bg: #1a1a1a; --text: #e0e0e0; --link: #8ab4f8; --meta: #999999; --border: #333333; --header-bg: #2d2d2d; --river-bg: #1a1a1a; }}
        }}
        body {{ font-family: -apple-system, system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.2; }}
        .header {{ background: var(--bg); padding: 10px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; align-items: center; }}
        .header h1 {{ margin: 0; font-size: 22px; font-weight: 900; }}
        .stats-summary {{ background: var(--header-bg); padding: 5px 20px; font-size: 11px; cursor: pointer; border-bottom: 1px solid var(--border); color: var(--meta); }}
        .stats-details {{ display: none; background: var(--bg); padding: 15px 20px; border-bottom: 1px solid var(--border); grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 5px; }}
        .wrapper {{ display: flex; width: 100%; gap: 1px; background: var(--border); min-height: 100vh; }}
        .river {{ flex: 1; background: var(--river-bg); padding: 10px 15px; }}
        .river-title {{ font-size: 18px; font-weight: bold; border-bottom: 1px solid var(--text); margin-bottom: 10px; padding-bottom: 3px; }}
        .date-header {{ background: #444; color: #fff; padding: 2px 8px; font-size: 11px; margin: 15px 0 5px; display: inline-block; font-weight: bold; }}
        .story-block {{ padding: 6px 0; border-bottom: 1px solid var(--border); }}
        .story-block.priority {{ border-left: 3px solid #0000ee44; padding-left: 5px; }}
        .headline-wrapper {{ display: flex; align-items: flex-start; }}
        .star-btn {{ cursor: pointer; color: #ccc; font-size: 14px; margin-right: 6px; margin-top: 1px; }}
        .star-btn.active {{ color: #f1c40f; }}
        .headline {{ color: var(--link); text-decoration: none; font-size: 15px; font-weight: bold; }}
        .original-title {{ font-size: 11px; color: var(--meta); margin: 1px 0 3px 20px; }}
        .sub-link {{ display: block; font-size: 11px; color: var(--text); opacity: 0.8; margin-top: 2px; text-decoration: none; padding-left: 20px; }}
        .source-tag {{ font-size: 11px; color: var(--meta); font-weight: normal; }}
        .other-mentions {{ font-size: 11px; color: var(--meta); margin-top: 3px; padding-left: 20px; font-style: italic; }}
    </style></head><body>
        <div class='header'><h1>台版 Techmeme</h1><div style="text-align: right; font-size: 11px; color: var(--meta);">{now_str} (台北)</div></div>
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
