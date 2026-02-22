import feedparser, datetime, pytz, os, difflib, requests, json, re, time, random
from dateutil import parser as date_parser
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from googletrans import Translator
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 基礎設定 ---
TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific"), "EST": pytz.timezone("US/Eastern"), "EDT": pytz.timezone("US/Eastern"), "JST": pytz.timezone("Asia/Tokyo"), "KST": pytz.timezone("Asia/Seoul")}
translator = Translator()
CACHE_FILE = 'translation_cache.json'
SITE_TITLE = "豆子版 Techmeme | 2026.v1"

def load_config():
    with open('feeds.json', 'r', encoding='utf-8') as f: return json.load(f)

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}
    return {}

def save_cache(cache_data):
    if len(cache_data) > 3500: cache_data = dict(list(cache_data.items())[-3500:])
    with open(CACHE_FILE, 'w', encoding='utf-8') as f: json.dump(cache_data, f, ensure_ascii=False, indent=2)

CONFIG = load_config()
TRANS_CACHE = load_cache()

def apply_custom_terms(text):
    term_map = CONFIG.get('TERM_MAP', {})
    for wrong, right in term_map.items(): text = text.replace(wrong, right)
    it_fixes = {"副駕駛": "Copilot", "智能": "智慧", "數據": "資料", "服務器": "伺服器", "軟件": "軟體", "網絡": "網路", "信息": "資訊", "計算": "運算"}
    for w, r in it_fixes.items(): text = text.replace(w, r)
    return text

def translate_text(text):
    if not text: return ""
    if text in TRANS_CACHE: return TRANS_CACHE[text]
    try:
        res = apply_custom_terms(translator.translate(text, dest='zh-tw').text)
        TRANS_CACHE[text] = res
        return res
    except: return text

def highlight_keywords(text):
    for kw in CONFIG['WHITELIST']:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(f'<span class="kw-highlight">\\g<0></span>', text)
    return text

def is_similar(a, b): return difflib.SequenceMatcher(None, a, b).ratio() > 0.85

