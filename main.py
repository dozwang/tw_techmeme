import feedparser, datetime, pytz, os, requests, json, re, sys
from dateutil import parser as date_parser
from google import genai
import urllib3

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 配置 ---
VERSION = "2.2.0"
SITE_TITLE = "豆子新聞戰情室"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}

def load_config():
    if os.path.exists('feeds.json'):
        try:
            with open('feeds.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}, "TERM_MAP": {}}

CONFIG = load_config()

def get_processed_content(articles):
    """【v2.2.0 核心】Gemini 同時處理翻譯與聚合"""
    if not client or not articles: return [[a] for a in articles]
    
    # 準備 AI 判斷清單
    titles_input = "\n".join([f"{i}: {a['raw_title']}" for i, a in enumerate(articles)])
    
    prompt = f"""
    任務：翻譯科技新聞並依『主體公司』分組。
    
    【指令】：
    1. 將標題精準翻成繁體中文。
    2. 修正術語：智能->智慧、數據->資料、軟件->軟體、芯片->晶片、副駕駛->Copilot。
    3. 徹底移除垃圾字眼：發送提示、📩、(Axios)、網址。
    4. 將同一家公司(如 Anthropic, Google, NVIDIA)的編號分在同一個括號組。
    
    【回傳格式範例】(嚴格遵守)：
    [0, 3] | 翻譯標題0 | 翻譯標題3
    [1] | 翻譯標題1
    
    【清單】：
    {titles_input}
    """
    
    try:
        response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt, config={'temperature': 0.0})
        lines = response.text.strip().split('\n')
        final_clusters = []
        used_indices = set()

        for line in lines:
            if '|' not in line or '[' not in line: continue
            parts = line.split('|')
            # 解析編號組 [0, 3]
            idx_match = re.search(r'\[(.*?)\]', parts[0])
            if not idx_match: continue
            
            indices = [int(i.strip()) for i in idx_match.group(1).split(',') if i.strip().isdigit()]
            translated_titles = [t.strip() for t in parts[1:]]
            
            cluster = []
            for i, idx in enumerate(indices):
                if idx < len(articles) and idx not in used_indices:
                    item = articles[idx]
                    # 填入 AI 翻譯好的標題
                    item['display_title'] = translated_titles[i] if i < len(translated_titles) else item['raw_title']
                    cluster.append(item)
                    used_indices.add(idx)
            if cluster: final_clusters.append(cluster)
        
        # 補漏 (萬一 AI 漏掉某些編號)
        for i, a in enumerate(articles):
            if i not in used_indices:
                a['display_title'] = a['raw_title'] # 沒翻到就放原文
                final_clusters.append([a])
        return final_clusters
    except Exception as e:
        print(f"Gemini Error: {e}")
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
        except: continue
    return all_articles

