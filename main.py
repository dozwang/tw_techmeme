import feedparser, datetime, pytz, os, requests, json, re, sys, time
from dateutil import parser as date_parser
from google import genai
import urllib3
from concurrent.futures import ThreadPoolExecutor

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 核心配置 ---
VERSION = "2.6.1"
SITE_TITLE = "豆子新聞戰情室"
PRIORITY_COMPANIES = ["Nvidia", "Apple", "Anthropic", "Tsmc", "Openai", "Google", "Microsoft", "Meta"]
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
# 回歸最穩定的 1.5 Flash 確保翻譯成功率
MODEL_NAME = "gemini-1.5-flash" 

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}

def load_config():
    if os.path.exists('feeds.json'):
        try:
            with open('feeds.json', 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}}

CONFIG = load_config()

def get_processed_content(articles, zone_name):
    """強化翻譯映射與 ID 型別處理"""
    if not client or not articles: return [[a] for a in articles]
    print(f"\n>>> 正在優化 {zone_name} 欄位...")
    
    chunk_size = 12 
    company_map = {} 
    translated_map = {} 
    
    for start in range(0, len(articles), chunk_size):
        chunk = articles[start : start + chunk_size]
        titles_input = "\n".join([f"ID_{i+start}: {a['raw_title']}" for i, a in enumerate(chunk)])
        
        prompt = f"""
        任務：翻譯為繁中並識別核心公司。
        1. 徹底移除標題中的 URL、Send tips、Axios、[日]、[韓]、[X]。
        2. 術語：智能->智慧、數據->資料、芯片->晶片、算力->運算力。
        3. 回傳純 JSON: [{{'id': 編號, 'company': '核心公司', 'title': '翻譯標題'}}]
        待處理清單：
        {titles_input}
        """
        
        try:
            response = client.models.generate_content(model=MODEL_NAME, contents=prompt, config={'temperature': 0.1})
            json_match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                for item in data:
                    try:
                        # 強制轉型 ID 避免 TypeError
                        idx = int(item['id'])
                        comp = item['company'].strip().capitalize()
                        translated_map[idx] = item['title'].strip()
                        if comp != "None":
                            if comp not in company_map: company_map[comp] = []
                            company_map[comp].append(idx)
                    except: continue
            time.sleep(1)
        except: continue

    final_clusters = []
    used_indices = set()

    # 按公司聚合
    for comp, indices in company_map.items():
        cluster = []
        is_p = any(p.capitalize() in comp for p in PRIORITY_COMPANIES)
        for idx in indices:
            if idx < len(articles) and idx not in used_indices:
                a = articles[idx]
                a['display_title'] = translated_map.get(idx, a['raw_title'])
                a['is_priority'] = is_p
                cluster.append(a); used_indices.add(idx)
        if cluster: final_clusters.append(cluster)

    # 補漏與單獨翻譯
    for i, a in enumerate(articles):
        if i not in used_indices:
            a['display_title'] = translated_map.get(i, a['raw_title'])
            a['is_priority'] = False
            final_clusters.append([a])
    
    final_clusters.sort(key=lambda x: (x[0].get('is_priority', False), x[0]['time']), reverse=True)
    return final_clusters