def fetch_html_fallback(name, url, selectors, tag_name):
    """進階 HTML 抓取：模擬真實瀏覽器環境"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.google.com/',
        'Connection': 'keep-alive'
    }
    articles = []
    try:
        # 增加一點隨機延遲，避免被判定為機器人
        time.sleep(random.uniform(1, 3))
        session = requests.Session()
        resp = session.get(url, headers=headers, timeout=30, verify=False)
        if resp.status_code != 200: 
            print(f"[診斷] {name} 抓取失敗，狀態碼: {resp.status_code}")
            return []
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = []
        for sel in selectors:
            items = soup.select(sel)
            if items: break
        for item in items[:15]:
            title = item.get_text().strip()
            link = item.get('href', '')
            if not title or not link or len(title) < 5: continue
            if link.startswith('/'): link = "/".join(url.split('/')[:3]) + link
            articles.append({'raw_title': title, 'link': link, 'source': name, 'time': datetime.datetime.now(TW_TZ), 'tag_html': tag_name, 'is_analysis': "[分析]" in tag_name, 'raw_summary': ""})
    except Exception as e:
        print(f"[錯誤] {name} 發生異常: {e}")
    return articles

def fetch_data(feed_list):
    data_by_date, stats, seen = {}, {}, []
    now_utc = datetime.datetime.now(pytz.utc)
    limit_time = now_utc - datetime.timedelta(hours=72)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}
    for item in feed_list:
        url, tag = item['url'], item['tag']
        try:
            resp = requests.get(url, headers=headers, timeout=25, verify=False)
            feed = feedparser.parse(resp.content)
            s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            stats[s_name] = 0
            for entry in feed.entries[:20]:
                title = entry.title.strip()
                if any(is_similar(title, s) for s in seen): continue
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                try:
                    p_date = date_parser.parse(raw_date, tzinfos=TZ_INFOS).astimezone(pytz.utc)
                except: continue
                if p_date < limit_time: continue
                p_date_tw = p_date.astimezone(TW_TZ)
                date_str = p_date_tw.strftime('%Y-%m-%d')
                data_by_date.setdefault(date_str, []).append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date_tw, 'tag_html': tag, 'is_analysis': "[分析]" in tag, 'raw_summary': ""})
                seen.append(title); stats[s_name] += 1
        except: continue
    return data_by_date, stats, seen

def cluster_and_translate(daily_data, need_trans=False):
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    results = {}
    for d_str, news_list in daily_data.items():
        if not news_list: continue
        titles = [n['raw_title'] for n in news_list]
        embeddings = model.encode(titles)
        clusters = DBSCAN(eps=0.35, min_samples=1, metric="cosine").fit_predict(embeddings)
        groups = {}
        for i, cid in enumerate(clusters): groups.setdefault(cid, []).append(news_list[i])
        final_groups = []
        for articles in groups.values():
            articles.sort(key=lambda x: x['time'])
            for idx, art in enumerate(articles):
                raw = art['raw_title']
                translated = translate_text(raw)
                art['translated_title'] = translated
                art['display_title'] = (art['tag_html'] + " " if art['tag_html'] else "") + highlight_keywords(translated)
            first = articles[0]
            is_priority = any(kw.lower() in first['raw_title'].lower() for kw in CONFIG['WHITELIST']) or first['is_analysis']
            final_groups.append({'articles': articles, 'priority': is_priority})
        final_groups.sort(key=lambda x: (x['priority'], x['articles'][0]['time']), reverse=True)
        results[d_str] = final_groups
    return results

def render_column(daily_clusters, title_prefix):
    html = f"<div class='river'><div class='river-title'>{title_prefix}</div>"
    for d_str in sorted(daily_clusters.keys(), reverse=True):
        group_list = daily_clusters[d_str]
        html += f"<div class='date-header'>{d_str}</div>"
        for group in group_list:
            first = group['articles'][0]
            # 建立穩定的 ID 用於星號功能
            link_hash = str(abs(hash(first['link'])))[:12]
            meta = f" — {first['source']} {first['time'].strftime('%H:%M')}"
            html += f"<div class='story-block {'priority' if group['priority'] else ''}' id='sb-{link_hash}' data-link='{first['link']}'>"
            html += f"<div class='headline-wrapper'><span class='star-btn' onclick='toggleStar(\"{link_hash}\")'>★</span>"
            html += f"<a class='headline' href='{first['link']}' target='_blank'>{first['display_title']} <span class='source-tag'>{meta}</span></a></div>"
            if first['translated_title'] != first['raw_title']:
                html += f"<div class='original-title'>{first['raw_title']}</div>"
            for up in sorted(group['articles'][1:], key=lambda x: x['time'], reverse=True)[:5]:
                sub_title = translate_text(up['raw_title'])
                html += f"<a class='sub-link' href='{up['link']}' target='_blank'>↳ {up['source']}: {sub_title}</a>"
            html += "</div>"
    return html + "</div>"

def main():
    intl_raw, intl_st, s1 = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_raw, jk_st, s2 = fetch_data(CONFIG['FEEDS']['JK'])
    tw_raw, tw_st, s3 = fetch_data(CONFIG['FEEDS']['TW'])
    all_seen = s1 + s2 + s3
    today_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d')

    # 深度修復 Bnext & Nikkei & CIO
    for name, url, sels, tag in [
        ('Nikkei Asia', 'https://asia.nikkei.com', ['h3 a', 'a[class*="title"]'], ''), 
        ('CIO Taiwan', 'https://www.cio.com.tw', ['h3.entry-title a', 'article h3 a'], '[分析]'),
        ('數位時代', 'https://www.bnext.com.tw/articles', ['a.item_title', 'div.item_box a'], '[數位]')
    ]:
        web = fetch_html_fallback(name, url, sels, tag)
        clean_web = [a for a in web if not any(is_similar(a['raw_title'], s) for s in all_seen)]
        if clean_web:
            target = intl_raw if name=='Nikkei Asia' else tw_raw
            target.setdefault(today_str, []).extend(clean_web)
            if name == '數位時代': tw_st['數位時代'] = len(clean_web)

    intl_cls, jk_cls, tw_cls = cluster_and_translate(intl_raw, True), cluster_and_translate(jk_raw, True), cluster_and_translate(tw_raw, False)
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    
    stats_items = [f"<div class='stat-row'>● {k}: {v}</div>" for k, v in sorted({**intl_st, **jk_st, **tw_st}.items(), key=lambda x: x[1], reverse=True)]

    full_html = f"""
    <html><head><meta charset='UTF-8'><title>{SITE_TITLE}</title><style>
        :root {{ --bg: #fff; --text: #333; --meta: #777; --border: #ddd; --hi: #ffff0033; --link: #1a0dab; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #1a1a1a; --text: #ccc; --meta: #999; --border: #333; --link: #8ab4f8; }} }}
        body {{ font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.3; }}
        .header {{ padding: 10px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 100; }}
        .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1px; background: var(--border); }}
        .river {{ background: var(--bg); padding: 10px; }}
        .river-title {{ font-size: 17px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 10px; }}
        .date-header {{ background: #444; color: #fff; padding: 2px 8px; font-size: 11px; margin: 15px 0 5px; }}
        .story-block {{ padding: 8px 0; border-bottom: 1px solid var(--border); }}
        .story-block.has-star {{ background: rgba(241, 196, 15, 0.1); border-left: 4px solid #f1c40f; padding-left: 5px; }}
        .headline {{ color: var(--link); text-decoration: none; font-size: 14.5px; font-weight: bold; }}
        .star-btn {{ cursor: pointer; color: #ccc; margin-right: 8px; font-size: 18px; }}
        .star-btn.active {{ color: #f1c40f !important; }}
        .original-title {{ font-size: 11px; color: var(--meta); margin-left: 28px; }}
        .sub-link {{ display: block; font-size: 11px; color: var(--link); margin-left: 28px; text-decoration: none; margin-top: 3px; }}
        .btn {{ cursor: pointer; padding: 4px 12px; border: 1px solid var(--text); font-size: 11px; font-weight: bold; border-radius: 4px; background: var(--bg); color: var(--text); }}
        body.only-stars .story-block:not(.has-star) {{ display: none; }}
    </style></head><body>
        <div class='header'><h1>{SITE_TITLE}</h1><div class='controls'><div class='btn' onclick='toggleStarFilter()'>★ 僅看精選</div><div style="font-size:11px; margin-left:15px;">{now_str}</div></div></div>
        <div id="stats" style="padding:10px; font-size:11px; background:#f9f9f9; display:none;">{" | ".join(stats_items)}</div>
        <div class='wrapper'>{render_column(intl_cls, "Global & Strategy")}{render_column(jk_cls, "Japan/Korea Tech")}{render_column(tw_cls, "Taiwan IT & Biz")}</div>
        <script>
            function toggleStar(hash) {{
                const el = document.getElementById('sb-' + hash);
                const btn = el.querySelector('.star-btn');
                const link = el.getAttribute('data-link');
                let stars = JSON.parse(localStorage.getItem('tech_stars') || '[]');
                if (stars.includes(link)) {{
                    stars = stars.filter(i => i !== link);
                    el.classList.remove('has-star'); btn.classList.remove('active');
                }} else {{
                    stars.push(link);
                    el.classList.add('has-star'); btn.classList.add('active');
                }}
                localStorage.setItem('tech_stars', JSON.stringify(stars));
            }}
            function toggleStarFilter() {{ document.body.classList.toggle('only-stars'); }}
            function init() {{
                const stars = JSON.parse(localStorage.getItem('tech_stars') || '[]');
                document.querySelectorAll('.story-block').forEach(el => {{
                    if (stars.includes(el.getAttribute('data-link'))) {{
                        el.classList.add('has-star');
                        el.querySelector('.star-btn').classList.add('active');
                    }}
                }});
            }}
            document.addEventListener('DOMContentLoaded', init);
        </script></body></html>
    """
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)
    save_cache(TRANS_CACHE)

if __name__ == "__main__": main()
