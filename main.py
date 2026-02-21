import feedparser
import datetime
import pytz
import os
import difflib
import requests
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

# 1. 國際媒體 (矽谷/歐美/深度分析)
FEEDS_INTL = [
    "https://stratechery.passport.online/feed/rss/CKcytLmgkRgmzv33UPinr",
    "https://siliconangle.com/feed/",
    "https://www.crn.com/rss/cloud", "https://www.crn.com/rss/computing",
    "https://www.crn.com/rss/data-center", "https://www.crn.com/rss/software",
    "https://www.crn.com/rss/networking",
    "https://techcrunch.com/feed/", "https://www.theverge.com/rss/partner/techmeme-full-article/rss.xml",
    "https://www.wired.com/feed/rss", "https://feeds.bloomberg.com/technology/news.rss",
    "https://www.ft.com/technology?format=rss", "https://feeds.arstechnica.com/arstechnica/index/",
    "https://9to5google.com/feed/", "https://feeds.macrumors.com/MacRumors-All"
]

# 2. 日韓媒體 (包含日韓原文來源)
FEEDS_JK = [
    "http://rss.etnews.com/03.xml", # 韓國 ETNews (韓文)
    "https://xtech.nikkei.com/rss/index.rdf", # Nikkei Xtech (日文)
    "https://www.sbbit.jp/rss/Special.rss", # SBBIT 獨家 (日文)
    "https://www.sbbit.jp/rss/HotTopics.rss", # SBBIT 熱門 (日文)
    "https://thinkit.co.jp/rss/all/feed.xml", # ThinkIT (日文)
    "https://it.impress.co.jp/rss/all/index.rdf", # Impress IT Leader (日文)
    "https://asia.nikkei.com/rss/feed/nar", # Nikkei Asia (英文)
    "http://www.koreaherald.com/common/rss_xml.php?ct=1003",
    "https://en.yna.co.kr/RSS/sci-tech.xml"
]

# 3. 台灣媒體
FEEDS_TW = [
    "https://www.ithome.com.tw/rss", "https://technews.tw/feed/",
    "https://www.digitimes.com.tw/rss/news.xml", "https://www.cio.com.tw/feed/",
    "https://www.bnext.com.tw/rss", "https://www.ctee.com.tw/rss/tech",
    "https://money.udn.com/rssfeed/news/1001/5591/1059?ch=money",
    "https://www.cna.com.tw/cna2018/api/jsnews.aspx?type=ait"
]

def is_similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio() > 0.85

def fetch_data(urls):
    data_by_date = {}
    stats = {}
    now_utc = datetime.datetime.now(pytz.utc)
    limit_48h = now_utc - datetime.timedelta(hours=48)
    seen_titles = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'}
    
    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.encoding = response.apparent_encoding # 自動修正編碼處理日韓文
            feed = feedparser.parse(response.content)
            s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            stats[s_name] = 0
            for entry in feed.entries[:15]:
                title = entry.title.strip()
                if any(kw in title.lower() for kw in BLACKLIST): continue
                if any(is_similar(title, seen) for seen in seen_titles): continue
                
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                if not raw_date: continue
                try:
                    p_date = date_parser.parse(raw_date)
                    if p_date.tzinfo is None: p_date = pytz.utc.localize(p_date)
                except: continue
                if p_date < limit_48h: continue
                
                p_date_tw = p_date.astimezone(TW_TZ)
                date_str = p_date_tw.strftime('%Y-%m-%d')
                author = entry.get('author', entry.get('author_detail', {}).get('name', ''))
                data_by_date.setdefault(date_str, []).append({'title': title, 'link': entry.link, 'source': s_name, 'time': p_date_tw, 'author': author})
                seen_titles.append(title)
                stats[s_name] += 1
        except: continue
    return data_by_date, stats

def cluster_and_translate(daily_data, need_trans=False):
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    results = {}
    for d_str, news_list in daily_data.items():
        if not news_list: continue
        titles = [n['title'] for n in news_list]
        embeddings = model.encode(titles)
        clusters = DBSCAN(eps=0.42, min_samples=1, metric="cosine").fit_predict(embeddings)
        groups = {}
        for i, cid in enumerate(clusters): groups.setdefault(cid, []).append(news_list[i])
        
        final_groups = []
        for cid, articles in groups.items():
            articles.sort(key=lambda x: x['time'])
            first = articles[0]
            if need_trans:
                try: first['trans_title'] = translator.translate(first['title'], dest='zh-tw').text
                except: first['trans_title'] = first['title']
            
            is_priority = any(kw.lower() in first['title'].lower() for kw in WHITELIST)
            if 'trans_title' in first: is_priority = is_priority or any(kw.lower() in first['trans_title'].lower() for kw in WHITELIST)
            
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
            display_title = first.get('trans_title', first['title'])
            safe_id = first['link'].replace('"', '&quot;')
            meta = f" — {first['source']} {first['time'].strftime('%H:%M')}"
            
            pri_class = "priority" if group['priority'] else ""
            html += f"<div class='story-block {pri_class}' data-id=\"{safe_id}\">"
            html += f"<div class='headline-wrapper'><span class='star-btn' onclick='toggleStar(\"{safe_id}\")'>★</span>"
            html += f"<a class='headline' href='{first['link']}'>{display_title} <span class='source-tag'>{meta}</span></a></div>"
            if 'trans_title' in first: html += f"<div class='original-title'>{first['title']}</div>"
            for up in sorted(articles[1:], key=lambda x: x['time'], reverse=True)[:5]:
                html += f"<a class='sub-link' href='{up['link']}'>↳ <span class='source-name'>{up['source']}</span>: {up.get('trans_title', up['title'])}</a>"
            html += "</div>"
    html += "</div>"
    return html