def fetch_single_feed(item, limit_date):
    results = []
    try:
        resp = requests.get(item['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=12, verify=False)
        feed = feedparser.parse(resp.content)
        s_name = (feed.feed.title if 'title' in feed.feed else item['url'].split('/')[2]).split('|')[0].strip()[:10]
        for entry in feed.entries[:10]:
            # 暴力清理原始標題中的網址與雜訊
            clean_title = re.sub(r'https?://\S+|Send tips!|📩|\[X\]|\[日\]|\[韓\]', '', entry.title).strip()
            if not clean_title: continue
            try: p_date = date_parser.parse(entry.get('published', entry.get('pubDate', entry.get('updated', None))), tzinfos=TZ_INFOS).astimezone(TW_TZ)
            except: p_date = datetime.datetime.now(TW_TZ)
            if p_date < limit_date: continue
            results.append({'raw_title': clean_title, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag': item['tag']})
    except: pass
    return results

def fetch_raw_data(feed_list):
    all_articles = []
    limit_date = datetime.datetime.now(TW_TZ) - datetime.timedelta(hours=48)
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_single_feed, item, limit_date) for item in feed_list]
        for f in futures: all_articles.extend(f.result())
    return sorted(all_articles, key=lambda x: x['time'], reverse=True)

def main():
    print(f"Executing {SITE_TITLE} v{VERSION}...")
    intl_raw = fetch_raw_data(CONFIG['FEEDS']['INTL'])
    jk_raw = fetch_raw_data(CONFIG['FEEDS']['JK'])
    tw_raw = fetch_raw_data(CONFIG['FEEDS']['TW'])
    
    intl = get_processed_content(intl_raw, "Global")
    jk = get_processed_content(jk_raw, "JK")
    tw = get_processed_content(tw_raw, "Taiwan")

    def render(clusters):
        html = ""
        for g in clusters:
            m = g[0]; hid = str(abs(hash(m['link'])))[:10]
            p_style = "border-left: 4px solid #f1c40f; background: rgba(241,196,15,0.03);" if m.get('is_priority') else ""
            badge = f"<span class='badge-ithome'>iThome</span>" if "iThome" in m['tag'] else ""
            
            html += f"<div class='story-block' id='sb-{hid}' data-link='{m['link']}' style='{p_style}'>"
            html += f"<div class='headline-wrapper'>"
            html += f"<div class='star-cell'><span class='star-btn' onclick='toggleStar(\"{hid}\")'>★</span></div>"
            html += f"<div class='head-content'><a class='headline' href='{m['link']}' target='_blank'>{badge}{m.get('display_title', m['raw_title'])}</a></div>"
            html += f"<div class='action-btns'><span class='btn-restore' onclick='restoreItem(\"{hid}\")'>恢復</span><span class='btn-hide' onclick='toggleHide(\"{hid}\")'>隱藏</span></div>"
            html += f"</div><div class='meta-line'>{m['source']} | {m['time'].strftime('%m/%d %H:%M')}</div>"
            if len(g) > 1:
                html += "<div class='sub-news-list'>"
                for s in g[1:6]:
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
        .headline {{ font-size: 14.5px; font-weight: 800; text-decoration: none; color: var(--link); line-height: 1.3; word-break: break-word; }}
        .action-btns {{ flex-shrink: 0; width: 85px; display: flex; gap: 8px; justify-content: flex-end; padding-top: 3px; font-size: 11px; }}
        .btn-hide, .btn-restore {{ cursor: pointer; color: var(--tag); }}
        .btn-restore {{ color: var(--hi); display: none; font-weight: bold; }}
        body.show-hidden .btn-restore {{ display: inline-block; }}
        .meta-line {{ font-size: 10px; color: var(--tag); margin: 4px 0 0 24px; }}
        .sub-news-list {{ margin: 6px 0 0 24px; border-left: 1px solid var(--border); padding-left: 10px; }}
        .sub-item {{ font-size: 12.5px; margin-bottom: 3px; opacity: 0.8; }}
        .badge-ithome {{ background: var(--hi); color: #fff; padding: 1px 4px; font-size: 8px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
        .star-btn {{ cursor: pointer; color: var(--tag); font-size: 15px; }}
        .btn {{ cursor: pointer; padding: 4px 10px; border: 1px solid var(--border); font-size: 11px; border-radius: 4px; background: var(--bg); color: var(--text); font-weight: bold; }}
    </style></head><body>
        <div class='header'><h1 style='margin:0; font-size:16px;'>{SITE_TITLE} v{VERSION}</h1>
        <div style='display:flex; gap:8px;'><span class='btn' onclick='document.body.classList.toggle("show-hidden")'>顯示已隱藏</span><span class='btn' onclick='location.reload()'>重新整理</span></div></div>
        <div class='wrapper'>
            <div class='river'><div class='river-title'>Global</div>{render(intl)}</div>
            <div class='river'><div class='river-title'>JK</div>{render(jk)}</div>
            <div class='river'><div class='river-title'>Taiwan</div>{render(tw)}</div>
        </div>
        <script>
            function toggleHide(h) {{
                const el = document.getElementById('sb-'+h); const link = el.getAttribute('data-link');
                let hiddens = JSON.parse(localStorage.getItem('tech_hiddens_v5') || '[]');
                if(!hiddens.some(i => i.l === link)) hiddens.push({{l: link, t: Math.floor(Date.now()/1000)}});
                localStorage.setItem('tech_hiddens_v5', JSON.stringify(hiddens)); el.classList.add('is-hidden');
            }}
            function restoreItem(h) {{
                const el = document.getElementById('sb-'+h); const link = el.getAttribute('data-link');
                let hiddens = JSON.parse(localStorage.getItem('tech_hiddens_v5') || '[]');
                hiddens = hiddens.filter(i => i.l !== link); localStorage.setItem('tech_hiddens_v5', JSON.stringify(hiddens));
                el.classList.remove('is-hidden');
            }}
            function toggleStar(h) {{
                const el = document.getElementById('sb-'+h); const btn = el.querySelector('.star-btn'); const link = el.getAttribute('data-link');
                let stars = JSON.parse(localStorage.getItem('tech_stars_v5') || '[]'); const idx = stars.findIndex(i => i.l === link);
                if(idx > -1) {{ stars.splice(idx, 1); btn.style.color = ''; }}
                else {{ stars.push({{l: link, t: Math.floor(Date.now()/1000)}}); btn.style.color = '#f1c40f'; }}
                localStorage.setItem('tech_stars_v5', JSON.stringify(stars));
            }}
            document.addEventListener('DOMContentLoaded', () => {{
                const now = Math.floor(Date.now() / 1000);
                let h = JSON.parse(localStorage.getItem('tech_hiddens_v5') || '[]');
                let s = JSON.parse(localStorage.getItem('tech_stars_v5') || '[]');
                h = h.filter(i => (now - i.t) < 604800); s = s.filter(i => (now - i.t) < 604800);
                localStorage.setItem('tech_hiddens_v5', JSON.stringify(h)); localStorage.setItem('tech_stars_v5', JSON.stringify(s));
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
