import feedparser, datetime, pytz, os, difflib, requests, json, re
from dateutil import parser as date_parser
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from googletrans import Translator
from bs4 import BeautifulSoup
import urllib3

# 停用連線警告
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

def clean_html(raw_html):
    if not raw_html: return ""
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', str(raw_html))[:160].strip() + "..."

def apply_custom_terms(text):
    term_map = CONFIG.get('TERM_MAP', {})
    for wrong, right in term_map.items(): text = text.replace(wrong, right)
    it_fixes = {"副駕駛": "Copilot", "智能": "智慧", "數據": "資料", "服務器": "伺服器", "軟件": "軟體", "網絡": "網路", "信息": "資訊"}
    for w, r in it_fixes.items(): text = text.replace(w, r)
    return text

def highlight_keywords(text):
    for kw in CONFIG['WHITELIST']:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(f'<span class="kw-highlight">\\g<0></span>', text)
    return text

def is_similar(a, b): return difflib.SequenceMatcher(None, a, b).ratio() > 0.85

def fetch_html_fallback(name, url, selectors, tag_name):
    """強化 HTML 抓取：支援 CSS 模糊匹配與 Session 模擬"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': url,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    articles = []
    try:
        session = requests.Session()
        resp = session.get(url, headers=headers, timeout=30, verify=False)
        if resp.status_code != 200: return []
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        items = []
        for sel in selectors:
            items = soup.select(sel)
            if items: break
            
        for item in items[:20]:
            title = item.get_text().strip()
            link = item.get('href', '')
            if not title or not link or len(title) < 5: continue
            if link.startswith('/'): link = "/".join(url.split('/')[:3]) + link
            if any(x in link for x in ['/about', '/ad', '/privacy']): continue
            articles.append({
                'raw_title': title, 'link': link, 'source': name,
                'time': datetime.datetime.now(TW_TZ), 'tag_html': tag_name,
                'is_analysis': "[分析]" in tag_name, 'raw_summary': ""
            })
    except: pass
    return articles

def fetch_data(feed_list):
    data_by_date, stats, seen = {}, {}, []
    now_utc = datetime.datetime.now(pytz.utc)
    limit_time = now_utc - datetime.timedelta(hours=72)
    headers = {'User-Agent': 'Mozilla/5.0'}
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
                data_by_date.setdefault(date_str, []).append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date_tw, 'tag_html': tag, 'is_analysis': "[分析]" in tag, 'raw_summary': clean_html(entry.get('summary', ""))})
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
        clusters = DBSCAN(eps=0.42, min_samples=1, metric="cosine").fit_predict(embeddings)
        groups = {}
        for i, cid in enumerate(clusters): groups.setdefault(cid, []).append(news_list[i])
        final_groups = []
        for articles in groups.values():
            articles.sort(key=lambda x: x['time'])
            for idx, art in enumerate(articles):
                raw = art['raw_title']
                if need_trans:
                    if raw in TRANS_CACHE: translated = TRANS_CACHE[raw]
                    else:
                        try:
                            translated = apply_custom_terms(translator.translate(raw, dest='zh-tw').text)
                            TRANS_CACHE[raw] = translated
                        except: translated = raw
                    art['translated_title'] = translated
                    art['display_title'] = (art['tag_html'] + " " if art['tag_html'] else "") + highlight_keywords(translated)
                    if idx == 0:
                        sum_key = raw[:40] + "_sum"
                        if sum_key in TRANS_CACHE: art['display_summary'] = TRANS_CACHE[sum_key]
                        else:
                            try:
                                t_sum = apply_custom_terms(translator.translate(art['raw_summary'], dest='zh-tw').text)
                                TRANS_CACHE[sum_key] = t_sum
                                art['display_summary'] = t_sum
                            except: art['display_summary'] = art['raw_summary']
                else:
                    fixed = apply_custom_terms(raw)
                    art['translated_title'] = fixed
                    art['display_title'] = (art['tag_html'] + " " if art['tag_html'] else "") + highlight_keywords(fixed)
                    if idx == 0: art['display_summary'] = apply_custom_terms(art['raw_summary'])
            first = articles[0]
            is_priority = any(kw.lower() in first['raw_title'].lower() for kw in CONFIG['WHITELIST']) or first['is_analysis']
            final_groups.append({'articles': articles, 'priority': is_priority})
        final_groups.sort(key=lambda x: (x['priority'], x['articles'][0]['time']), reverse=True)
        results[d_str] = final_groups
    return results

def render_column(daily_clusters, title_prefix):
    all_arts = []
    for d in daily_clusters:
        for g in daily_clusters[d]: all_arts.extend(g['articles'])
    stats_bar = f"<div class='column-stats'>總量：{len(all_arts)} 則報導</div>" if all_arts else "<div class='column-stats'>無新資訊</div>"
    html = f"<div class='river'><div class='river-title'>{title_prefix}</div>{stats_bar}"
    for d_str in sorted(daily_clusters.keys(), reverse=True):
        group_list = daily_clusters[d_str]
        html += f"<div class='date-header'>{d_str} <span class='day-count'>({sum(len(g['articles']) for g in group_list)} 則)</span></div>"
        for group in group_list:
            first = group['articles'][0]
            safe_id = first['link'].replace('"', '&quot;')
            meta = f" — {first['source']} {first['time'].strftime('%H:%M')}"
            html += f"<div class='story-block {'priority' if group['priority'] else ''}' data-id=\"{safe_id}\" title=\"{first.get('display_summary','')}\">"
            html += f"<div class='headline-wrapper'><span class='star-btn' onclick='toggleStar(\"{safe_id}\")'>★</span>"
            html += f"<a class='headline' href='{first['link']}' target='_blank'>{first['display_title']} <span class='source-tag'>{meta}</span></a></div>"
            if 'raw_title' in first and first['display_title'].find(first['raw_title']) == -1:
                html += f"<div class='original-title'>{first['raw_title']}</div>"
            for up in sorted(group['articles'][1:], key=lambda x: x['time'], reverse=True)[:5]:
                html += f"<a class='sub-link' href='{up['link']}' target='_blank'>↳ {up['source']}: {up.get('translated_title', up['raw_title'])}</a>"
            html += "</div>"
    return html + "</div>"

def main():
    intl_raw, intl_st, s1 = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_raw, jk_st, s2 = fetch_data(CONFIG['FEEDS']['JK'])
    tw_raw, tw_st, s3 = fetch_data(CONFIG['FEEDS']['TW'])
    all_seen = s1 + s2 + s3
    today_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d')

    # --- 豆子特別調教：首頁與頑固來源 ---
    nikkei_web = fetch_html_fallback('Nikkei Asia', 'https://asia.nikkei.com', ['h2 a', 'h3 a', 'a[class*="title"]', '.n-card__title-link'], '')
    if nikkei_web: intl_raw.setdefault(today_str, []).extend(nikkei_web); intl_st['Nikkei Asia'] = len(nikkei_web)

    cio_web = fetch_html_fallback('CIO Taiwan', 'https://www.cio.com.tw', ['h3.entry-title a', 'article h3 a'], '[分析]')
    if cio_web: tw_raw.setdefault(today_str, []).extend(cio_web); tw_st['CIO Taiwan'] = len(cio_web)

    # 數位時代首頁抓取 (改抓 bnext.com.tw 首頁結構)
    bnext_web_all = fetch_html_fallback('數位時代', 'https://www.bnext.com.tw/', ['div.item_box a', 'a.item_title', '.article_title'], '[數位]')
    # 增加去重比對：如果標題已經在 RSS 中出現過則跳過
    bnext_web = [a for a in bnext_web_all if not any(is_similar(a['raw_title'], s) for s in all_seen)]
    if bnext_web: tw_raw.setdefault(today_str, []).extend(bnext_web); tw_st['數位時代'] = len(bnext_web)

    zdj_web = fetch_html_fallback('ZDNet Japan', 'https://japan.zdnet.com', ['section.content-list h3 a', 'h3 a', '.content-list__title a'], '[日]')
    if zdj_web: jk_raw.setdefault(today_str, []).extend(zdj_web); jk_st['ZDNet Japan'] = len(zdj_web)
    
    # 產出
    intl_cls, jk_cls, tw_cls = cluster_and_translate(intl_raw, True), cluster_and_translate(jk_raw, True), cluster_and_translate(tw_raw, False)
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    all_st = {**intl_st, **jk_st, **tw_st}
    
    stats_items = []
    for k, v in sorted(all_st.items(), key=lambda x: x[1], reverse=True):
        status_color = "var(--accent)" if v > 0 else "#e74c3c"
        stats_items.append(f"<div class='stat-row'><span class='stat-name'>{'●' if v > 0 else '○'} {k}</span><div class='stat-bar-container'><div class='stat-bar-fill' style='width: {min(v*4,100)}%; background: {status_color}'></div></div><span class='stat-count' style='color: {status_color}'>{v}</span></div>")

    full_html = f"""
    <html><head><meta charset='UTF-8'><title>{SITE_TITLE}</title><style>
        :root {{ --bg: #fff; --text: #333; --meta: #777; --border: #ddd; --hi: #ffff0033; --link: #1a0dab; --visited: #609; --accent: #27ae60; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #1a1a1a; --text: #ccc; --meta: #999; --border: #333; --hi: #ffd70033; --link: #8ab4f8; --visited: #c58af9; }} }}
        body {{ font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.3; }}
        .header {{ padding: 10px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 100; }}
        #stats-details {{ display: none; padding: 10px 20px; background: rgba(0,0,0,0.02); border-bottom: 1px solid var(--border); column-count: 2; }}
        .stat-row {{ display: flex; align-items: center; gap: 8px; padding: 2px 0; break-inside: avoid; max-width: 450px; }}
        .stat-name {{ font-size: 11px; width: 180px; font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        .stat-bar-container {{ width: 60px; height: 5px; background: #eee; border-radius: 3px; overflow: hidden; }}
        .stat-bar-fill {{ height: 100%; border-radius: 3px; }}
        .stat-count {{ font-size: 11px; font-weight: bold; width: 30px; text-align: left; font-family: monospace; }}
        .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; width: 100%; max-width: 1900px; margin: 0 auto; gap: 1px; background: var(--border); min-height: 100vh; }}
        .river {{ background: var(--bg); padding: 10px 15px; }}
        .river-title {{ font-size: 17px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 5px; }}
        .headline {{ color: var(--link); text-decoration: none; font-size: 14.5px; font-weight: bold; }}
        .headline:visited {{ color: var(--visited); }}
        .star-btn {{ cursor: pointer; color: #ccc; margin-right: 6px; font-size: 16px; }}
        .star-btn.active {{ color: #f1c40f; }}
        .btn {{ cursor: pointer; padding: 4px 12px; border: 1px solid var(--text); font-size: 11px; font-weight: bold; background: var(--bg); color: var(--text); border-radius: 4px; }}
        body.only-stars .story-block:not(.has-star) {{ display: none; }}
    </style></head><body>
        <div class='header'><h1>{SITE_TITLE}</h1><div class='controls'><div id='stats-btn' class='btn' onclick='toggleStats()'>📊 來源統計</div><div id='star-filter' class='btn' onclick='toggleStarFilter()'>★ 僅看星號</div><div style="font-size:11px; color:var(--meta);">{now_str}</div></div></div>
        <div id="stats-details">{"".join(stats_items)}</div>
        <div class='wrapper'>{render_column(intl_cls, "Global & Strategy")}{render_column(jk_cls, "Japan/Korea Tech")}{render_column(tw_cls, "Taiwan IT & Biz")}</div>
        <script>
            function toggleStats() {{ const p = document.getElementById('stats-details'); p.style.display = (p.style.display === 'block') ? 'none' : 'block'; }}
            function toggleStarFilter() {{ document.body.classList.toggle('only-stars'); }}
            function toggleStar(link) {{ let b = JSON.parse(localStorage.getItem('tech_bookmarks') || '[]'); b.includes(link) ? b = b.filter(i => i !== link) : b.push(link); localStorage.setItem('tech_bookmarks', JSON.stringify(b)); updateStarUI(); }}
            function updateStarUI() {{ const b = JSON.parse(localStorage.getItem('tech_bookmarks') || '[]'); document.querySelectorAll('.story-block').forEach(el => {{ const id = el.getAttribute('data-id'); const isStarred = b.includes(id); el.querySelector('.star-btn').classList.toggle('active', isStarred); el.classList.toggle('has-star', isStarred); }}); }}
            document.addEventListener('DOMContentLoaded', updateStarUI);
        </script></body></html>
    """
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)
    save_cache(TRANS_CACHE)

if __name__ == "__main__": main()
