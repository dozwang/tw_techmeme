import feedparser, datetime, pytz, os, difflib, requests, json, re, time, sys
from dateutil import parser as date_parser
from googletrans import Translator
from bs4 import BeautifulSoup
import google.generativeai as genai
import urllib3

# 確保在 GitHub Actions Log 中顯示中文不亂碼
if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 配置 ---
VERSION = "1.4.3"
SITE_TITLE = "豆子新聞戰情室"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')

TW_TZ = pytz.timezone('Asia/Taipei')
translator = Translator()
FINAL_STATS = {}

SOURCE_CLEAN_MAP = {
    "全記事新着 - 日経クロステック": "日經 XTECH",
    "日經 XTECH": "日經 XTECH",
    "IT - 전자신문": "韓國 ET News",
    "韓國 ET News": "韓國 ET News",
    "ITmedia NEWS": "ITmedia NEWS",
    "ZDNET Japan": "ZDNET Japan",
    "CIO Taiwan": "CIO Taiwan"
}

NOISE_WORDS = ["快訊", "獨家", "Breaking", "Live", "Update", "更新", "最新", "直擊", "影", "圖", "報導", "Exclusive", "發送提示", "點我看", "懶人包", "必讀", "完整清單", "轉貼", "整理", "推薦", "秒懂", "精選"]

def load_config():
    if os.path.exists('feeds.json'):
        try:
            with open('feeds.json', 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}, "WHITELIST": [], "TERM_MAP": {}}

CONFIG = load_config()

def translate_text(text):
    if not text: return ""
    try:
        res = translator.translate(text, dest='zh-tw').text
        term_map = CONFIG.get('TERM_MAP', {})
        for wrong, right in term_map.items(): res = res.replace(wrong, right)
        return res
    except: return text

def highlight_keywords(text):
    for kw in CONFIG.get('WHITELIST', []):
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(f'<span class="kw-highlight">\\g<0></span>', text)
    return text

def is_blacklisted(text):
    all_black = CONFIG.get('BLACKLIST_GENERAL', []) + CONFIG.get('BLACKLIST_TECH_RELATED', [])
    return any(word.lower() in text.lower() for word in all_black)

def clean_x_title(text):
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\s\S+\.(com|org|net|me|gov|io|edu|tv)(\/\S*)?\s?$', '', text)
    return text.strip().rstrip(' ;:,.')

def get_pure_title(title):
    temp = re.sub(r'【[^】]*】|\[[^\]]*\]', '', title)
    for noise in NOISE_WORDS: temp = temp.replace(noise, "")
    return re.sub(r'\s+', '', temp).strip()

def badge_styler(tag_str):
    if not tag_str: return ""
    clean_tags = re.findall(r'\[(.*?)\]', tag_str)
    badges = ""
    for t in clean_tags:
        cls = "badge-default"
        if t.upper() == "X": cls = "badge-x"
        elif "分析" in t: cls = "badge-analysis"
        elif "資安" in t: cls = "badge-sec"
        elif "日" in t: cls = "badge-jp"
        elif "韓" in t: cls = "badge-kr"
        elif "iThome" in t: cls = "badge-ithome"
        badges += f'<span class="badge {cls}">{t}</span>'
    return badges

def ask_gemini_if_same_event(title1, title2):
    if not GEMINI_KEY: return False
    prompt = f"作為專業編輯，判斷兩標題是否描述『同一個技術新聞事件』。相同回傳 YES，不同回傳 NO。只需回答 YES 或 NO。\n1: {title1}\n2: {title2}"
    try:
        response = gemini_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0))
        return "YES" in response.text.upper()
    except: return False

def cluster_articles(articles, is_tw=False):
    clusters = []
    soft_kw = CONFIG.get('WHITELIST', [])
    threshold = 0.30 if is_tw else 0.35
    for art in sorted(articles, key=lambda x: x['time']):
        pure_art_title = get_pure_title(art['raw_title'])
        best_match_idx = -1
        for idx, cluster in enumerate(clusters):
            main_title = get_pure_title(cluster[0]['raw_title'])
            sim = difflib.SequenceMatcher(None, main_title, pure_art_title).ratio()
            if any(kw in main_title and kw in pure_art_title for kw in soft_kw): sim += 0.20
            if sim > 0.70: best_match_idx = idx; break
            elif sim > threshold:
                if ask_gemini_if_same_event(main_title, pure_art_title): best_match_idx = idx; break
        if best_match_idx != -1: clusters[best_match_idx].insert(0, art)
        else: clusters.append([art])
    return sorted(clusters, key=lambda c: c[0]['time'], reverse=True)

