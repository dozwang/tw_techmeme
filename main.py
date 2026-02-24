import feedparser, datetime, pytz, os, difflib, requests, json, re, time, sys
from dateutil import parser as date_parser
from google import genai
from bs4 import BeautifulSoup
import urllib3

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 核心配置 ---
VERSION = "1.8.8"
SITE_TITLE = "豆子新聞戰情室"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

client = None
if GEMINI_KEY:
    client = genai.Client(api_key=GEMINI_KEY)

TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}
FINAL_STATS = {}
TOTAL_TOKENS = 0  # 累計預估消耗

def load_config():
    if os.path.exists('feeds.json'):
        try:
            with open('feeds.json', 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                for zone in ["INTL", "JK", "TW"]:
                    cfg["FEEDS"][zone] = [i for i in cfg["FEEDS"][zone] if "nitter" not in i["url"] or "bnext" not in i["url"]]
                return cfg
        except: pass
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}, "WHITELIST": [], "TERM_MAP": {}}

CONFIG = load_config()

def get_ai_keywords(cluster):
    global TOTAL_TOKENS
    if not client: return []
    TOTAL_TOKENS += 350 # AI 處理基數
    titles = [c['raw_title'] for c in cluster]
    prompt = f"請針對以下科技新聞標題，提取 3-5 個中文關鍵字標籤，用逗號隔開：\n" + "\n".join(titles)
    try:
        response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt, config={'temperature': 0.0})
        kw_str = response.text.replace('、', ',').replace(' ', '')
        return [k.strip() for k in kw_str.split(',') if k.strip()][:5]
    except: return []

def validate_and_tag_group(cluster):
    global TOTAL_TOKENS
    if not client or len(cluster) < 2: 
        return [{"group": cluster, "kws": get_ai_keywords(cluster) if client else []}]
    
    TOTAL_TOKENS += 300 # 聚合判斷基數
    titles = [f"- {c['raw_title']}" for c in cluster]
    prompt = f"判斷以下新聞是否屬於同一個具體技術事件，回傳 YES 或 NO：\n" + "\n".join(titles)
    try:
        res = client.models.generate_content(model="gemini-1.5-flash", contents=prompt, config={'temperature':0.0})
        if "YES" in res.text.upper():
            return [{"group": cluster, "kws": get_ai_keywords(cluster)}]
        else:
            return [{"group": [c], "kws": get_ai_keywords([c])} for c in cluster]
    except:
        return [{"group": cluster, "kws": []}]

def cluster_articles(articles, is_tw=False):
    if not articles: return []
    temp_clusters = []
    # 簡單預篩選，減少 AI 調用
    for art in sorted(articles, key=lambda x: x['time']):
        pure_t = re.sub(r'【[^】]*】|\[[^\]]*\]', '', art['raw_title']).strip()
        best_match_idx = -1
        for idx, cluster in enumerate(temp_clusters):
            main_t = re.sub(r'【[^】]*】|\[[^\]]*\]', '', cluster[0]['raw_title']).strip()
            sim = difflib.SequenceMatcher(None, main_t, pure_t).ratio()
            if sim > 0.45:
                best_match_idx = idx; break
        if best_match_idx != -1: temp_clusters[best_match_idx].append(art)
        else: temp_clusters.append([art])
    
    final_output = []
    for group in temp_clusters:
        final_output.extend(validate_and_tag_group(group))
    return sorted(final_output, key=lambda x: x['group'][0]['time'], reverse=True)

