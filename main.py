import feedparser, datetime, pytz, os, difflib, requests, json, re, time, sys
from dateutil import parser as date_parser
from google import genai
from bs4 import BeautifulSoup
import urllib3

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 配置 ---
VERSION = "1.4.5"
SITE_TITLE = "豆子新聞戰情室"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

client = None
if GEMINI_KEY:
    client = genai.Client(api_key=GEMINI_KEY)

TW_TZ = pytz.timezone('Asia/Taipei')
# 修正 PST/PDT 識別問題
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}

SOURCE_CLEAN_MAP = {
    "全記事新着 - 日経クロステック": "日經 XTECH",
    "日経クロステック": "日經 XTECH",
    "IT - 전자신문": "韓國 ET News",
    "ITmedia NEWS": "ITmedia NEWS",
    "ZDNET Japan": "ZDNET Japan",
    "CIO Taiwan": "CIO Taiwan"
}

NOISE_WORDS = ["快訊", "獨家", "Breaking", "Live", "Update", "更新", "最新", "直擊", "影", "圖", "報導", "Exclusive", "發送提示", "點我看", "懶人包", "必讀", "轉貼", "整理", "推薦", "秒懂"]

def load_config():
    if os.path.exists('feeds.json'):
        try:
            with open('feeds.json', 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}, "WHITELIST": [], "TERM_MAP": {}}

CONFIG = load_config()

def translate_text(text):
    if not text: return ""
    from googletrans import Translator
    try:
        res = Translator().translate(text, dest='zh-tw').text
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
    return text.strip().rstrip(' ;:,.')

def badge_styler(tag_str):
    if not tag_str: return ""
    clean_tags = re.findall(r'\[(.*?)\]', tag_str)
    badges = ""
    for t in clean_tags:
        cls = "badge-default"
        if t.upper() == "X": cls = "badge-x"
        elif "分析" in t: cls = "badge-analysis"
        elif "日" in t: cls = "badge-jp"
        elif "韓" in t: cls = "badge-kr"
        elif "iThome" in t: cls = "badge-ithome"
        badges += f'<span class="badge {cls}">{t}</span>'
    return badges

def ask_gemini_if_same_event(title1, title2):
    if not client: return False
    prompt = f"判斷以下兩則標題是否描述『同一個技術新聞事件』。相同回答 YES，不同回答 NO。\n1: {title1}\n2: {title2}"
    try:
        response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
        return "YES" in response.text.upper()
    except: return False

def cluster_articles(articles, is_tw=False):
    clusters = []
    soft_kw = CONFIG.get('WHITELIST', [])
    threshold = 0.30 if is_tw else 0.35
    for art in sorted(articles, key=lambda x: x['time']):
        pure_title = re.sub(r'【[^】]*】|\[[^\]]*\]', '', art['raw_title']).strip()
        best_match_idx = -1
        for idx, cluster in enumerate(clusters):
            main_title = re.sub(r'【[^】]*】|\[[^\]]*\]', '', cluster[0]['raw_title']).strip()
            sim = difflib.SequenceMatcher(None, main_title, pure_title).ratio()
            if any(kw in main_title and kw in pure_title for kw in soft_kw): sim += 0.20
            if sim > 0.70: best_match_idx = idx; break
            elif sim > threshold:
                if ask_gemini_if_same_event(main_title, pure_title): best_match_idx = idx; break
        if best_match_idx != -1: clusters[best_match_idx].insert(0, art)
        else: clusters.append([art])
    return sorted(clusters, key=lambda c: c[0]['time'], reverse=True)

def fetch_data(feed_list):
    all_articles = []
    now_tw = datetime.datetime.now(TW_TZ)
    FINAL_STATS = {}
    for item in feed_list:
        url, tag = item['url'], item['tag']
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
            feed = feedparser.parse(resp.content)
            raw_s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            s_name = raw_s_name.split('|')[0].split('-')[0].strip()
            for key, clean_val in SOURCE_CLEAN_MAP.items():
                if key in raw_s_name: s_name = clean_val; break
            for entry in feed.entries[:20]:
                title = clean_x_title(entry.title)
                if is_blacklisted(title): continue
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                try: p_date = date_parser.parse(raw_date, tzinfos=TZ_INFOS).astimezone(TW_TZ)
                except: p_date = now_tw
                all_articles.append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag_html': tag})
        except: continue
    return all_articles

