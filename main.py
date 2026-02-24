import feedparser, datetime, pytz, os, requests, json, re, sys
from dateutil import parser as date_parser
from google import genai
import urllib3

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

VERSION = "2.3.3"
SITE_TITLE = "豆子新聞戰情室"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}
FINAL_STATS = {}
TOTAL_TOKENS = 0

def load_config():
    if os.path.exists('feeds.json'):
        try:
            with open('feeds.json', 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}, "TERM_MAP": {}}

CONFIG = load_config()

def get_processed_content(articles):
    """【v2.3.3】強化聚合與 Token 計數"""
    global TOTAL_TOKENS
    if not client or not articles: return [[a] for a in articles]
    
    # 基礎 Token 估算：每 1 則新聞標題約 80 Tokens (輸入+處理)
    TOTAL_TOKENS += (len(articles) * 85)
    
    titles_input = "\n".join([f"ID_{i}: {a['raw_title']}" for i, a in enumerate(articles)])
    prompt = f"""
    任務：翻譯為繁體中文並依核心公司聚合。
    指令：
    1. 移除 Send tips, URL, Axios, 📩 等雜訊。
    2. 術語轉換：智能->智慧、數據->資料、芯片->晶片、算力->運算力。
    3. 強制聚合：所有關於同家公司(如 Anthropic, Apple)的新聞必須分在同組，忽略動作差異。
    4. 必須回傳純 JSON。
    
    範例格式：
    [ {{"company": "Apple", "indices": [0, 5], "titles": ["翻譯1", "翻譯2"]}} ]
    
    待處理：
    {titles_input}
    """
    
    try:
        response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt, config={'temperature': 0.0})
        json_match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
        if not json_match: return [[a] for a in articles]
        
        data = json.loads(json_match.group())
        final_clusters = []
        used = set()
        
        for group in data:
            cluster = []
            for i, idx in enumerate(group['indices']):
                if idx < len(articles) and idx not in used:
                    item = articles[idx]
                    item['display_title'] = group['titles'][i]
                    cluster.append(item); used.add(idx)
            if cluster: final_clusters.append(cluster)
            
        for i, a in enumerate(articles):
            if i not in used:
                a['display_title'] = a['raw_title']
                final_clusters.append([a])
        return final_clusters
    except:
        return [[a] for a in articles]

