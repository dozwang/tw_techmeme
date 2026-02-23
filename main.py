import feedparser, datetime, pytz, os, difflib, requests, json, re, time, sys
from dateutil import parser as date_parser
from googletrans import Translator
from bs4 import BeautifulSoup
import google.generativeai as genai
import urllib3

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 配置 ---
VERSION = "1.3.3"
SITE_TITLE = "豆子新聞戰情室"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')

TW_TZ = pytz.timezone('Asia/Taipei')
translator = Translator()

NOISE_WORDS = ["快訊", "獨家", "Breaking", "Live", "Update", "更新", "最新", "直擊", "影", "圖", "報導", "Exclusive", "發送提示", "點我看", "懶人包", "必讀", "完整清單", "轉貼", "整理", "推薦", "秒懂"]

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
        if "X" in t: cls = "badge-x"
        elif "分析" in t: cls = "badge-analysis"
        elif "資安" in t: cls = "badge-sec"
        elif "日" in t: cls = "badge-jp"
        elif "韓" in t: cls = "badge-kr"
        elif "數位" in t: cls = "badge-digital"
        badges += f'<span class="badge {cls}">{t}</span>'
    return badges

def ask_gemini_if_same_event(title1, title2):
    if not GEMINI_KEY: return False
    prompt = f"判斷以下兩則標題是否描述『同一個核心技術新聞事件』。只需回答 YES 或 NO。\n1: {title1}\n2: {title2}"
    try:
        response = gemini_model.generate_content(prompt)
        return "YES" in response.text.upper()
    except: return False

def cluster_articles(articles):
    clusters = []
    soft_kw = ["軟體", "開發", "程式", "GitHub", "API", "架構", "DevOps", "AI", "Agent", "K8s"]
    for art in sorted(articles, key=lambda x: x['time']):
        pure_art_title = get_pure_title(art['raw_title'])
        best_match_idx = -1
        for idx, cluster in enumerate(clusters):
            main_title = get_pure_title(cluster[0]['raw_title'])
            sim = difflib.SequenceMatcher(None, main_title, pure_art_title).ratio()
            if any(kw in main_title and kw in pure_art_title for kw in soft_kw): sim += 0.18
            if sim > 0.65: best_match_idx = idx; break
            elif sim > 0.32:
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
            s_name = (feed.feed.title if 'title' in feed.feed else url.split('/')[2]).split('|')[0].strip()[:18]
            for entry in feed.entries[:25]:
                title = clean_x_title(entry.title) if "nitter" in url else entry.title.strip()
                if is_blacklisted(title): continue
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                try: p_date = date_parser.parse(raw_date).astimezone(TW_TZ)
                except: p_date = now_tw
                if p_date < limit_time: continue
                all_articles.append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag_html': tag})
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
        html += f"<div class='story-block' id='sb-{link_hash}' data-link='{main['link']}'><div class='headline-wrapper'><span class='star-btn' onclick='toggleStar(\"{link_hash}\")'>★</span><div style='display: flex; align-items: flex-start;'>{badges}<a class='headline main-head' href='{main['link']}' target='_blank'>{display_title}</a></div></div><div class='meta-line'>{main['source']} | {time_str}</div>"
        if len(group) > 1:
            html += "<div class='sub-news-list'>"
            seen_links = {main['link']}
            for sub in group[1:]:
                if sub['link'] in seen_links: continue
                sub_title = translate_text(sub['raw_title']) if need_trans else sub['raw_title']
                if sub_title == translate_text(main['raw_title']): continue 
                html += f"<div class='sub-item'>• <a href='{sub['link']}' target='_blank'>{sub_title}</a> <span class='sub-meta'>({sub['source']})</span></div>"
                seen_links.add(sub['link'])
            html += "</div>"
        html += "</div>"
    return html

