import feedparser, datetime, pytz, os, requests, json, re, sys, time
from dateutil import parser as date_parser
from google import genai
import urllib3

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 配置 ---
VERSION = "2.5.6"
SITE_TITLE = "豆子新聞戰情室"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemma-3-27b-it" 

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}

def load_config():
    if os.path.exists('feeds.json'):
        try:
            with open('feeds.json', 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}, "TERM_MAP": {}}

CONFIG = load_config()

def get_processed_content(articles, zone_name):
    """【v2.5.6】強勢實體聚合邏輯"""
    if not client or not articles: return [[a] for a in articles]
    print(f"\n>>> 處理 {zone_name}，共 {len(articles)} 則")
    
    chunk_size = 15 
    company_map = {} # 格式: { "Apple": [idx1, idx2], ... }
    translated_titles = {} # 格式: { idx: "翻譯標題" }
    
    for start in range(0, len(articles), chunk_size):
        chunk = articles[start : start + chunk_size]
        titles_input = "\n".join([f"ID_{i+start}: {a['raw_title']}" for i, a in enumerate(chunk)])
        
        prompt = f"""
        任務：從標題提取核心公司，並翻譯標題為繁體中文。
        1. 標註核心公司(Entity)：若無明確公司，標註為 "None"。
        2. 翻譯標題：移除雜訊([日],[韓],Send tips, Axios, 📩)。
        3. 術語：智能->智慧、數據->資料、芯片->晶片、算力->運算力。
        4. 必須回傳純 JSON 陣列：
        [ {{"id": 編號, "company": "核心公司", "title": "翻譯標題"}} ]
        待處理：{titles_input}
        """
        
        retry_count = 0
        while retry_count < 2:
            try:
                response = client.models.generate_content(model=MODEL_NAME, contents=prompt, config={'temperature': 0.1})
                json_match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    for item in data:
                        idx = item['id']
                        comp = item['company'].strip().capitalize()
                        translated_titles[idx] = item['title'].strip()
                        if comp != "None":
                            if comp not in company_map: company_map[comp] = []
                            company_map[comp].append(idx)
                    break 
                else: break
            except Exception:
                time.sleep(15); retry_count += 1
        time.sleep(1)

    # --- Python 硬聚合階段 ---
    final_clusters = []
    used_indices = set()

    # 1. 優先處理有公司的群組
    for comp, indices in company_map.items():
        cluster = []
        for idx in indices:
            if idx < len(articles) and idx not in used_indices:
                a = articles[idx]
                a['display_title'] = translated_titles.get(idx, a['raw_title'])
                cluster.append(a); used_indices.add(idx)
        if cluster: final_clusters.append(cluster)

    # 2. 處理沒有公司的新聞 (依時間排序)
    remaining = []
    for i, a in enumerate(articles):
        if i not in used_indices:
            a['display_title'] = translated_titles.get(i, a['raw_title'])
            remaining.append([a])
    
    final_clusters.extend(remaining)
    return final_clusters

