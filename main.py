import feedparser, datetime, pytz, os, requests, json, re, sys, time
from dateutil import parser as date_parser
from google import genai
import urllib3
from concurrent.futures import ThreadPoolExecutor

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 核心配置 ---
VERSION = "2.7.0"
SITE_TITLE = "豆子新聞戰情室"
PRIORITY_COMPANIES = ["Nvidia", "Apple", "Anthropic", "Tsmc", "Openai", "Google", "Microsoft", "Meta"]
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-1.5-flash" 

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}
FINAL_STATS = {}

def load_config():
    if os.path.exists('feeds.json'):
        try:
            with open('feeds.json', 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}}

CONFIG = load_config()

def fallback_translate(text):
    if not text or len(text) < 2: return ""
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-TW&dt=t&q={requests.utils.quote(text)}"
        resp = requests.get(url, timeout=5)
        return "".join([x[0] for x in resp.json()[0]])
    except: return text

def get_processed_content(articles, zone_name):
    if not articles: return []
    if not client: return [[a] for a in articles]
    
    print(f"\n>>> 正在生成 {zone_name} 深度翻譯摘要...")
    chunk_size = 10 
    company_map, translated_map, summary_map = {}, {}, {}

    for start in range(0, len(articles), chunk_size):
        chunk = articles[start : start + chunk_size]
        titles_input = "\n".join([f"ID_{i+start}: {a['raw_title']}" for i, a in enumerate(chunk)])
        prompt = f"翻譯標題並提供 60 字內繁中摘要。回傳 JSON: [{{'id': 編號, 'company': '公司', 'title': '翻譯標題', 'summary': '繁中摘要'}}]。待處理：{titles_input}"
        try:
            response = client.models.generate_content(model=MODEL_NAME, contents=prompt, config={'temperature': 0.1})
            json_match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                for item in data:
                    try:
                        idx = int(item['id'])
                        translated_map[idx] = item['title'].strip()
                        summary_map[idx] = item.get('summary', '').strip()
                        comp = item['company'].strip().capitalize()
                        if comp != "None":
                            if comp not in company_map: company_map[comp] = []
                            company_map[comp].append(idx)
                    except: continue
            time.sleep(1)
        except:
            for i, a in enumerate(chunk):
                idx = i + start
                translated_map[idx] = fallback_translate(a['raw_title'])
                summary_map[idx] = fallback_translate(a.get('raw_summary', ''))

    final_clusters, used_indices = [], set()
    for comp, indices in company_map.items():
        cluster = []
        is_p = any(p.capitalize() in comp for p in PRIORITY_COMPANIES)
        for idx in indices:
            if idx < len(articles) and idx not in used_indices:
                a = articles[idx]
                a['display_title'] = translated_map.get(idx, a['raw_title'])
                a['ai_summary'] = summary_map.get(idx) or fallback_translate(a.get('raw_summary', ''))
                a['is_priority'] = is_p
                cluster.append(a); used_indices.add(idx)
        if cluster: final_clusters.append(cluster)
    
    for i, a in enumerate(articles):
        if i not in used_indices:
            a['display_title'] = translated_map.get(i, a['raw_title'])
            a['ai_summary'] = summary_map.get(i) or fallback_translate(a.get('raw_summary', ''))
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
            clean_t = re.sub(r'https?://\S+|Send tips!|📩|\[.*?\]', '', entry.title).strip()
            raw_sum = re.sub(r'<[^>]+>', '', entry.get('summary', entry.get('description', '')))[:150].strip()
            if not clean_t: continue
            try: p_date = date_parser.parse(entry.get('published', entry.get('pubDate', entry.get('updated', None))), tzinfos=TZ_INFOS).astimezone(TW_TZ)
            except: p_date = datetime.datetime.now(TW_TZ)
            if p_date < limit_date: continue
            results.append({'raw_title': clean_t, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag': item['tag'], 'raw_summary': raw_sum})
            FINAL_STATS[s_name] = FINAL_STATS.get(s_name, 0) + 1
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
    print(f"Building {SITE_TITLE} v{VERSION}...")
    intl = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['INTL']), "Global")
    jk = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['JK']), "JK")
    tw = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['TW']), "Taiwan")

    def render(clusters):
        html = ""
        for g in clusters:
            m = g[0]; hid = str(abs(hash(m['link'])))[:10]
            p_style = "border-left: 4px solid #f1c40f; background: rgba(241,196,15,0.03);" if m.get('is_priority') else ""
            badge = f"<span class='badge-ithome'>iThome</span>" if "iThome" in m['tag'] else ""
            html += f"""
            <div class='story-block' id='sb-{hid}' data-link='{m['link']}' data-ts='{int(m['time'].timestamp())}' style='{p_style}'>
                <div class='grid-layout'>
                    <div class='star-col'><span class='star-btn' onclick='toggleStar("{hid}")'>★</span></div>
                    <div class='text-col'>
                        <a class='headline' href='{m['link']}' target='_blank'>{badge}{m.get('display_title', m['raw_title'])}</a>
                        <div class='summary-line'>{m.get('ai_summary', '')}</div>
                        <div class='meta-line'>{m['source']} | {m['time'].strftime('%m/%d %H:%M')}</div>
                    </div>
                    <div class='action-col'>
                        <span class='btn-restore' onclick='restoreItem("{hid}")'>恢復</span>
                        <span class='btn-hide' onclick='toggleHide("{hid}")'>隱藏</span>
                    </div>
                </div>
            """
            if len(g) > 1:
                html += "<div class='sub-news-list'>"
                for s in g[1:6]:
                    html += f"<div class='sub-item'>• <a href='{s['link']}' target='_blank'>{s.get('display_title', s['raw_title'])}</a> <span class='sub-sum'>- {s.get('ai_summary', '')}</span></div>"
                html += "</div>"
            html += "</div>"
        return html

    stats_sorted = sorted(FINAL_STATS.items(), key=lambda x: x[1], reverse=True)
    stats_html = "".join([f"<div class='stat-row'><span>{k}</span><b>{v}</b></div>" for k, v in stats_sorted])

    full_html = f"""
    <html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{SITE_TITLE}</title>
    <style>
        :root {{ --bg: #fff; --text: #333; --border: #eee; --link: #1a0dab; --hi: #3498db; --tag: #888; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #121212; --text: #e0e0e0; --border: #2c2c2c; --link: #8ab4f8; --tag: #9aa0a6; }} }}
        * {{ box-sizing: border-box; }}
        body {{ font-family: sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0 15px 50px 15px; line-height: 1.5; }}
        .header {{ padding: 10px 0; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 1000; }}
        .wrapper {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }}
        @media (max-width: 1000px) {{ .wrapper {{ grid-template-columns: 1fr; }} }}
        .river-title {{ font-size: 16px; font-weight: 900; border-bottom: 2px solid var(--text); margin: 10px 0; }}
        .story-block {{ padding: 12px 0; border-bottom: 1px solid var(--border); }}
        .story-block.is-hidden {{ display: none; }}
        body.show-hidden .story-block.is-hidden {{ display: block !important; opacity: 0.4; }}
        .grid-layout {{ display: grid; grid-template-columns: 24px 1fr 75px; gap: 8px; align-items: flex-start; }}
        .text-col {{ min-width: 0; }}
        .action-col {{ text-align: right; font-size: 11px; padding-top: 3px; }}
        .headline {{ font-size: 15px; font-weight: 800; text-decoration: none; color: var(--link); line-height: 1.4; word-break: break-word; }}
        .summary-line {{ font-size: 13px; color: #555; margin-top: 6px; line-height: 1.6; }}
        .meta-line {{ font-size: 10px; color: var(--tag); margin-top: 6px; }}
        .sub-news-list {{ margin: 8px 0 0 32px; border-left: 1px solid var(--border); padding-left: 12px; }}
        .sub-item {{ font-size: 12.5px; margin-bottom: 4px; opacity: 0.8; }}
        .sub-sum {{ font-size: 11.5px; color: #888; }}
        @media (prefers-color-scheme: dark) {{ .summary-line {{ color: #bbb; }} .sub-sum {{ color: #777; }} }}
        .badge-ithome {{ background: var(--hi); color: #fff; padding: 1px 4px; font-size: 8px; border-radius: 2px; margin-right: 4px; }}
        .star-btn {{ cursor: pointer; color: var(--tag); font-size: 15px; }}
        .btn-hide, .btn-restore {{ cursor: pointer; color: var(--tag); }}
        .btn-restore {{ color: var(--hi); display: none; font-weight: bold; }}
        body.show-hidden .btn-restore {{ display: inline-block; }}
        .btn {{ cursor: pointer; padding: 4px 10px; border: 1px solid var(--border); font-size: 11px; border-radius: 4px; background: var(--bg); color: var(--text); font-weight: bold; }}
        
        /* 統計儀表板樣式 */
        #stats-dashboard {{ display: none; background: var(--bg); border: 1px solid var(--border); padding: 15px; border-radius: 8px; margin: 15px 0; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }}
        .stat-row {{ display: flex; justify-content: space-between; font-size: 12px; padding: 4px 8px; background: var(--border); border-radius: 4px; }}
        #starred-area {{ background: rgba(241,196,15,0.05); padding: 10px; border-radius: 8px; margin-bottom: 20px; border: 1px dashed #f1c40f; display: none; }}
    </style></head><body>
        <div class='header'>
            <h1 style='margin:0; font-size:16px;'>{SITE_TITLE} v{VERSION}</h1>
            <div style='display:flex; gap:8px;'>
                <span class='btn' onclick='toggleStats()'>來源統計</span>
                <span class='btn' onclick='document.body.classList.toggle("show-hidden")'>顯示已隱藏</span>
                <span class='btn' onclick='location.reload()'>重新整理</span>
            </div>
        </div>
        
        <div id='stats-dashboard' style='display: none;'>{stats_html}</div>
        <div id='starred-area'><div class='river-title' style='color:#f1c40f; border-color:#f1c40f;'>Starred Stories</div><div id='starred-list'></div></div>

        <div class='wrapper'>
            <div class='river'><div class='river-title'>Global</div>{render(intl)}</div>
            <div class='river'><div class='river-title'>JK</div>{render(jk)}</div>
            <div class='river'><div class='river-title'>Taiwan</div>{render(tw)}</div>
        </div>

        <script>
            function toggleStats() {{
                const d = document.getElementById('stats-dashboard');
                d.style.display = (d.style.display === 'none' || d.style.display === '') ? 'grid' : 'none';
            }}
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
                localStorage.setItem('tech_stars_v5', JSON.stringify(stars)); updateStarredArea();
            }}
            function updateStarredArea() {{
                const area = document.getElementById('starred-area'); const list = document.getElementById('starred-list');
                const stars = JSON.parse(localStorage.getItem('tech_stars_v5') || '[]'); list.innerHTML = '';
                if(stars.length > 0) {{
                    area.style.display = 'block';
                    stars.forEach(s => {{
                        const original = document.querySelector(`.story-block[data-link="${{s.l}}"]`);
                        if(original) {{ const clone = original.cloneNode(true); clone.id = 'star-copy-' + clone.id; list.appendChild(clone); }}
                    }});
                }} else {{ area.style.display = 'none'; }}
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
                updateStarredArea();
            }});
        </script></body></html>
    """
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__":
    main()
