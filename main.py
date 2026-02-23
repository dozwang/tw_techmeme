import feedparser, datetime, pytz, os, difflib, requests, json, re, time, sys
from dateutil import parser as date_parser
from google import genai
from bs4 import BeautifulSoup
import urllib3

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 核心配置 ---
VERSION = "1.4.8"
SITE_TITLE = "豆子新聞戰情室"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

client = None
if GEMINI_KEY:
    client = genai.Client(api_key=GEMINI_KEY)

TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}

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
        for w, r in term_map.items(): res = res.replace(w, r)
        return res
    except: return text

def ask_gemini_if_same_event(title1, title2):
    if not client: return False
    prompt = f"判斷標題是否描述同一技術事件，回答 YES 或 NO：\n1: {title1}\n2: {title2}"
    try:
        response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
        return "YES" in response.text.upper()
    except: return False

def cluster_articles(articles, is_tw=False):
    clusters = []
    threshold = 0.30 if is_tw else 0.35
    for art in sorted(articles, key=lambda x: x['time']):
        pure_t = re.sub(r'【[^】]*】|\[[^\]]*\]', '', art['raw_title']).strip()
        best_match_idx = -1
        for idx, cluster in enumerate(clusters):
            main_t = re.sub(r'【[^】]*】|\[[^\]]*\]', '', cluster[0]['raw_title']).strip()
            sim = difflib.SequenceMatcher(None, main_t, pure_t).ratio()
            if sim > 0.70: best_match_idx = idx; break
            elif sim > threshold:
                if ask_gemini_if_same_event(main_t, pure_t): best_match_idx = idx; break
        if best_match_idx != -1: clusters[best_match_idx].insert(0, art)
        else: clusters.append([art])
    return sorted(clusters, key=lambda c: c[0]['time'], reverse=True)

def fetch_data(feed_list):
    all_articles = []
    now_tw = datetime.datetime.now(TW_TZ)
    for item in feed_list:
        try:
            resp = requests.get(item['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
            feed = feedparser.parse(resp.content)
            s_name = (feed.feed.title if 'title' in feed.feed else item['url'].split('/')[2]).split('|')[0].strip()[:18]
            for entry in feed.entries[:20]:
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                try: p_date = date_parser.parse(raw_date, tzinfos=TZ_INFOS).astimezone(TW_TZ)
                except: p_date = now_tw
                all_articles.append({'raw_title': entry.title.strip(), 'link': entry.link, 'source': s_name, 'time': p_date, 'tag_html': item['tag']})
        except: continue
    return all_articles

def main():
    print(f"Starting {SITE_TITLE} v{VERSION}")
    intl = fetch_data(CONFIG['FEEDS']['INTL'])
    jk = fetch_data(CONFIG['FEEDS']['JK'])
    tw = fetch_data(CONFIG['FEEDS']['TW'])
    
    def render(clusters, trans):
        h_html = ""
        for g in clusters:
            m = g[0]; t = translate_text(m['raw_title']) if trans else m['raw_title']
            hid = str(abs(hash(m['link'])))[:10]
            h_html += f"<div class='story-block' id='sb-{hid}' data-link='{m['link']}'><div class='headline-wrapper'><span class='star-btn' onclick='toggleStar(\"{hid}\")'>★</span><a class='main-head' href='{m['link']}' target='_blank'>{t}</a><span class='btn-hide' onclick='toggleHide(\"{hid}\")'>✕</span></div><div class='meta-line'>{m['source']} | {m['time'].strftime('%H:%M')}</div></div>"
        return h_html

    full_html = f"""
    <html><head><meta charset='UTF-8'><title>{SITE_TITLE}</title>
    <style>
        :root {{ --bg: #fff; --text: #333; --link: #1a0dab; --border: #eee; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #121212; --text: #e0e0e0; --link: #8ab4f8; --border: #2c2c2c; }} }}
        body {{ font-family: sans-serif; background: var(--bg); color: var(--text); margin: 0; padding-bottom: 50px; }}
        .header {{ padding: 10px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); }}
        .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1px; background: var(--border); }}
        @media (max-width: 900px) {{ .wrapper {{ grid-template-columns: 1fr; }} }}
        .river {{ background: var(--bg); padding: 15px; }}
        .story-block {{ padding: 10px 0; border-bottom: 1px solid var(--border); }}
        .story-block.is-hidden {{ display: none !important; }}
        body.show-hidden .story-block.is-hidden {{ display: block !important; opacity: 0.3; }}
        .main-head {{ font-size: 15px; font-weight: 800; text-decoration: none; color: var(--link); }}
        .meta-line {{ font-size: 11px; color: #888; margin-top: 4px; margin-left: 25px; }}
        .star-btn {{ cursor: pointer; color: #444; margin-right: 8px; }}
        .star-btn.active {{ color: #f1c40f; }}
        .btn-hide {{ cursor: pointer; float: right; font-size: 12px; opacity: 0.5; }}
        .btn {{ cursor: pointer; padding: 4px 8px; border: 1px solid var(--border); font-size: 11px; background: var(--bg); color: var(--text); border-radius: 4px; }}
    </style></head><body>
        <div class='header'><h1 style='margin:0; font-size:18px;'>{SITE_TITLE} v{VERSION}</h1><div><span class='btn' onclick='location.reload()'>🔄</span> <span class='btn' onclick='document.body.classList.toggle("show-hidden")'>👁️</span></div></div>
        <div class='wrapper'>
            <div class='river'><h3>Global</h3>{render(cluster_articles(intl), True)}</div>
            <div class='river'><h3>JK</h3>{render(cluster_articles(jk), True)}</div>
            <div class='river'><h3>Taiwan</h3>{render(cluster_articles(tw, True), False)}</div>
        </div>
        <script>
            function toggleHide(h) {{
                const el = document.getElementById('sb-'+h); const l = el.getAttribute('data-link');
                let hds = JSON.parse(localStorage.getItem('tech_hiddens')||'[]');
                if(hds.includes(l)) hds = hds.filter(i=>i!==l); else hds.push(l);
                localStorage.setItem('tech_hiddens', JSON.stringify(hds)); el.classList.toggle('is-hidden');
            }}
            function toggleStar(h) {{
                const el = document.getElementById('sb-'+h); const btn = el.querySelector('.star-btn'); const l = el.getAttribute('data-link');
                let s = JSON.parse(localStorage.getItem('tech_stars')||'[]');
                if(s.includes(l)) {{ s=s.filter(i=>i!==l); btn.classList.remove('active'); }} else {{ s.push(l); btn.classList.add('active'); }}
                localStorage.setItem('tech_stars', JSON.stringify(s));
            }}
            document.addEventListener('DOMContentLoaded', () => {{
                const h = JSON.parse(localStorage.getItem('tech_hiddens')||'[]');
                const s = JSON.parse(localStorage.getItem('tech_stars')||'[]');
                document.querySelectorAll('.story-block').forEach(el => {{
                    const l = el.getAttribute('data-link');
                    if(h.includes(l)) el.classList.add('is-hidden');
                    if(s.includes(l)) el.querySelector('.star-btn').classList.add('active');
                }});
            }});
        </script></body></html>
    """
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)
    print("Done writing index.html")

if __name__ == "__main__":
    main()