def fetch_raw_data(feed_list):
    all_articles = []
    now_tw = datetime.datetime.now(TW_TZ)
    limit_date = now_tw - datetime.timedelta(hours=48)
    for item in feed_list:
        try:
            resp = requests.get(item['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15, verify=False)
            feed = feedparser.parse(resp.content)
            s_name = (feed.feed.title if 'title' in feed.feed else item['url'].split('/')[2]).split('|')[0].strip()[:10]
            for entry in feed.entries[:12]:
                title = entry.title.strip()
                if not title: continue
                try: p_date = date_parser.parse(entry.get('published', entry.get('pubDate', entry.get('updated', None))), tzinfos=TZ_INFOS).astimezone(TW_TZ)
                except: p_date = now_tw
                if p_date < limit_date: continue
                all_articles.append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag': item['tag']})
        except: continue
    return all_articles

def main():
    print(f"Building {SITE_TITLE} v{VERSION}...")
    intl = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['INTL']), "Global")
    jk = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['JK']), "JK")
    tw = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['TW']), "Taiwan")

    def render(clusters):
        html = ""
        # 排序邏輯：有公司的群組會依照該組最新一則新聞的時間排序
        for g in sorted(clusters, key=lambda x: x[0]['time'], reverse=True):
            m = g[0]; hid = str(abs(hash(m['link'])))[:10]
            badge = f'<span class="badge-ithome">iThome</span>' if "iThome" in m['tag'] else (f'<span class="badge-tag">{m["tag"]}</span>' if m["tag"] else "")
            
            html += f"""
            <div class='story-block' id='sb-{hid}' data-link='{m['link']}' data-ts='{int(m['time'].timestamp())}'>
                <div class='headline-wrapper'>
                    <div class='star-cell'><span class='star-btn' onclick='toggleStar("{hid}")'>★</span></div>
                    <div class='head-content'>
                        <div class='title-row'>
                            {badge}<a class='headline' href='{m['link']}' target='_blank'>{m.get('display_title', m['raw_title'])}</a>
                        </div>
                    </div>
                    <div class='action-btns'>
                        <span class='btn-restore' onclick='restoreItem("{hid}")'>恢復</span>
                        <span class='btn-hide' onclick='toggleHide("{hid}")'>隱藏</span>
                    </div>
                </div>
                <div class='meta-line'>{m['source']} | {m['time'].strftime('%m/%d %H:%M')}</div>
            """
            if len(g) > 1:
                html += "<div class='sub-news-list'>"
                for s in g[1:8]:
                    html += f"<div class='sub-item'>• <a href='{s['link']}' target='_blank'>{s.get('display_title', s['raw_title'])}</a></div>"
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
        .headline-wrapper {{ display: flex; align-items: flex-start; width: 100%; }}
        .star-cell {{ width: 24px; flex-shrink: 0; padding-top: 2px; }}
        .head-content {{ flex: 1; min-width: 0; padding: 0 8px; }}
        .title-row {{ display: flex; align-items: flex-start; gap: 5px; flex-wrap: wrap; }}
        .headline {{ font-size: 14.5px; font-weight: 800; text-decoration: none; color: var(--link); line-height: 1.3; word-break: break-word; }}
        .action-btns {{ flex-shrink: 0; display: flex; gap: 10px; padding-top: 3px; }}
        .meta-line {{ font-size: 10px; color: var(--tag); margin: 4px 0 0 24px; }}
        .sub-news-list {{ margin: 6px 0 0 24px; border-left: 1px solid var(--border); padding-left: 10px; }}
        .sub-item {{ font-size: 12.5px; margin-bottom: 3px; opacity: 0.8; }}
        .badge-tag, .badge-ithome {{ color: #fff; padding: 1px 4px; font-size: 8px; border-radius: 2px; flex-shrink: 0; }}
        .badge-tag {{ background: #888; }} .badge-ithome {{ background: var(--hi); font-weight: 800; }}
        .star-btn {{ cursor: pointer; color: var(--tag); font-size: 15px; }}
        .btn-hide {{ cursor: pointer; color: var(--tag); font-size: 11px; }}
        .btn-restore {{ cursor: pointer; color: var(--hi); font-size: 11px; display: none; font-weight: bold; }}
        body.show-hidden .btn-restore {{ display: inline-block; }}
        .btn {{ cursor: pointer; padding: 4px 10px; border: 1px solid var(--border); font-size: 11px; border-radius: 4px; background: var(--bg); color: var(--text); font-weight: bold; }}
    </style></head><body>
        <div class='header'>
            <h1 style='margin:0; font-size:16px;'>{SITE_TITLE} v{VERSION}</h1>
            <div style='display:flex; gap:8px;'>
                <span class='btn' onclick='document.body.classList.toggle("show-hidden")'>顯示已隱藏</span>
                <span class='btn' onclick='location.reload()'>重新整理</span>
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