def fetch_data(feed_list):
    all_articles = []
    now_tw = datetime.datetime.now(TW_TZ)
    limit_time = now_tw - datetime.timedelta(hours=96)
    for item in feed_list:
        url, tag = item['url'], item['tag']
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
            feed = feedparser.parse(resp.content)
            raw_s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            s_name = raw_s_name.split('|')[0].split('-')[0].strip()
            for key, clean_val in SOURCE_CLEAN_MAP.items():
                if key in raw_s_name: s_name = clean_val; break
            s_name = s_name[:18]
            
            for entry in feed.entries[:25]:
                title = clean_x_title(entry.title) if "nitter" in url else entry.title.strip()
                if is_blacklisted(title): continue
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                try: p_date = date_parser.parse(raw_date).astimezone(TW_TZ)
                except: p_date = now_tw
                if p_date < limit_time: continue
                all_articles.append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag_html': tag})
                FINAL_STATS[s_name] = FINAL_STATS.get(s_name, 0) + 1
        except: continue
    return all_articles

def render_clustered_html(clusters, need_trans=False):
    html = ""
    for group in clusters:
        main = group[0]
        display_title = highlight_keywords(translate_text(main['raw_title']) if need_trans else main['raw_title'])
        badges = badge_styler(main['tag_html'])
        link_hash = str(abs(hash(main['link'])))[:10]
        time_str = main['time'].strftime('%m/%d %H:%M')
        html += f"""
        <div class='story-block' id='sb-{link_hash}' data-link='{main['link']}'>
            <div class='headline-wrapper'>
                <span class='star-btn' onclick='toggleStar("{link_hash}")'>★</span>
                <div style='display: flex; align-items: flex-start; flex-grow: 1;'>
                    {badges}<a class='headline main-head' href='{main['link']}' target='_blank'>{display_title}</a>
                </div>
                <span class='btn-hide' onclick='toggleHide("{link_hash}")'>✕</span>
            </div>
            <div class='meta-line'>{main['source']} | {time_str}</div>
        """
        if len(group) > 1:
            html += "<div class='sub-news-list'>"
            seen_links = {main['link']}
            for sub in group[1:]:
                if sub['link'] in seen_links: continue
                sub_title = translate_text(sub['raw_title']) if need_trans else sub['raw_title']
                if sub_title == translate_text(main['raw_title']): continue 
                short_title = (sub_title[:45] + '...') if len(sub_title) > 48 else sub_title
                html += f"<div class='sub-item'>• <a href='{sub['link']}' target='_blank'>{short_title}</a> <span class='sub-meta'>({sub['source']})</span></div>"
                seen_links.add(sub['link'])
            html += "</div>"
        html += "</div>"
    return html

def main():
    now_tw_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    intl_list = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_list = fetch_data(CONFIG['FEEDS']['JK'])
    tw_list = fetch_data(CONFIG['FEEDS']['TW'])
    
    # 強攻站點
    special_sites = [("CIO Taiwan", "https://www.cio.com.tw/category/it-strategy/", ["h3 a"], "[分析]"), ("數位時代", "https://www.bnext.com.tw/articles", [".item_box", ".post_item"], "[數位]")]
    for name, url, sels, tag in special_sites:
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
            soup = BeautifulSoup(resp.text, 'html.parser')
            items = []
            for sel in sels:
                items = soup.select(sel)
                if items:
                    break
            for item in items[:10]:
                title_tag = item.select_one('.item_title, h3, a') if name == "數位時代" else item
                link_tag = title_tag if title_tag and title_tag.name == 'a' else (title_tag.find('a') if title_tag else None)
                if not link_tag: continue
                title = link_tag.get_text().strip()
                if not is_blacklisted(title):
                    tw_list.append({'raw_title': title, 'link': link_tag.get('href', ''), 'source': name, 'time': datetime.datetime.now(TW_TZ), 'tag_html': tag})
                    FINAL_STATS[name] = FINAL_STATS.get(name, 0) + 1
        except: pass

    stats_html = "".join([f"<li><span class='stats-label'>{k}</span><span class='stats-bar' style='width:{min(v*5, 100)}%'></span><span class='stats-val'>{v}</span></li>" for k, v in sorted(FINAL_STATS.items(), key=lambda x: x[1], reverse=True)])

    full_html = f"""
    <html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{SITE_TITLE}</title>
    <style>
        :root {{ --bg: #fff; --text: #3
