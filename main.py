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
SITE_TITLE = "珍的 IT 戰情室 | 2026.v1"

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
    it_fixes = {"副駕駛": "Copilot", "智能": "智慧", "數據": "資料", "服務器": "伺服器", "軟件": "軟體", "網絡": "網路", "信息": "資訊", "計算": "運算"}
    for w, r in it_fixes.items(): text = text.replace(w, r)
    return text

def highlight_keywords(text):
    for kw in CONFIG['WHITELIST']:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(f'<span class="kw-highlight">\\g<0></span>', text)
    return text

def is_similar(a, b): return difflib.SequenceMatcher(None, a, b).ratio() > 0.85

def fetch_html_fallback(name, url, selectors, tag_name):
    """強化 HTML 抓取：模擬 Session 與 Referer"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': url,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
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
            
        for item in items[:15]:
            title = item.get_text().strip()
            link = item.get('href')
            if not title or not link or len(title) < 5: continue
            if link.startswith('/'): link = "/".join(url.split('/')[:3]) + link
            articles.append({
                'raw_title': title, 'link': link, 'source': name,
                'time': datetime.datetime.now(TW_TZ), 'tag_html': tag_name,
                'is_analysis': "[分析]" in tag_name, 'raw_summary': ""
            })
    except: pass
    return articles

def fetch_data(feed_list):
    data_by_date, stats = {}, {}
    now_utc = datetime.datetime.now(pytz.utc)
    limit_time = now_utc - datetime.timedelta(hours=72)
    seen_titles = []
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
                    p_date = date_parser.parse(raw_date, tzinfos=TZ_INFOS).astimezone(pytz.utc)
                except: continue
                if p_date < limit_time: continue
                p_date_tw = p_date.astimezone(TW_TZ)
                date_str = p_date_tw.strftime('%Y-%m-%d')
                data_by_date.setdefault(date_str, []).append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date_tw, 'tag_html': tag, 'is_analysis': "[分析]" in tag, 'raw_summary': clean_html(entry.get('summary', ""))})
                seen_titles.append(title); stats[s_name] += 1
        except: continue
    return data_by_date, stats

# ... (cluster_and_translate 與 render_column 部分保持不變，可沿用之前程式碼) ...

def main():
    # 載入資料
    intl_raw, intl_st = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_raw, jk_st = fetch_data(CONFIG['FEEDS']['JK'])
    tw_raw, tw_st = fetch_data(CONFIG['FEEDS']['TW'])
    today_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d')

    # --- 針對性補抓 (精準攻擊 0 產出媒體) ---
    # Nikkei Asia: 嘗試多標籤
    nikkei_web = fetch_html_fallback('Nikkei Asia', 'https://asia.nikkei.com', ['h3 a', 'a[class*="title"]', '.n-card__title a'], '')
    if nikkei_web: intl_raw.setdefault(today_str, []).extend(nikkei_web); intl_st['Nikkei Asia'] = len(nikkei_web)

    # CIO Taiwan: 已救活，維持結構
    cio_web = fetch_html_fallback('CIO Taiwan', 'https://www.cio.com.tw', ['h3.entry-title a', 'article h3 a'], '[分析]')
    if cio_web: tw_raw.setdefault(today_str, []).extend(cio_web); tw_st['CIO Taiwan'] = len(cio_web)

    # 數位時代 (Meet 改抓主站)
    bnext_web = fetch_html_fallback('數位時代', 'https://www.bnext.com.tw/articles', ['a.item_title', '.item_box a'], '[數位]')
    if bnext_web: tw_raw.setdefault(today_str, []).extend(bnext_web); tw_st['數位時代'] = len(bnext_web)

    # ZDNet Japan: 關鍵修正點
    zdj_web = fetch_html_fallback('ZDNet Japan', 'https://japan.zdnet.com', ['section.content-list h3 a', 'h3 a', '.content-list__title a'], '[日]')
    if zdj_web: jk_raw.setdefault(today_str, []).extend(zdj_web); jk_st['ZDNet Japan'] = len(zdj_web)
    
    # IT Impress (日本)
    impress_web = fetch_html_fallback('Impress IT', 'https://it.impress.co.jp', ['div.article p.title a', 'p.title a'], '[日]')
    if impress_web: jk_raw.setdefault(today_str, []).extend(impress_web); jk_st['Impress IT'] = len(impress_web)

    # ... (後續翻譯、聚類、產出 index.html 邏輯) ...
    # (此處請務必保留您之前完整的 cluster_and_translate 與產出 HTML 字串邏輯)
    # ... 最後存檔 ...
    save_cache(TRANS_CACHE)