def main():
    print(f"Running {SITE_TITLE} v{VERSION} (AI-Powered)...")
    
    # 執行流程：抓取 -> Gemini(翻譯+聚合) -> 渲染
    intl_c = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['INTL']))
    jk_c = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['JK']))
    tw_c = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['TW']))

    def render(clusters):
        html = ""
        for g in sorted(clusters, key=lambda x: x[0]['time'], reverse=True):
            m = g[0]
            hid = str(abs(hash(m['link'])))[:10]
            badge = f'<span class="badge-tag">{m["tag"]}</span>' if m["tag"] else ""
            if "iThome" in m["tag"]: badge = '<span class="badge-ithome">iThome</span>'
            ts = int(m['time'].timestamp())
            
            html += f"""
            <div class='story-block' id='sb-{hid}' data-link='{m['link']}' data-ts='{ts}'>
                <div class='headline-wrapper'>
                    <span class='star-btn' onclick='toggleStar("{hid}")'>★</span>
                    <div class='head-content'>
                        <div class='title-row'>
                            {badge}<a class='headline' href='{m['link']}' target='_blank'>{m.get('display_title', m['raw_title'])}</a>
                        </div>
                    </div>
                    <span class='btn-hide' onclick='toggleHide("{hid}")'>✕</span>
                </div>
                <div class='meta-line'>{m['source']} | {m['time'].strftime('%m/%d %H:%M')}</div>
            """
            if len(g) > 1:
                html += "<div class='sub-news-list'>"
                for s in g[1:6]:
                    html += f"<div class='sub-item'>• <a href='{s['link']}' target='_blank'>{s.get('display_title', s['raw_title'])}</a> <small>({s['source']})</small></div>"
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
        .headline {{ font-size: 14.5px; font-weight: 800; text-decoration: none; color: var(--link); line-height:1.3; }}
        .meta-line {{ font-size: 10px; color: var(--tag); margin-top: 5px; margin-left: 23px; }}
        .sub-news-list {{ margin: 6px 0 0 23px; border-left: 1px solid var(--border); padding-left: 10px; }}
        .sub-item {{ font-size: 12.5px; margin-bottom: 3px; color: var(--text); opacity: 0.9; }}
        .sub-item a {{ text-decoration: none; color: inherit; }}
        .badge-tag {{ background: #888; color: #fff; padding: 1px 4px; font-size: 8.5px; border-radius: 2px; flex-shrink: 0; }}
        .badge-ithome {{ background: var(--hi); color: #fff; padding: 1px 4px; font-size: 8.5px; border-radius: 2px; font-weight: 800; flex-shrink: 0; }}
        .star-btn {{ cursor: pointer; color: var(--tag); font-size: 15px; margin-top: 1px; }}
        .btn-hide {{ cursor: pointer; color: var(--tag); font-size: 11px; opacity: 0.3; margin-left: auto; }}
        .btn {{ cursor: pointer; padding: 4px 10px; border: 1px solid var(--border); font-size: 11px; border-radius: 4px; background: var(--bg); color: var(--text); font-weight: bold; }}
    </style></head><body>
        <div class='header'>
            <h1 style='margin:0; font-size:16px;'>{SITE_TITLE} v{VERSION}</h1>
            <div style='display:flex; gap:8px;'>
                <span class='btn' onclick='document.body.classList.toggle("show-hidden")'>👁️ 顯示已隱藏</span>
                <span class='btn' onclick='location.reload()'>🔄</span>
            </div>
        </div>
        <div class='wrapper'>
            <div class='river'><div class='river-title'>Global</div>{render(intl_c)}</div>
            <div class='river'><div class='river-title'>JK</div>{render(jk_c)}</div>
            <div class='river'><div class='river-title'>Taiwan</div>{render(tw_c)}</div>
        </div>
        <script>
            function toggleHide(h) {{
                const el = document.getElementById('sb-'+h);
                const link = el.getAttribute('data-link');
                const ts = el.getAttribute('data-ts');
                let hiddens = JSON.parse(localStorage.getItem('tech_hiddens_v4') || '[]');
                if(!hiddens.some(i => i.l === link)) hiddens.push({{l: link, t: ts}});
                localStorage.setItem('tech_hiddens_v4', JSON.stringify(hiddens));
                el.classList.add('is-hidden');
            }}
            function toggleStar(h) {{
                const el = document.getElementById('sb-'+h);
                const btn = el.querySelector('.star-btn');
                const link = el.getAttribute('data-link');
                const ts = el.getAttribute('data-ts');
                let stars = JSON.parse(localStorage.getItem('tech_stars_v4') || '[]');
                const idx = stars.findIndex(i => i.l === link);
                if(idx > -1) {{ stars.splice(idx, 1); btn.style.color = ''; }}
                else {{ stars.push({{l: link, t: ts}}); btn.style.color = '#f1c40f'; }}
                localStorage.setItem('tech_stars_v4', JSON.stringify(stars));
            }}
            document.addEventListener('DOMContentLoaded', () => {{
                const now = Math.floor(Date.now() / 1000);
                let hiddens = JSON.parse(localStorage.getItem('tech_hiddens_v4') || '[]');
                let stars = JSON.parse(localStorage.getItem('tech_stars_v4') || '[]');
                hiddens = hiddens.filter(i => (now - i.t) < 604800);
                stars = stars.filter(i => (now - i.t) < 604800);
                localStorage.setItem('tech_hiddens_v4', JSON.stringify(hiddens));
                localStorage.setItem('tech_stars_v4', JSON.stringify(stars));
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
