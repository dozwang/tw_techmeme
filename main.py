import feedparser, datetime, pytz, os, difflib, requests, json, re
from dateutil import parser as date_parser
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from googletrans import Translator
from bs4 import BeautifulSoup
import urllib3

# 停用不安全連線警告
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
    it_fixes = {"副駕駛": "Copilot", "智能": "智慧", "數據": "資料", "服務器": "伺服器", "軟件": "軟體", "網絡": "網路", "信息": "資訊", "雲端原生": "雲原生"}
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

def fetch_bnext_custom():
    """進階抓取：解析數位時代文章列表頁 HTML"""
    url = "https://www.bnext.com.tw/articles"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Referer': 'https://www.google.com/'
    }
    articles = []
    try:
        resp = requests.get(url, headers=headers, timeout=30, verify=False)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        # 根據數位時代目前結構定位文章標題連結
        items = soup.select('a.item_title') or soup.select('.item_box a')
        for item in items[:12]:
            title = item.get_text().strip()
            link = item.get('href')
            if not title or not link: continue
            if link.startswith('/'): link = "https://www.bnext.com.tw" + link
            articles.append({
                'raw_title': title, 'link': link, 'source': '數位時代(Web)', 
                'time': datetime.datetime.now(TW_TZ), 'tag_html': '[數位]', 
                'is_analysis': False, 'raw_summary': ""
            })
    except Exception as e:
        print(f"Bnext Scraping Error: {e}")
    return articles

def fetch_data(feed_list):
    data_by_date, stats = {}, {}
    now_utc = datetime.datetime.now(pytz.utc)
    limit_time = now_utc - datetime.timedelta(hours=72)
    seen_titles = []
    tz_infos = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific"), "JST": pytz.timezone("Asia/Tokyo"), "GMT": pytz.UTC}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}
    full_blacklist = [kw.lower().strip() for kw in (CONFIG.get('BLACKLIST_GENERAL', []) + CONFIG.get('BLACKLIST_TECH_RELATED', [])) if kw]
    
    for item in feed_list:
        url, tag = item['url'], item['tag']
        try:
            resp = requests.get(url, headers=headers, timeout=25, verify=False)
            feed = feedparser.parse(resp.content)
            s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            stats[s_name] = 0
            for entry in feed.entries[:20]:
                title = entry.title.strip()
                if any(kw in title.lower() for kw in full_blacklist): continue
                if any(is_similar(title, seen) for seen in seen_titles): continue
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                try:
                    p_date = date_parser.parse(raw_date, tzinfos=tz_infos)
                    p_date = p_date.astimezone(pytz.utc) if p_date.tzinfo else pytz.utc.localize(p_date)
                except: continue
                if p_date < limit_time: continue
                p_date_tw = p_date.astimezone(TW_TZ)
                date_str = p_date_tw.strftime('%Y-%m-%d')
                data_by_date.setdefault(date_str, []).append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date_tw, 'tag_html': tag, 'is_analysis': "[分析]" in tag, 'raw_summary': clean_html(entry.get('summary', ""))})
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
            for up in sorted(group['articles'][1:], key=lambda x: x['time'], reverse=True)[:5]:
                html += f"<a class='sub-link' href='{up['link']}' target='_blank'>↳ {up['source']}: {up.get('translated_title', up['raw_title'])}</a>"
            html += "</div>"
    return html + "</div>"

def main():
    intl_raw, intl_st = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_raw, jk_st = fetch_data(CONFIG['FEEDS']['JK'])
    tw_raw, tw_st = fetch_data(CONFIG['FEEDS']['TW'])
    
    # 增加數位時代進階抓取
    bnext_web = fetch_bnext_custom()
    if bnext_web:
        today_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d')
        tw_raw.setdefault(today_str, []).extend(bnext_web)
        tw_st['數位時代(Web)'] = len(bnext_web)

    intl_cls, jk_cls, tw_cls = cluster_and_translate(intl_raw, True), cluster_and_translate(jk_raw, True), cluster_and_translate(tw_raw, False)
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    all_st = {**intl_st, **jk_st, **tw_st}
    stats_items = [f"<div class='stat-row'><span class='stat-name'>{k}</span><div class='stat-bar-container'><div class='stat-bar-fill' style='width: {min(v*4,100)}%; background: {'var(--accent)' if v>0 else '#e74c3c'}'></div></div><span class='stat-count'>{v}</span></div>" for k, v in sorted(all_st.items(), key=lambda x: x[1], reverse=True)]
    
    # 此處省略 HTML Template (保持與之前一致) ... 僅更新最後寫入
    # (請確認 CSS 部分包含 .stat-row 等樣式)
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html) # full_html 為組合好的字串
    save_cache(TRANS_CACHE)

if __name__ == "__main__": main()