def main():
    now_tw_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    intl_list = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_list = fetch_data(CONFIG['FEEDS']['JK'])
    tw_list = fetch_data(CONFIG['FEEDS']['TW'])
    
    # 簡化 render 邏輯確保不報錯
    def render(clusters, need_trans):
        html = ""
        for g in clusters:
            m = g[0]
            t = highlight_keywords(translate_text(m['raw_title']) if need_trans else m['raw_title'])
            b = badge_styler(m['tag_html'])
            h = str(abs(hash(m['link'])))[:10]
            html += f"<div class='story-block' id='sb-{h}' data-link='{m['link']}'><div class='headline-wrapper'><span class='star-btn' onclick='toggleStar(\"{h}\")'>★</span><a class='main-head' href='{m['link']}' target='_blank'>{b}{t}</a><span class='btn-hide' onclick='toggleHide(\"{h}\")'>✕</span></div><div class='meta-line'>{m['source']} | {m['time'].strftime('%H:%M')}</div>"
            if len(g) > 1:
                html += "<div class='sub-news-list'>"
                for s in g[1:5]:
                    st = translate_text(s['raw_title']) if need_trans else s['raw_title']
                    html += f"<div class='sub-item'>• <a href='{s['link']}' target='_blank'>{st[:40]}...</a></div>"
                html += "</div>"
            html += "</div>"
        return html

    full_html = f"""
    <html><head><meta charset='UTF-8'><title>{SITE_TITLE}</title>
    <style>
        :root {{ --bg: #fff; --text: #333; --border: #eee; --link: #1a0dab; --hi: #ff98001a; --kw: #e67e22; --tag: #888; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #121212; --text: #e0e0e0; --border: #2c2c2c; --link: #8ab4f8; --tag: #9aa0a6; }} }}
        body {{ font-family: sans-serif; background: var(--bg); color: var(--text); margin: 0; padding-bottom: 50px; line-height: 1.4; }}
        .header {{ padding: 10px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); }}
        .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1px; background: var(--border); }}
        @media (max-width: 900px) {{ .wrapper {{ grid-template-columns: 1fr; }} }}
        .river {{ background: var(--bg); padding: 15px; }}
        .river-title {{ font-size: 18px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 15px; }}
        .story-block {{ padding: 12px 0; border-bottom: 1px solid var(--border); }}
        .story-block.is-hidden {{ display: none !important; }}
        body.show-hidden .story-block.is-hidden {{ display: block !important; opacity: 0.3; }}
        body.only-stars .story-block:not(.has-star) {{ display: none !important; }}
        .main-head {{ font-size: 15px; font-weight: 800; text-decoration: none; color: var(--link); }}
        .meta-line {{ font-size: 11px; color: var(--tag); margin-top: 4px; margin-left: 25px; }}
        .sub-news-list {{ margin: 5px 0 0 30px; border-left: 1px solid var(--border); padding-left: 10px; }}
        .sub-item {{ font-size: 12px; margin-bottom: 2px; }}
        .badge {{ padding: 1px 5px; font-size: 9px; border-radius: 3px; margin-right: 5px; color: #fff; font-weight: bold; }}
        .badge-x {{ background: #1da1f2; }} .badge-jp {{ background: #ff5722; }} .badge-kr {{ background: #303f9f; }} .badge-ithome {{ background: #d32f2f; }}
        .star-btn {{ cursor: pointer; color: #444; margin-right: 8px; }}
        .star-btn.active {{ color: #f1c40f; }}
        .btn-hide {{ cursor: pointer; color: var(--tag); float: right; font-size: 12px; }}
        .kw-highlight {{ color: var(--kw); font-weight: bold; background: #ff980010; }}
        .btn {{ cursor: pointer; padding: 4px 8px; border: 1px solid var(--border); font-size: 11px; background: var(--bg); color: var(--text); border-radius: 4px; }}
    </style></head><body>
        <div class='header'>
            <h1 style='margin:0; font-size:18px;'>{SITE_TITLE} v{VERSION}</h1>
            <div><span class='btn' onclick='location.reload()'>🔄</span> <span class='btn' onclick='document.body.classList.toggle("show-hidden")'>👁️</span> <span class='btn' onclick='document.body.classList.toggle("only-stars")'>★</span></div>
        </div>
        <div class='wrapper'>
            <div class='river'><div class='river-title'>Global</div>{render(cluster_articles(intl_list), True)}</div>
            <div class='river'><div class='river-title'>JK</div>{render(cluster_articles(jk_list), True)}</div>
            <div class='river'><div class='river-title'>Taiwan</div>{render(cluster_articles(tw_list, True), False)}</div>
        </div>
        <script>
            function toggleHide(h) {{
                const el = document.getElementById('sb-'+h);
                let hiddens = JSON.parse(localStorage.getItem('tech_hiddens')||'[]');
                const link = el.getAttribute('data-link');
                if(hiddens.includes(link)) hiddens = hiddens.filter(i=>i!==link);
                else hiddens.push(link);
                localStorage.setItem('tech_hiddens', JSON.stringify(hiddens));
                el.classList.toggle('is-hidden');
            }}
            function toggleStar(h) {{
                const el = document.getElementById('sb-'+h);
                const btn = el.querySelector('.star-btn');
                let stars = JSON.parse(localStorage.getItem('tech_stars')||'[]');
                const link = el.getAttribute('data-link');
                if(stars.includes(link)) {{
                    stars = stars.filter(i=>i!==link);
                    el.classList.remove('has-star');
                    btn.classList.remove('active');
                }} else {{
                    stars.push(link);
                    el.classList.add('has-star');
                    btn.classList.add('active');
                }}
                localStorage.setItem('tech_stars', JSON.stringify(stars));
            }}
            document.addEventListener('DOMContentLoaded', () => {{
                const h = JSON.parse(localStorage.getItem('tech_hiddens')||'[]');
                const s = JSON.parse(localStorage.getItem('tech_stars')||'[]');
                document.querySelectorAll('.story-block').forEach(el => {{
                    const link = el.getAttribute('data-link');
                    if(h.includes(link)) el.classList.add('is-hidden');
                    if(s.includes(link)) {{
                        el.classList.add('has-star');
                        el.querySelector('.star-btn').classList.add('active');
                    }}
                }});
            }});
        </script></body></html>
    """
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__":
    main()