def main():
    now_tw_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    intl_list = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_list = fetch_data(CONFIG['FEEDS']['JK'])
    tw_list = fetch_data(CONFIG['FEEDS']['TW'])
    
    special_sites = [("CIO Taiwan", "https://www.cio.com.tw/category/it-strategy/", ["h3 a"], "[分析]"), ("數位時代", "https://www.bnext.com.tw/articles", [".item_box", ".post_item"], "[數位]")]
    for name, url, sels, tag in special_sites:
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
            soup = BeautifulSoup(resp.text, 'html.parser')
            items = []
            for sel in sels:
                items = soup.select(sel)
                if items: break
            for item in items[:10]:
                title_tag = item.select_one('.item_title, h3, a') if name == "數位時代" else item
                link_tag = title_tag if title_tag and title_tag.name == 'a' else (title_tag.find('a') if title_tag else None)
                if not link_tag: continue
                title = link_tag.get_text().strip()
                if not is_blacklisted(title):
                    tw_list.append({'raw_title': title, 'link': link_tag.get('href', ''), 'source': name, 'time': datetime.datetime.now(TW_TZ), 'tag_html': tag})
        except: pass

    full_html = f"<html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{SITE_TITLE}</title><style>:root {{ --bg: #fff; --text: #333; --border: #eee; --link: #1a0dab; --hi: #ff98001a; --kw: #e67e22; --tag: #888; }} @media (prefers-color-scheme: dark) {{ :root {{ --bg: #111; --text: #ddd; --border: #222; --link: #8ab4f8; --tag: #777; }} }} body {{ font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.4; padding-bottom: 50px; }} .header {{ padding: 12px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 1000; }} .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1px; background: var(--border); }} @media (max-width: 900px) {{ .wrapper {{ grid-template-columns: 1fr; }} }} .river {{ background: var(--bg); padding: 14px; }} .river-title {{ font-size: 18px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 15px; }} .story-block {{ padding: 12px 0; border-bottom: 1px solid var(--border); }} .main-head {{ font-size: 15px; font-weight: 800; text-decoration: none; color: var(--link); }} .meta-line {{ font-size: 11px; color: var(--tag); margin-top: 4px; margin-left: 28px; }} .sub-news-list {{ margin: 6px 0 0 35px; border-left: 2px solid var(--border); padding-left: 10px; }} .sub-item {{ font-size: 12px; margin-bottom: 3px; color: var(--text); }} .sub-item a {{ text-decoration: none; color: var(--text); }} .sub-meta {{ font-size: 10px; color: var(--tag); }} .badge {{ display: inline-block; padding: 1px 6px; font-size: 10px; border-radius: 4px; margin-right: 6px; font-weight: 800; white-space: nowrap; height: 18px; margin-top: 2px; color: #fff !important; }} .badge-x {{ background: #1da1f2 !important; }} .badge-jp {{ background: #ff5722 !important; }} .badge-kr {{ background: #303f9f !important; }} .badge-digital {{ background: #27ae60 !important; }} .badge-analysis {{ background: #673ab7 !important; }} .badge-sec {{ background: #e91e63 !important; }} .badge-default {{ background: #888 !important; }} .star-btn {{ cursor: pointer; color: #ddd; font-size: 18px; margin-right: 10px; float: left; }} .star-btn.active {{ color: #f1c40f; }} .kw-highlight {{ color: var(--kw); font-weight: bold; background: #ff980015; }} .btn {{ cursor: pointer; padding: 5px 12px; border: 1px solid var(--text); font-size: 11px; border-radius: 6px; background: var(--bg); color: var(--text); font-weight: bold; }}</style></head><body><div class='header'><h1 style='margin:0; font-size:20px;'>{SITE_TITLE}</h1><div><span style='font-size:10px; color:var(--tag); margin-right:10px;'>{now_tw_str}</span><span class='btn' onclick='document.body.classList.toggle(\"only-stars\")'>★ 精選</span></div></div><div class='wrapper'><div class='river'><div class='river-title'>Global Strategy</div>{render_clustered_html(cluster_articles(intl_list), True)}</div><div class='river'><div class='river-title'>Japan/Korea</div>{render_clustered_html(cluster_articles(jk_list), True)}</div><div class='river'><div class='river-title'>Taiwan Tech</div>{render_clustered_html(cluster_articles(tw_list), False)}</div></div><script>function toggleStar(h) {{ const el = document.getElementById('sb-'+h); const btn = el.querySelector('.star-btn'); const link = el.getAttribute('data-link'); let s = JSON.parse(localStorage.getItem('tech_stars')||'[]'); if(s.includes(link)) {{ s=s.filter(i=>i!==link); el.classList.remove('has-star'); btn.classList.remove('active'); }} else {{ s.push(link); el.classList.add('has-star'); btn.classList.add('active'); }} localStorage.setItem('tech_stars', JSON.stringify(s)); }} document.addEventListener('DOMContentLoaded', () => {{ const s = JSON.parse(localStorage.getItem('tech_stars')||'[]'); document.querySelectorAll('.story-block').forEach(el => {{ if(s.includes(el.getAttribute('data-link'))) {{ el.classList.add('has-star'); el.querySelector('.star-btn').classList.add('active'); }} }}); }});</script></body></html>"
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__":
    main()