def fetch_raw_data(feed_list):
    all_articles = []
    now_tw = datetime.datetime.now(TW_TZ)
    limit_date = now_tw - datetime.timedelta(days=4)
    for item in feed_list:
        try:
            resp = requests.get(item['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
            feed = feedparser.parse(resp.content)
            s_name = (feed.feed.title if 'title' in feed.feed else item['url'].split('/')[2]).split('|')[0].strip()[:10]
            for entry in feed.entries[:15]:
                title = entry.title.strip()
                try: p_date = date_parser.parse(entry.get('published', entry.get('pubDate', entry.get('updated', None))), tzinfos=TZ_INFOS).astimezone(TW_TZ)
                except: p_date = now_tw
                if p_date < limit_date: continue
                all_articles.append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag': item['tag']})
                FINAL_STATS[s_name] = FINAL_STATS.get(s_name, 0) + 1
        except: continue
    return all_articles

def main():
    intl = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['INTL']))
    jk = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['JK']))
    tw = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['TW']))

    def render(clusters):
        html = ""
        for g in sorted(clusters, key=lambda x: x[0]['time'], reverse=True):
            m = g[0]; hid = str(abs(hash(m['link'])))[:10]
            badge = f'<span class="badge-ithome">iThome</span>' if "iThome" in m['tag'] else (f'<span class="badge-tag">{m["tag"]}</span>' if m["tag"] else "")
            html += f"""
            <div class='story-block' id='sb-{hid}' data-link='{m['link']}' data-ts='{int(m['time'].timestamp())}'>
                <div class='headline-wrapper'>
                    <span class='star-btn' onclick='toggleStar("{hid}")'>★</span>
                    <div class='head-content'>
                        <div class='title-row'>
                            {badge}<a class='headline' href='{m['link']}' target='_blank'>{m.get('display_title', m['raw_title'])}</a>
                        </div>
                    </div>
                    <div class='action-btns'>
                        <span class='btn-restore' onclick='restoreItem("{hid}")'>↺</span>
                        <span class='btn-hide' onclick='toggleHide("{hid}")'>✕</span>
                    </div>
                </div>
                <div class='meta-line'>{m['source']} | {m['time'].strftime('%m/%d %H:%M')}</div>
            """
            if len(g) > 1:
                html += "<div class='sub-news-list'>"
                for s in g[1:6]:
                    html += f"<div class='sub-item'>• <a href='{s['link']}' target='_blank'>{s.get('display_title', s['raw_title'])}</a></div>"
                html += "</div>"
            html += "</div>"
        return html

    stats_header = f"<div class='token-bar'>💰 預估本次消耗：<strong>{TOTAL_TOKENS}</strong> Tokens</div>"
    stats_rows = "".join([f"<li><span class='s-label'>{k}</span><span class='s-bar'><i style='width:{min(v*5,100)}%'></i></span><span class='s-count'>{v}</span></li>" for k,v in sorted(FINAL_STATS.items(), key=lambda x:x[1], reverse=True)])

    full_html = f"""
    <html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{SITE_TITLE}</title>
    <style>
        :root {{ --bg: #fff; --text: #333; --border: #eee; --link: #1a0dab; --hi: #3498db; --tag: #888; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #121212; --text: #e0e0e0; --border: #2c2c2c; --link: #8ab4f8; --tag: #9aa0a6; }} }}
        * {{ box-sizing: border-box; }}
        body {{ font-family: sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0 15px 50px 15px; }}
        .header {{ padding: 10px 0; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 1000; }}
        #stats-p {{ display: none; padding: 15px 0; border-bottom: 1px solid var(--border); }}
        .token-bar {{ background: #e67e22; color: #fff; padding: 4px 10px; border-radius: 4px; font-size: 11px; margin-bottom: 10px; display: inline-block; }}
        #stats-p ul {{ list-style: none; padding: 0; margin: 0; column-count: 2; column-gap: 30px; }}
        .wrapper {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }}
        @media (max-width: 900px) {{ .wrapper {{ grid-template-columns: 1fr; }} }}
        .river-title {{ font-size: 16px; font-weight: 900; border-bottom: 2px solid var(--text); margin: 10px 0; }}
        .story-block {{ padding: 12px 0; border-bottom: 1px solid var(--border); }}
        .story-block.is-hidden {{ display: none; }}
        body.show-hidden .story-block.is-hidden {{ display: block !important; opacity: 0.4; }}
        .headline-wrapper {{ display: flex; align-items: flex-start; gap: 8px; width: 100%; }}
        .head-content {{ flex-grow: 1; min-width: 0; }}
        .title-row {{ display: flex; align-items: flex-start; gap: 5px; }}
        .headline {{ font-size: 14.5px; font-weight: 800; text-decoration: none; color: var(--link); line-height: 1.3; }}
        .action-btns {{ display: flex; gap: 10px; flex-shrink: 0; margin-left: auto; align-items: center; }}
        .meta-line {{ font-size: 10px; color: var(--tag); margin: 5px 0 0 23px; }}
        .sub-news-list {{ margin: 6px 0 0 23px; border-left: 1px solid var(--border); padding-left: 10px; }}
        .sub-item {{ font-size: 12.5px; margin-bottom: 3px; opacity: 0.8; }}
        .badge-tag, .badge-ithome {{ color: #fff; padding: 1px 4px; font-size: 8px; border-radius: 2px; }}
        .badge-tag {{ background: #888; }} .badge-ithome {{ background: var(--hi); font-weight: 800; }}
        .star-btn {{ cursor: pointer; color: var(--tag); font-size: 15px; }}
        .btn-hide {{ cursor: pointer; color: var(--tag); font-size: 12px; opacity: 0.3; }}
        .btn-restore {{ cursor: pointer; color: var(--hi); font-size: 14px; display: none; font-weight: bold; }}
        .btn {{ cursor: pointer; padding: 4px 10px; border: 1px solid var(--border); font-size: 11px; border-radius: 4px; background: var(--bg); color: var(--text); font-weight: bold; }}
    </style></head><body>
        <div class='header'>
            <h1 style='margin:0; font-size:16px;'>{SITE_TITLE} v{VERSION}</h1>
            <div style='display:flex; gap:8px;'>
                <span class='btn' onclick='document.getElementById("stats-p").style.display=(document.getElementById("stats-p").style.display==="block")?"none":"block"'>📊 分析</span>
                <span class='btn' onclick='document.body.classList.toggle("show-hidden")'>👁️ 恢復</span>
                <span class='btn' onclick='location.reload()'>🔄</span>
            </div>
        </div>
        <div id='stats-p'>{stats_header}<ul>{stats_rows}</ul></div>
        <div class='wrapper'>
            <div class='river'><div class='river-title'>Global</div>{render(intl)}</div>
            <div class='river'><div class='river-title'>JK</div>{render(jk)}</div>
            <div class='river'><div class='river-title'>Taiwan</div>{render(tw)}</div>
        </div>
        <script>
            function toggleHide(h) {{
                const el = document.getElementById('sb-'+h);
                const link = el.getAttribute('data-link');
                let hiddens = JSON.parse(localStorage.getItem('tech_hiddens_v5') || '[]');
                if(!hiddens.some(i => i.l === link)) hiddens.push({{l: link, t: el.getAttribute('data-ts')}});
                localStorage.setItem('tech_hiddens_v5', JSON.stringify(hiddens));
                el.classList.add('is-hidden');
            }}
            function restoreItem(h) {{
                const el = document.getElementById('sb-'+h);
                const link = el.getAttribute('data-link');
                let hiddens = JSON.parse(localStorage.getItem('tech_hiddens_v5') || '[]');
                hiddens = hiddens.filter(i => i.l !== link);
                localStorage.setItem('tech_hiddens_v5', JSON.stringify(hiddens));
                el.classList.remove('is-hidden');
            }}
            function toggleStar(h) {{
                const el = document.getElementById('sb-'+h);
                const btn = el.querySelector('.star-btn');
                const link = el.getAttribute('data-link');
                let stars = JSON.parse(localStorage.getItem('tech_stars_v5') || '[]');
                const idx = stars.findIndex(i => i.l === link);
                if(idx > -1) {{ stars.splice(idx, 1); btn.style.color = ''; }}
                else {{ stars.push({{l: link, t: el.getAttribute('data-ts')}}); btn.style.color = '#f1c40f'; }}
                localStorage.setItem('tech_stars_v5', JSON.stringify(stars));
            }}
            document.addEventListener('DOMContentLoaded', () => {{
                const now = Math.floor(Date.now() / 1000);
                let h = JSON.parse(localStorage.getItem('tech_hiddens_v5') || '[]');
                let s = JSON.parse(localStorage.getItem('tech_stars_v5') || '[]');
                h = h.filter(i => (now - i.t) < 604800); s = s.filter(i => (now - i.t) < 604800);
                localStorage.setItem('tech_hiddens_v5', JSON.stringify(h));
                localStorage.setItem('tech_stars_v5', JSON.stringify(s));
                document.querySelectorAll('.story-block').forEach(el => {{
                    const link = el.getAttribute('data-link');
                    if(h.some(i => i.l === link)) el.classList.add('is-hidden');
                    if(s.some(i => i.l === link)) el.querySelector('.star-btn').style.color = '#f1c40f';
                }});
            }});
        </script></body></html>
    """
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__":
    main()