def fetch_data(feed_list):
    global TOTAL_TOKENS
    all_articles = []
    now_tw = datetime.datetime.now(TW_TZ)
    for item in feed_list:
        try:
            resp = requests.get(item['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=25, verify=False)
            feed = feedparser.parse(resp.content)
            s_name = (feed.feed.title if 'title' in feed.feed else item['url'].split('/')[2]).split('|')[0].strip()[:12]
            for entry in feed.entries[:18]:
                title = re.sub(r'https?://\S+', '', entry.title).strip()
                if not title: continue
                TOTAL_TOKENS += 50 # 翻譯與標題處理
                try: p_date = date_parser.parse(entry.get('published', entry.get('pubDate', entry.get('updated', None))), tzinfos=TZ_INFOS).astimezone(TW_TZ)
                except: p_date = now_tw
                all_articles.append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag': item['tag']})
                FINAL_STATS[s_name] = FINAL_STATS.get(s_name, 0) + 1
        except: continue
    return all_articles

def main():
    intl_raw = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_raw = fetch_data(CONFIG['FEEDS']['JK'])
    tw_raw = fetch_data(CONFIG['FEEDS']['TW'])
    
    intl_c = cluster_articles(intl_raw)
    jk_c = cluster_articles(jk_raw)
    tw_c = cluster_articles(tw_raw, is_tw=True)

    # 渲染統計區：增加 Token 顯示
    stats_header = f"<div class='token-bar'>💰 預估 Token 消耗：<strong>{TOTAL_TOKENS}</strong> (Input + Output)</div>"
    stats_rows = "".join([f"<li><span class='s-label'>{k}</span><span class='s-bar'><i style='width:{min(v*5,100)}%'></i></span><span class='s-count'>{v}</span></li>" for k,v in sorted(FINAL_STATS.items(), key=lambda x:x[1], reverse=True)])

    def render(clusters, need_trans):
        html = ""
        from googletrans import Translator
        translator = Translator()
        for item in clusters:
            g = item['group']; kws = item['kws']; m = g[0]
            display_t = m['raw_title']
            if need_trans:
                try: display_t = translator.translate(display_t, dest='zh-tw').text
                except: pass
            hid = str(abs(hash(m['link'])))[:10]
            badge = f'<span class="badge-ithome">iThome</span>' if "iThome" in m['tag'] else ""
            kw_html = "".join([f"<span class='kw-tag'>{k}</span>" for k in kws])
            
            html += f"""
            <div class='story-block' id='sb-{hid}' data-link='{m['link']}'>
                <div class='headline-wrapper'>
                    <span class='star-btn' onclick='toggleStar("{hid}")'>★</span>
                    <div class='head-main'>
                        {badge}<a class='headline' href='{m['link']}' target='_blank'>{display_t}</a>
                        <div class='kw-container'>{kw_html}</div>
                    </div>
                    <span class='btn-hide' onclick='toggleHide("{hid}")'>✕</span>
                </div>
                <div class='meta-line'>{m['source']} | {m['time'].strftime('%m/%d %H:%M')}</div>
            """
            if len(g) > 1:
                html += "<div class='sub-news-list'>"
                for s in g[1:4]:
                    html += f"<div class='sub-item'>• <a href='{s['link']}' target='_blank'>{s['raw_title'][:40]}...</a></div>"
                html += "</div>"
            html += "</div>"
        return html

    full_html = f"""
    <html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{SITE_TITLE}</title>
    <style>
        :root {{ --bg: #fff; --text: #333; --border: #eee; --link: #1a0dab; --hi: #3498db; --tag: #888; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #121212; --text: #e0e0e0; --border: #2c2c2c; --link: #8ab4f8; --tag: #9aa0a6; }} }}
        * {{ box-sizing: border-box; }}
        body {{ font-family: sans-serif; background: var(--bg); color: var(--text); margin: 0; padding-bottom: 50px; }}
        .header {{ padding: 10px 15px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 1000; }}
        #stats-p {{ display: none; padding: 15px; background: #8881; border-bottom: 1px solid var(--border); }}
        .token-bar {{ background: var(--hi); color: #fff; padding: 5px 12px; border-radius: 4px; font-size: 12px; margin-bottom: 10px; display: inline-block; }}
        #stats-p ul {{ list-style: none; padding: 0; margin: 0; column-count: 2; column-gap: 30px; }}
        @media (max-width: 600px) {{ #stats-p ul {{ column-count: 1; }} }}
        #stats-p li {{ font-size: 11px; margin-bottom: 6px; break-inside: avoid; display: flex; align-items: center; justify-content: space-between; }}
        .s-label {{ width: 85px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }}
        .s-bar {{ flex-grow: 1; height: 4px; background: #8882; margin: 0 10px; border-radius: 2px; }}
        .s-bar i {{ display: block; height: 100%; background: var(--hi); border-radius: 2px; }}
        .wrapper {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; background: var(--border); }}
        @media (max-width: 900px) {{ .wrapper {{ grid-template-columns: 1fr; }} }}
        .river {{ background: var(--bg); padding: 15px; min-width: 0; }}
        .river-title {{ font-size: 16px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 12px; }}
        .story-block {{ padding: 8px 0; border-bottom: 1px solid var(--border); }}
        .headline {{ font-size: 14px; font-weight: 800; text-decoration: none; color: var(--link); }}
        .kw-tag {{ background: #8881; color: var(--tag); font-size: 9px; padding: 1px 6px; border-radius: 4px; margin-right: 4px; }}
        .meta-line {{ font-size: 10px; color: var(--tag); margin-top: 5px; margin-left: 22px; }}
        .badge-ithome {{ background: var(--hi); color: #fff; padding: 1px 4px; font-size: 8px; border-radius: 2px; font-weight: 800; margin-right: 5px; }}
        .btn {{ cursor: pointer; padding: 4px 10px; border: 1px solid var(--border); font-size: 11px; border-radius: 4px; background: var(--bg); color: var(--text); font-weight: bold; }}
    </style></head><body>
        <div class='header'>
            <h1 style='margin:0; font-size:16px;'>{SITE_TITLE} v{VERSION}</h1>
            <div><span class='btn' onclick='document.getElementById("stats-p").style.display=(document.getElementById("stats-p").style.display==="block")?"none":"block"'>📊 分析</span> <span class='btn' onclick='location.reload()'>🔄</span></div>
        </div>
        <div id='stats-p'>{stats_header}<ul>{stats_rows}</ul></div>
        <div class='wrapper'>
            <div class='river'><div class='river-title'>Global</div>{render(intl_c, True)}</div>
            <div class='river'><div class='river-title'>JK</div>{render(jk_c, True)}</div>
            <div class='river'><div class='river-title'>Taiwan</div>{render(tw_c, False)}</div>
        </div>
        <script>
            function toggleHide(h) {{
                const el = document.getElementById('sb-'+h); const l = el.getAttribute('data-link');
                let hds = JSON.parse(localStorage.getItem('tech_hiddens')||'[]');
                if(hds.includes(l)) hds = hds.filter(i=>i!==l); else hds.push(l);
                localStorage.setItem('tech_hiddens', JSON.stringify(hds)); el.style.display = 'none';
            }}
            function toggleStar(h) {{
                const el = document.getElementById('sb-'+h); const btn = el.querySelector('.star-btn'); const l = el.getAttribute('data-link');
                let s = JSON.parse(localStorage.getItem('tech_stars')||'[]');
                if(s.includes(l)) {{ s=s.filter(i=>i!==l); btn.style.color = '#444'; }} 
                else {{ s.push(l); btn.style.color = '#f1c40f'; }}
                localStorage.setItem('tech_stars', JSON.stringify(s));
            }}
        </script></body></html>
    """
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__":
    main()
