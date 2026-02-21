import feedparser, datetime, pytz, os, difflib, requests, json, re
from dateutil import parser as date_parser
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from googletrans import Translator
import urllib3

# 停用不安全連線警告 (針對 verify=False)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 基礎設定 ---
TW_TZ = pytz.timezone('Asia/Taipei')
translator = Translator()
CACHE_FILE = 'translation_cache.json'
SITE_TITLE = "豆子版 Techmeme，彙整台美日韓最新IT新聞. 2026.v1"

def load_config():
    with open('feeds.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}
    return {}

def save_cache(cache_data):
    if len(cache_data) > 3500:
        cache_data = dict(list(cache_data.items())[-3500:])
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)

CONFIG = load_config()
TRANS_CACHE = load_cache()

def clean_html(raw_html):
    if not raw_html: return ""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', str(raw_html))
    return cleantext[:160].strip() + "..."

def apply_custom_terms(text):
    term_map = CONFIG.get('TERM_MAP', {})
    for wrong, right in term_map.items():
        text = text.replace(wrong, right)
    
    it_fixes = {
        "副駕駛": "Copilot", "智能": "智慧", "數據": "資料", 
        "服務器": "伺服器", "軟件": "軟體", "網絡": "網路", 
        "信息": "資訊", "雲端原生": "雲原生"
    }
    for w, r in it_fixes.items():
        text = text.replace(w, r)
    return text

def highlight_keywords(text):
    for kw in CONFIG['WHITELIST']:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(f'<span class="kw-highlight">\\g<0></span>', text)
    return text

def is_similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio() > 0.85

def fetch_data(feed_list):
    data_by_date, stats = {}, {}
    now_utc = datetime.datetime.now(pytz.utc)
    # 週末放寬至 72 小時確保資訊量
    limit_time = now_utc - datetime.timedelta(hours=72)
    seen_titles = []
    
    # 解決 PST/EST 等時區縮寫辨識問題
    tz_infos = {
        "PST": pytz.timezone("US/Pacific"),
        "PDT": pytz.timezone("US/Pacific"),
        "EST": pytz.timezone("US/Eastern"),
        "EDT": pytz.timezone("US/Eastern"),
        "JST": pytz.timezone("Asia/Tokyo"),
        "KST": pytz.timezone("Asia/Seoul"),
        "GMT": pytz.UTC
    }
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}
    
    # 黑名單防呆處理
    full_blacklist = [kw.lower() for kw in (CONFIG.get('BLACKLIST_GENERAL', []) + CONFIG.get('BLACKLIST_TECH_RELATED', [])) if kw and kw.strip()]
    
    for item in feed_list:
        url, tag = item['url'], item['tag']
        try:
            resp = requests.get(url, headers=headers, timeout=20, verify=False)
            resp.encoding = resp.apparent_encoding
            feed = feedparser.parse(resp.content)
            s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            if s_name not in stats: stats[s_name] = 0
            
            for entry in feed.entries[:20]:
                title = entry.title.strip()
                
                if any(kw in title.lower() for kw in full_blacklist): continue
                if any(is_similar(title, seen) for seen in seen_titles): continue
                
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                if not raw_date: continue
                try:
                    p_date = date_parser.parse(raw_date, tzinfos=tz_infos)
                    if p_date.tzinfo is None: p_date = pytz.utc.localize(p_date)
                    else: p_date = p_date.astimezone(pytz.utc)
                except: continue
                
                if p_date < limit_time: continue
                
                p_date_tw = p_date.astimezone(TW_TZ)
                date_str = p_date_tw.strftime('%Y-%m-%d')
                
                data_by_date.setdefault(date_str, []).append({
                    'raw_title': title, 'link': entry.link, 'source': s_name, 
                    'time': p_date_tw, 'tag_html': display_tag,
                    'is_analysis': "[分析]" in tag,
                    'raw_summary': clean_html(entry.get('summary', entry.get('description', "")))
                })
                seen_titles.append(title)
                stats[s_name] += 1
        except: continue
    return data_by_date, stats

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
                    art['display_title'] = art['tag_html'] + highlight_keywords(translated)
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
                    art['display_title'] = art['tag_html'] + highlight_keywords(fixed)
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
    if all_arts:
        sorted_t = sorted([a['time'] for a in all_arts])
        t_range = f"{sorted_t[0].strftime('%m/%d %H:%M')} ~ {sorted_t[-1].strftime('%m/%d %H:%M')}"
        stats_bar = f"<div class='column-stats'>總量：{len(all_arts)} 則報導 | 跨度：{t_range}</div>"
    else: stats_bar = "<div class='column-stats'>無新資訊</div>"

    html = f"<div class='river'><div class='river-title'>{title_prefix}</div>{stats_bar}"
    for d_str in sorted(daily_clusters.keys(), reverse=True):
        group_list = daily_clusters[d_str]
        daily_count = sum(len(g['articles']) for g in group_list)
        html += f"<div class='date-header'>{d_str} <span class='day-count'>({daily_count} 則)</span></div>"
        for group in group_list:
            first = group['articles'][0]
            safe_id = first['link'].replace('"', '&quot;')
            safe_sum = first.get('display_summary', "").replace('"', '&quot;')
            meta = f" — {first['source']} {first['time'].strftime('%H:%M')}"
            html += f"<div class='story-block {'priority' if group['priority'] else ''}' data-id=\"{safe_id}\" title=\"{safe_sum}\">"
            html += f"<div class='headline-wrapper'><span class='star-btn' onclick='toggleStar(\"{safe_id}\")'>★</span>"
            html += f"<a class='headline {'analysis-text' if first['is_analysis'] else ''}' href='{first['link']}' target='_blank'>{first['display_title']} <span class='source-tag'>{meta}</span></a></div>"
            if 'raw_title' in first and first['display_title'].find(first['raw_title']) == -1:
                html += f"<div class='original-title'>{first['raw_title']}</div>"
            for up in sorted(group['articles'][1:], key=lambda x: x['time'], reverse=True)[:5]:
                sub_t = up.get('translated_title', up['raw_title'])
                html += f"<a class='sub-link' href='{up['link']}' target='_blank'>↳ {up['source']}: {sub_t}</a>"
            html += "</div>"
    return html + "</div>"

