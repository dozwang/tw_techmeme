import feedparser, datetime, pytz, os, difflib, requests, json, re, time, sys
from dateutil import parser as date_parser
from google import genai
from bs4 import BeautifulSoup
import urllib3

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 配置 ---
VERSION = "2.0.4"
SITE_TITLE = "豆子新聞戰情室"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

client = None
if GEMINI_KEY:
    client = genai.Client(api_key=GEMINI_KEY)

TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}
FINAL_STATS = {}
TOTAL_TOKENS = 0

def load_config():
    if os.path.exists('feeds.json'):
        try:
            with open('feeds.json', 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                for zone in ["INTL", "JK", "TW"]:
                    cfg["FEEDS"][zone] = [i for i in cfg["FEEDS"][zone] if "bnextmedia" not in i["url"]]
                return cfg
        except: pass
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}, "WHITELIST": [], "TERM_MAP": {}, "BLACKLIST_GENERAL": [], "BLACKLIST_TECH_RELATED": []}

CONFIG = load_config()

def translate_text(text):
    if not text: return ""
    # 強力過濾雜訊
    text = re.sub(r'發送提示！|📩|https?://\S+', '', text).strip()
    if not text: return ""
    if not re.search(r'[\u4e00-\u9fff]', text):
        from googletrans import Translator
        try:
            res = Translator().translate(text, dest='zh-tw').text
            if res:
                for old, new in CONFIG.get('TERM_MAP', {}).items():
                    res = res.replace(old, new)
                return res
        except: return text
    return text

def get_company_clusters(articles):
    """【v2.0.4 強力聚合】強制標籤化分類，解決 Anthropic 分散問題"""
    global TOTAL_TOKENS
    if not client or not articles: return [[a] for a in articles]
    TOTAL_TOKENS += 1500
    titles_input = "\n".join([f"{i}: {a['raw_title']}" for i, a in enumerate(articles)])
    prompt = f"""
    任務：將標題依照『核心主體公司』進行分類。
    【重要】：不管動作為何，只要主體是同一家公司(如 Anthropic, OpenAI, SKT)就必須分在同一組。
    回傳編號，範例：
    [0, 5, 10]
    [1, 4]
    
    【清單】：
    {titles_input}
    """
    try:
        response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt, config={'temperature': 0.0})
        groups = []
        used = set()
        matches = re.findall(r'\[(.*?)\]', response.text)
        for m in matches:
            idx_list = [int(i.strip()) for i in m.split(',') if i.strip().isdigit()]
            group = []
            for idx in idx_list:
                if idx < len(articles) and idx not in used:
                    group.append(articles[idx]); used.add(idx)
            if group: groups.append(group)
        for i, a in enumerate(articles):
            if i not in used: groups.append([a])
        return groups
    except: return [[a] for a in articles]

