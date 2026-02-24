import feedparser, datetime, pytz, os, difflib, requests, json, re, time, sys
from dateutil import parser as date_parser
from google import genai
from bs4 import BeautifulSoup
import urllib3

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 核心配置 ---
VERSION = "1.7.1"
SITE_TITLE = "豆子新聞戰情室"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

client = None
if GEMINI_KEY:
    client = genai.Client(api_key=GEMINI_KEY)

TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}
FINAL_STATS = {}

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
        for w, r in CONFIG.get('TERM_MAP', {}).items(): res = res.replace(w, r)
        return res
    except: return text

def highlight_keywords(text):
    for kw in CONFIG.get('WHITELIST', []):
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(f'<span class="kw-highlight">\\g<0></span>', text)
    return text

def batch_cluster_with_gemini(articles):
    """一次將整區標題丟給 Gemini 進行語義分類，節省 Token 並提高準確度"""
    if not client or not articles or len(articles) < 2:
        return [[a] for a in articles]

    titles_input = "\n".join([f"{i}: {a['raw_title']}" for i, a in enumerate(articles)])
    prompt = f"""
    作為科技新聞主編，請將以下新聞標題進行『同事件聚合』。
    
    【任務說明】：
    1. 將描述『同一個具體技術事件』的新聞分在同一組。
    2. 只因主題相似(例如都在講AI)但事件不同，請分開。
    3. 只回傳編號分組，範例：
    [0, 3]
    [1]
    [2, 4, 5]
    
    【待處理新聞】：
    {titles_input}
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config={'temperature': 0.0}
        )
        
        groups = []
        used_indices = set()
        # 匹配所有方括號中的數字
        lines = re.findall(r'\[(.*?)\]', response.text)
        for line in lines:
            indices = [int(i.strip()) for i in line.split(',') if i.strip().isdigit()]
            group = []
            for idx in indices:
                if idx < len(articles) and idx not in used_indices:
                    group.append(articles[idx])
                    used_indices.add(idx)
            if group: groups.append(group)
        
        # 補上未被分類的孤兒新聞
        for i, art in enumerate(articles):
            if i not in used_indices: groups.append([art])
        return groups
    except:
        return [[a] for a in articles]

def fetch_data(feed_list):
    all_articles = []
    now_tw = datetime.datetime.now(TW_TZ)
    for item in feed_list:
        try:
            resp = requests.get(item['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
            feed = feedparser.parse(resp.content)
            s_name = (feed.feed.title if 'title' in feed.feed else item['url'].split('/')[2]).split('|')[0].strip()[:15]
            for entry in feed.entries[:15]:
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                try: p_date = date_parser.parse(raw_date, tzinfos=TZ_INFOS).astimezone(TW_TZ)
                except: p_date = now_tw
                all_articles.append({'raw_title': entry.title.strip(), 'link': entry.link, 'source': s_name, 'time': p_date, 'tag': item['tag']})
                FINAL_STATS[s_name] = FINAL_STATS.get(s_name, 0) + 1
        except: continue
    return all_articles

def main():
    print(f"Executing {SITE_TITLE} v{VERSION}...")
    intl = fetch_data(CONFIG['FEEDS']['INTL'])
    jk = fetch_data(CONFIG['FEEDS']['JK'])
    tw = fetch_data(CONFIG['FEEDS']['TW'])
    
    intl_clusters = batch_cluster_with_gemini(intl)
    jk_clusters = batch_cluster_with_gemini(jk)
    tw_clusters = batch_cluster_with_gemini(tw)

    stats_rows = "".join([f"<li><span class='s-label'>{k}</span><span class='s-bar'><i style='width:{min(v*5,100)}%'></i></span><span class='s-val'>{v}</span></li>" for k,v in sorted(FINAL_STATS.items(), key=lambda x:x[1], reverse=True)])

    def render(clusters, need_trans):
        html = ""
        for g in sorted(clusters, key=lambda x: x[0]['time'], reverse=True):
            m = g[0]
            t = highlight_keywords(translate_text(m['raw_title']) if need_trans else m['raw_title'])
            hid = str(abs(hash(m['link'])))[:10]
            time_str = m['time'].strftime('%m/%d %H:%M')
            html += f"<div class='story-block' id='sb-{hid}' data-link='{m['link']}'><div class='headline-wrapper'><span class='star-btn' onclick='toggleStar(\"{hid}\")'>★</span><div class='head-main'><a class='headline' href='{m['link']}' target='_blank'>{t}</a></div><span class='btn-hide' onclick='toggleHide(\"{hid}\")'>✕</span></div><div class='meta-line'>{m['source']} | {time_str}</div>"
            if len(g) > 1:
                html += "<div class='sub-news-list'>"
                for s in g[1:4]:
                    st = translate_text(s['raw_title']) if need_trans else s['raw_title']
                    html += f"<div class='sub-item'>• <a href='{s['link']}' target='_blank'>{st[:45]}...</a></div>"
                html += "</div>"
            html += "</div>"
        return html

    full_html = f"""
    <html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{SITE_TITLE}</title>
    <style>
        :root {{ --bg: #fff; --text: #333; --border: #eee; --link: #1a0dab; --tag: #888; --hi: #3498db; --kw: #e67e22; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #121212; --text: #e0e0e0; --border: #2c2c2c; --link: #8ab4f8; --tag: #9aa0a6; }} }}
        * {{ box-sizing: border-box; }}
        body {{ font-family: sans-serif; background: var(--bg); color: var(--text); margin: 0; padding-bottom: 50px; }}
        .header {{ padding: 8px 15px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 1000; }}
        #stats-p {{ display: none; padding: 10px 15px; background: #8881; border-bottom: 1px solid var(--border); font-size: 10px; }}
        #stats-p ul {{ list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 5px; }}
        .s-bar {{ display: inline-block; width: 40px; height: 4px; background: #8882; border-radius: 2px; margin: 0 5px; vertical-align: middle; }}
        .s-bar i {{ display: block; height: 100%; background: var(--hi); border-radius: 2px; }}
        .wrapper {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; background: var(--border); width: 100%; }}
        @media (max-width: 900px) {{ .wrapper {{ grid-template-columns: 1fr; }} }}
        .river {{ background: var(--bg); padding: 10px; min-width: 0; }}
        .river-title {{ font-size: 16px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 10px; }}
        .story-block {{ padding: 6px 0; border-bottom: 1px solid var(--border); }}
        .story-block.is-hidden {{ display: none !important; }}
        body.show-hidden .story-block.is-hidden {{ display: block !important; opacity: 0.3; }}
        body.only-stars .story-block:not(.has-star) {{ display: none !important; }}
        .headline-wrapper {{ display: flex; align-items: flex-start; gap: 4px; }}
        .head-main {{ flex-grow: 1; min-width: 0; }}
        .headline {{ font-size: 14px; font-weight: 800; text-decoration: none; color: var(--link); line-height: 1.3; }}
        .meta-line {{ font-size: 10px; color: var(--tag); margin-top: 2px; margin-left: 22px; }}
        .sub-news-list {{ margin: 4px 0 0 26px; border-left: 1px solid var(--border); padding-left: 8px; }}
        .sub-item {{ font-size: 11.5px; margin-bottom: 1px; color: var(--text); opacity: 0.8; }}
        .sub-item a {{ text-decoration: none; color: inherit; }}
        .star-btn {{ cursor: pointer; color: #444; font-size: 14px; margin-right: 6px; flex-shrink: 0; }}
        .star-btn.active {{ color: #f1c40f; }}
        .btn-hide {{ cursor: pointer; color: var(--tag); font-size: 11px; opacity: 0.4; margin-left: auto; }}
        .kw-highlight {{ color: var(--kw); font-weight: bold; background: #ff980015; }}
        .btn {{ cursor: pointer; padding: 3px 8px; border: 1px solid var(--border); font-size: 11px; border-radius: 3px; background: var(--bg); color: var(--text); font-weight: bold; }}
    </style></head><body>
        <div class='header'>
            <h1 style='margin:0; font-size:16px;'>{SITE_TITLE} v{VERSION}</h1>
            <div style='gap:5px; display:flex;'><span class='btn' onclick='tStats()'>📊</span> <span class='btn' onclick='location.reload()'>🔄</span> <span class='btn' onclick='document.body.classList.toggle("show-hidden")'>👁️</span> <span class='btn' onclick='document.body.classList.toggle("only-stars")'>★</span></div>
        </div>
        <div id='stats-p'><ul>{stats_rows}</ul></div>
        <div class='wrapper'>
            <div class='river'><div class='river-title'>Global Strategy</div>{render(intl_clusters, True)}</div>
            <div class='river'><div class='river-title'>Japan/Korea</div>{render(jk_clusters, True)}</div>
            <div class='river'><div class='river-title'>Taiwan Tech</div>{render(tw_clusters, False)}</div>
        </div>
        <script>
            function tStats() {{ const p = document.getElementById('stats-p'); p.style.display = (p.style.display==='block')?'none':'block'; }}
            function toggleHide(h) {{
                const el = document.getElementById('sb-'+h); const l = el.getAttribute('data-link');
                let hds = JSON.parse(localStorage.getItem('tech_hiddens')||'[]');
                if(hds.includes(l)) hds = hds.filter(i=>i!==l); else hds.push(l);
                localStorage.setItem('tech_hiddens', JSON.stringify(hds)); el.classList.toggle('is-hidden');
            }}
            function toggleStar(h) {{
                const el = document.getElementById('sb-'+h); const btn = el.querySelector('.star-btn'); const l = el.getAttribute('data-link');
                let s = JSON.parse(localStorage.getItem('tech_stars')||'[]');
                if(s.includes(l)) {{ s=s.filter(i=>i!==l); el.classList.remove('has-star'); btn.classList.remove('active'); }} 
                else {{ s.push(l); el.classList.add('has-star'); btn.classList.add('active'); }}
                localStorage.setItem('tech_stars', JSON.stringify(s));
            }}
            document.addEventListener('DOMContentLoaded', () => {{
                const h = JSON.parse(localStorage.getItem('tech_hiddens')||'[]');
                const s = JSON.parse(localStorage.getItem('tech_stars')||'[]');
                document.querySelectorAll('.story-block').forEach(el => {{
                    const l = el.getAttribute('data-link');
                    if(h.includes(l)) el.classList.add('is-hidden');
                    if(s.includes(l)) {{ el.classList.add('has-star'); el.querySelector('.star-btn').classList.add('active'); }}
                }});
            }});
        </script></body></html>
    """
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__":
    main()