def main():
    intl_raw, intl_st = fetch_data(FEEDS_INTL)
    jk_raw, jk_st = fetch_data(FEEDS_JK)
    tw_raw, tw_st = fetch_data(FEEDS_TW)
    
    intl_cls = cluster_and_translate(intl_raw, need_trans=True)
    jk_cls = cluster_and_translate(jk_raw, need_trans=True)
    tw_cls = cluster_and_translate(tw_raw, need_trans=False)
    
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    all_st = {**intl_st, **jk_st, **tw_st}
    stats_html = "".join([f"<div class='stat-item'>{k}: <span>{v}</span></div>" for k, v in sorted(all_st.items())])
    
    full_html = f"""
    <html><head><meta charset='UTF-8'><title>台版 Techmeme 戰情室</title><style>
        :root {{ --bg: #ffffff; --text: #000000; --link: #0000ee; --meta: #777777; --border: #dddddd; --river-bg: #ffffff; }}
        @media (prefers-color-scheme: dark) {{
            :root {{ --bg: #1a1a1a; --text: #e0e0e0; --link: #8ab4f8; --meta: #999999; --border: #333333; --river-bg: #1a1a1a; }}
        }}
        body {{ font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.2; }}
        .header {{ padding: 10px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; align-items: center; }}
        .stats-summary {{ background: var(--bg); padding: 5px 20px; font-size: 11px; cursor: pointer; border-bottom: 1px solid var(--border); color: var(--meta); }}
        .stats-details {{ display: none; padding: 15px; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 5px; border-bottom: 1px solid var(--border); }}
        .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; width: 100%; max-width: 1900px; margin: 0 auto; min-height: 100vh; gap: 1px; background: var(--border); }}
        .river {{ background: var(--river-bg); padding: 10px 15px; }}
        .river-title {{ font-size: 18px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 10px; padding-bottom: 3px; }}
        .date-header {{ background: #444; color: #fff; padding: 2px 8px; font-size: 11px; margin: 15px 0 5px; display: inline-block; font-weight: bold; }}
        .story-block {{ padding: 8px 0; border-bottom: 1px solid var(--border); }}
        .story-block.priority {{ border-left: 3px solid #0000ee44; padding-left: 8px; }}
        .headline {{ color: var(--link); text-decoration: none; font-size: 15px; font-weight: bold; }}
        .original-title {{ font-size: 11px; color: var(--meta); margin: 2px 0 4px 20px; }}
        .sub-link {{ display: block; font-size: 11px; color: var(--text); opacity: 0.8; margin-top: 3px; text-decoration: none; padding-left: 20px; }}
        .source-tag {{ font-size: 11px; color: var(--meta); font-weight: normal; }}
        .star-btn {{ cursor: pointer; color: #ccc; margin-right: 6px; }}
        .star-btn.active {{ color: #f1c40f; }}
    </style></head><body>
        <div class='header'><h1>Techmeme 戰情室</h1><div style="font-size: 11px;">{now_str} Taipei</div></div>
        <div class="stats-summary" onclick="toggleStats()">📊 監控 {len(all_st)} 媒體 <span id="toggle-txt">▼</span></div>
        <div id="stats-details" class="stats-details">{stats_html}</div>
        <div class='wrapper'>
            {render_column(intl_cls, "Global & Strategy")}
            {render_column(jk_cls, "Japan/Korea Tech")}
            {render_column(tw_cls, "Taiwan IT & Biz")}
        </div>
        <script>
            function toggleStats() {{
                const p = document.getElementById('stats-details');
                p.style.display = p.style.display === 'grid' ? 'none' : 'grid';
            }}
            function toggleStar(link) {{
                let b = JSON.parse(localStorage.getItem('tech_bookmarks') || '[]');
                if (b.includes(link)) b = b.filter(i => i !== link);
                else b.push(link);
                localStorage.setItem('tech_bookmarks', JSON.stringify(b));
                const el = document.querySelector(`[data-id="${{link}}"]`);
                if (el) el.querySelector('.star-btn').classList.toggle('active');
            }}
            document.addEventListener('DOMContentLoaded', () => {{
                const b = JSON.parse(localStorage.getItem('tech_bookmarks') || '[]');
                b.forEach(link => {{
                    const el = document.querySelector(`[data-id="${{link}}"]`);
                    if (el) el.querySelector('.star-btn').classList.add('active');
                }});
            }});
        </script>
    </body></html>
    """
    os.makedirs('output', exist_ok=True)
    with open('output/index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__": main()