def fetch_data(feed_list):
    global TOTAL_TOKENS
    all_articles = []
    now_tw = datetime.datetime.now(TW_TZ)
    limit_date = now_tw - datetime.timedelta(days=4) # 只抓 4 天內
    bl = CONFIG.get("BLACKLIST_GENERAL", []) + CONFIG.get("BLACKLIST_TECH_RELATED", [])
    for item in feed_list:
        try:
            resp = requests.get(item['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=25, verify=False)
            feed = feedparser.parse(resp.content)
            s_name = (feed.feed.title if 'title' in feed.feed else item['url'].split('/')[2]).split('|')[0].strip()[:12]
            for entry in feed.entries[:15]:
                title = re.sub(r'https?://\S+|發送提示！|📩', '', entry.title).strip()
                if not title or any(b in title for b in bl): continue
                try: p_date = date_parser.parse(entry.get('published', entry.get('pubDate', entry.get('updated', None))), tzinfos=TZ_INFOS).astimezone(TW_TZ)
                except: p_date = now_tw
                if p_date < limit_date: continue
                TOTAL_TOKENS += 50
                all_articles.append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag': item['tag']})
                FINAL_STATS[s_name] = FINAL_STATS.get(s_name, 0) + 1
        except: continue
    return all_articles

def main():
    intl = get_company_clusters(fetch_data(CONFIG['FEEDS']['INTL']))
    jk = get_company_clusters(fetch_data(CONFIG['FEEDS']['JK']))
    tw = get_company_clusters(fetch_data(CONFIG['FEEDS']['TW']))

    def render(clusters):
        html = ""
        for g in sorted(clusters, key=lambda x: x[0]['time'], reverse=True):
            m = g[0]
            main_t = translate_text(m['raw_title'])
            hid = str(abs(hash(m['link'])))[:10]
            badge = f'<span class="badge-ithome">iThome</span>' if "iThome" in m['tag'] else (f'<span class="badge-tag">{m["tag"]}</span>' if m["tag"] else "")
            ts = int(m['time'].timestamp())
            
            html += f"""
            <div class='story-block' id='sb-{hid}' data-link='{m['link']}' data-ts='{ts}'>
                <div class='headline-wrapper'>
                    <span class='star-btn' onclick='toggleStar("{hid}")'>★</span>
                    <div class='head-content'>
                        <div class='title-row'>
                            {badge}<a class='headline' href='{m['link']}' target='_blank'>{main_t}</a>
                        </div>
                    </div>
                    <span class='btn-hide' onclick='toggleHide("{hid}")'>✕</span>
                </div>
                <div class='meta-line'>{m['source']} | {m['time'].strftime('%m/%d %H:%M')}</div>
            """
            if len(g) > 1:
                html += "<div class='sub-news-list'>"
                for s in g[1:6]:
                    sub_t = translate_text(s['raw_title'])
                    html += f"<div class='sub-item'>• <a href='{s['link']}' target='_blank'>{sub_t[:55]}...</a> <small>({s['source']})</small></div>"
                html += "</div>"
            html += "</div>"
        return html

    full_html = f"""
    <html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{SITE_TITLE}</title>
    <style>
        :root {{ --bg: #fff; --text: #333; --border: #eee; --link: #1a0dab; --hi: #3498db; --tag: #888; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #121212; --text: #e0e0e0; --border: #2c2c2c; --link: #8ab4f8; --tag: #9aa0a6; }} }}
        * {{ box-sizing: border-box; }}
        body {{ font-family: sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0 15px 50px 15px; line-height: 1.4; }}
        .header {{ padding: 10px 0; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 1000; }}
        .wrapper {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }}
        @media (max-width: 900px) {{ .wrapper {{ grid-template-columns: 1fr; }} }}
        .river-title {{ font-size: 16px; font-weight: 900; border-bottom: 2px solid var(--text); margin: 10px 0; }}
        .story-block {{ padding: 12px 0; border-bottom: 1px solid var(--border); }}
        .story-block.is-hidden {{ display: none; }}
        body.show-hidden .story-block.is-hidden {{ display: block !important; opacity: 0.4; }}
        .headline-wrapper {{ display: flex; align-items: flex-start; gap: 8px; }}
        .head-content {{ flex-grow: 1; min-width: 0; }}
        .title-row {{ display: flex; align-items: flex-start; gap: 5px; }}
        .headline {{ font-size: 14.5px; font-weight: 800; text-decoration: none; color: var(--link); }}
        .meta-line {{ font-size: 10px; color: var(--tag); margin-top: 5px; margin-left: 23px; }}
        .sub-news-list {{ margin: 6px 0 0 23px; border-left: 1px solid var(--border); padding-left: 10px; }}
        .sub-item {{ font-size: 12px; margin-bottom: 3px; }}
        .badge-tag, .badge-ithome {{ color: #fff; padding: 1px 4px; font-size: 8.5px; border-radius: 2px; flex-shrink: 0; }}
        .badge-tag {{ background: #888; }} .badge-ithome {{ background: var(--hi); font-weight: 800; }}
        .star-btn {{ cursor: pointer; color: var(--tag); font-size: 14px; }}
        .btn-hide {{ cursor: pointer; color: var(--tag); font-size: 11px; opacity: 0.4; margin-left: auto; }}
        .btn {{ cursor: pointer; padding: 4px 10px; border: 1px solid var(--border); font-size: 11px; border-radius: 4px; background: var(--bg); color: var(--text); font-weight: bold; }}
    </style></head><body>
        <div class='header'>
            <h1 style='margin:0; font-size:16px;'>{SITE_TITLE} v{VERSION}</h1>
            <div style='display:flex; gap:8px;'>
                <span class='btn' onclick='document.body.classList.toggle("show-hidden")'>👁️ 恢復/隱藏已讀</span>
                <span class='btn' onclick='location.reload()'>🔄</span>
            </div>
        </div>
        <div class='wrapper'>
            <div class='river'><div class='river-title'>Global</div>{render(intl)}</div>
            <div class='river'><div class='river-title'>JK</div>{render(jk)}</div>
            <div class='river'><div class='river-title'>Taiwan</div>{render(tw)}</div>
        </div>
        <script>
            function toggleHide(h) {{
                const el = document.getElementById('sb-'+h);
                const link = el.getAttribute('data-link');
                const ts = el.getAttribute('data-ts');
                let hiddens = JSON.parse(localStorage.getItem('tech_hiddens_v3') || '[]');
                if(!hiddens.some(i => i.l === link)) hiddens.push({{l: link, t: ts}});
                localStorage.setItem('tech_hiddens_v3', JSON.stringify(hiddens));
                el.classList.add('is-hidden');
            }}
            function toggleStar(h) {{
                const el = document.getElementById('sb-'+h);
                const btn = el.querySelector('.star-btn');
                const link = el.getAttribute('data-link');
                const ts = el.getAttribute('data-ts');
                let stars = JSON.parse(localStorage.getItem('tech_stars_v3') || '[]');
                const idx = stars.findIndex(i => i.l === link);
                if(idx > -1) {{ stars.splice(idx, 1); btn.style.color = ''; }}
                else {{ stars.push({{l: link, t: ts}}); btn.style.color = '#f1c40f'; }}
                localStorage.setItem('tech_stars_v3', JSON.stringify(stars));
            }}
            document.addEventListener('DOMContentLoaded', () => {{
                const now = Math.floor(Date.now() / 1000);
                let hiddens = JSON.parse(localStorage.getItem('tech_hiddens_v3') || '[]');
                let stars = JSON.parse(localStorage.getItem('tech_stars_v3') || '[]');
                hiddens = hiddens.filter(i => (now - i.t) < 604800);
                stars = stars.filter(i => (now - i.t) < 604800);
                localStorage.setItem('tech_hiddens_v3', JSON.stringify(hiddens));
                localStorage.setItem('tech_stars_v3', JSON.stringify(stars));
                document.querySelectorAll('.story-block').forEach(el => {{
                    const link = el.getAttribute('data-link');
                    if(hiddens.some(i => i.l === link)) el.classList.add('is-hidden');
                    if(stars.some(i => i.l === link)) el.querySelector('.star-btn').style.color = '#f1c40f';
                }});
            }});
        </script></body></html>
    """
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__":
    main()