def main():
    intl_raw, intl_st = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_raw, jk_st = fetch_data(CONFIG['FEEDS']['JK'])
    tw_raw, tw_st = fetch_data(CONFIG['FEEDS']['TW'])
    intl_cls = cluster_and_translate(intl_raw, need_trans=True)
    jk_cls = cluster_and_translate(jk_raw, need_trans=True)
    tw_cls = cluster_and_translate(tw_raw, need_trans=False)
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    all_st = {**intl_st, **jk_st, **tw_st}
    stats_html = "".join([f"<div class='stat-item'>{k}: <span>{v}</span></div>" for k, v in sorted(all_st.items())])
    full_html = f"""
    <html><head><meta charset='UTF-8'><title>{SITE_TITLE}</title><style>
        :root {{ --bg: #fff; --text: #333; --meta: #777; --border: #ddd; --hi: #ffff0033; --link: #1a0dab; --visited: #609; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #1a1a1a; --text: #ccc; --meta: #999; --border: #333; --hi: #ffd70033; --link: #8ab4f8; --visited: #c58af9; }} }}
        body {{ font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.2; }}
        .header {{ padding: 10px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; align-items: center; }}
        .controls {{ display: flex; gap: 10px; align-items: center; }}
        .filter-btn {{ cursor: pointer; padding: 3px 8px; border: 1px solid var(--text); font-size: 11px; font-weight: bold; background: var(--bg); color: var(--text); }}
        .filter-btn.active {{ background: #f1c40f; border-color: #f1c40f; color: #000; }}
        .column-stats {{ font-size: 10px; color: var(--meta); margin-bottom: 10px; padding-bottom: 5px; border-bottom: 1px dashed var(--border); font-family: monospace; }}
        .stats-summary {{ background: var(--bg); padding: 5px 20px; font-size: 11px; cursor: pointer; border-bottom: 1px solid var(--border); color: var(--meta); }}
        .stats-details {{ display: none; padding: 15px; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 5px; border-bottom: 1px solid var(--border); }}
        .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; width: 100%; max-width: 1900px; margin: 0 auto; gap: 1px; background: var(--border); min-height: 100vh; }}
        .river {{ background: var(--bg); padding: 10px 15px; }}
        .river-title {{ font-size: 17px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 5px; }}
        .date-header {{ background: #444; color: #fff; padding: 2px 8px; font-size: 11px; margin: 15px 0 5px; font-weight: bold; }}
        .day-count {{ float: right; opacity: 0.7; font-weight: normal; }}
        .story-block {{ padding: 8px 0; border-bottom: 1px solid var(--border); transition: background 0.2s; cursor: help; }}
        .story-block:hover {{ background: rgba(0,0,0,0.02); }}
        .badge {{ font-size: 10px; padding: 1px 4px; border-radius: 3px; font-weight: bold; }}
        .badge-分析 {{ background: #8e44ad; color: #fff; }}
        .badge-日 {{ background: #c0392b; color: #fff; }}
        .badge-韓 {{ background: #2980b9; color: #fff; }}
        .kw-highlight {{ background-color: var(--hi); border-radius: 2px; padding: 0 2px; font-weight: 600; color: #000; }}
        .analysis-text {{ color: #8e44ad !important; }}
        .headline {{ color: var(--link); text-decoration: none; font-size: 15px; font-weight: bold; }}
        .headline:visited {{ color: var(--visited); }}
        .sub-link {{ display: block; font-size: 11px; color: var(--link); opacity: 0.85; margin: 3px 0 0 22px; text-decoration: none; }}
        .sub-link:visited {{ color: var(--visited); }}
        .source-tag {{ font-size: 11px; color: var(--meta); font-weight: normal; }}
        .original-title {{ font-size: 11px; color: var(--meta); margin: 2px 0 4px 22px; }}
        .star-btn {{ cursor: pointer; color: #ccc; margin-right: 6px; transition: color 0.2s; }}
        .star-btn.active {{ color: #f1c40f; }}
        body.only-stars .story-block:not(.has-star) {{ display: none; }}
    </style></head><body>
        <div class='header'><h1>{SITE_TITLE}</h1><div class='controls'><div id='star-filter' class='filter-btn' onclick='toggleStarFilter()'>僅顯示星號 ★</div><div style="font-size:11px;">{now_str}</div></div></div>
        <div class="stats-summary" onclick="toggleStats()">📊 來源統計 <span id="toggle-txt">▼</span></div>
        <div id="stats-details" class="stats-details">{stats_html}</div>
        <div class='wrapper'>
            {render_column(intl_cls, "Global & Strategy")}
            {render_column(jk_cls, "Japan/Korea Tech")}
            {render_column(tw_cls, "Taiwan IT & Biz")}
        </div>
        <script>
            function toggleStats() {{ const p = document.getElementById('stats-details'); p.style.display = p.style.display === 'grid' ? 'none' : 'grid'; }}
            function toggleStarFilter() {{ document.getElementById('star-filter').classList.toggle('active'); document.body.classList.toggle('only-stars'); }}
            function toggleStar(link) {{
                let b = JSON.parse(localStorage.getItem('tech_bookmarks') || '[]');
                b.includes(link) ? b = b.filter(i => i !== link) : b.push(link);
                localStorage.setItem('tech_bookmarks', JSON.stringify(b));
                updateStarUI();
            }}
            function updateStarUI() {{
                const b = JSON.parse(localStorage.getItem('tech_bookmarks') || '[]');
                document.querySelectorAll('.story-block').forEach(el => {{
                    const isStarred = b.includes(el.getAttribute('data-id'));
                    el.querySelector('.star-btn').classList.toggle('active', isStarred);
                    el.classList.toggle('has-star', isStarred);
                }});
            }}
            document.addEventListener('DOMContentLoaded', updateStarUI);
        </script>
    </body></html>
    """
    save_cache(TRANS_CACHE)
    os.makedirs('output', exist_ok=True)
    with open('output/index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__": main()
