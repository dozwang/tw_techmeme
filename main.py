import feedparser, datetime, pytz, os, difflib, requests, json, re, time
from dateutil import parser as date_parser
from googletrans import Translator
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 基礎設定 ---
TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific"), "JST": pytz.timezone("Asia/Tokyo"), "KST": pytz.timezone("Asia/Seoul")}
translator = Translator()
SITE_TITLE = "豆子版 Techmeme | 2026.v1"

def load_config():
    if os.path.exists('feeds.json'):
        with open('feeds.json', 'r', encoding='utf-8') as f: return json.load(f)
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}, "WHITELIST": [], "BLACKLIST_GENERAL": [], "BLACKLIST_TECH_RELATED": [], "TERM_MAP": {}}

CONFIG = load_config()

def translate_text(text):
    if not text: return ""
    try:
        res = translator.translate(text, dest='zh-tw').text
        # 套用自定義詞彙表
        for wrong, right in CONFIG.get('TERM_MAP', {}).items():
            res = res.replace(wrong, right)
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

def is_similar(a, b): return difflib.SequenceMatcher(None, a, b).ratio() > 0.4

def fetch_data(feed_list):
    data_by_date, stats, seen = {}, {}, []
    now_utc = datetime.datetime.now(pytz.utc)
    limit_time = now_utc - datetime.timedelta(hours=48)
    for item in feed_list:
        url, tag = item['url'], item['tag']
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            feed = feedparser.parse(resp.content)
            s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            s_name = s_name.split('|')[0].split('-')[0].strip()[:15]
            stats[s_name] = 0
            for entry in feed.entries[:20]:
                title = entry.title.strip()
                # 過濾重複與黑名單
                if is_blacklisted(title) or any(is_similar(title, s) for s in seen): continue
                
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                try: p_date = date_parser.parse(raw_date, tzinfos=TZ_INFOS).astimezone(pytz.utc)
                except: p_date = now_utc
                if p_date < limit_time: continue
                
                p_date_tw = p_date.astimezone(TW_TZ)
                date_str = p_date_tw.strftime('%Y-%m-%d')
                data_by_date.setdefault(date_str, []).append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date_tw, 'tag_html': tag})
                seen.append(title); stats[s_name] += 1
        except: continue
    return data_by_date, stats, seen

def render_column(data, title, need_trans=False):
    html = f"<div class='river'><div class='river-title'>{title}</div>"
    sorted_dates = sorted(data.keys(), reverse=True)
    for d_str in sorted_dates:
        html += f"<div class='date-header'>{d_str}</div>"
        for art in data[d_str]:
            display_title = translate_text(art['raw_title']) if need_trans else art['raw_title']
            display_title = highlight_keywords(display_title)
            link_hash = str(abs(hash(art['link'])))[:10]
            html += f"""
            <div class='story-block' id='sb-{link_hash}' data-link='{art['link']}'>
                <div class='headline-wrapper'>
                    <span class='star-btn' onclick='toggleStar("{link_hash}")'>★</span>
                    <a class='headline' href='{art['link']}' target='_blank'>{art['tag_html']} {display_title}</a>
                </div>
                <div class='meta'>{art['source']} | {art['time'].strftime('%H:%M')}</div>
            </div>"""
    return html + "</div>"

def main():
    print(">>> [1/2] 正在同步大數據與黑名單過濾中...", flush=True)
    intl_raw, intl_st, _ = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_raw, jk_st, _ = fetch_data(CONFIG['FEEDS']['JK'])
    tw_raw, tw_st, _ = fetch_data(CONFIG['FEEDS']['TW'])

    print(">>> [2/2] 翻譯與卡片儀表板產出中...", flush=True)
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    
    all_stats = {**intl_st, **jk_st, **tw_st}
    stats_cards = ""
    for k, v in sorted(all_stats.items(), key=lambda x: x[1], reverse=True):
        status_color = "#27ae60" if v > 0 else "#e74c3c"
        stats_cards += f"<div class='stat-card' style='border-top:3px solid {status_color};'><div class='s-name'>{k}</div><div class='s-value'>{v}</div></div>"

    full_html = f"""
    <html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{SITE_TITLE}</title>
    <style>
        :root {{ --bg: #fff; --text: #333; --border: #eee; --link: #1a0dab; --hi: #ff98001a; --kw: #e67e22; --card-bg: #f8f9fa; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #1a1a1a; --text: #ccc; --border: #333; --link: #8ab4f8; --card-bg: #2d2d2d; }} }}
        body {{ font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; }}
        .header {{ padding: 12px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 1000; }}
        #stats-panel {{ display: none; padding: 20px; background: var(--card-bg); border-bottom: 1px solid var(--border); }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 10px; }}
        .stat-card {{ padding: 8px; border-radius: 6px; background: var(--bg); border: 1px solid var(--border); text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .s-name {{ font-size: 10px; color: #888; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }}
        .s-value {{ font-size: 16px; font-weight: bold; margin-top: 2px; }}
        .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1px; background: var(--border); }}
        @media (max-width: 900px) {{ .wrapper {{ grid-template-columns: 1fr; }} }}
        .river {{ background: var(--bg); padding: 15px; }}
        .river-title {{ font-size: 18px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 15px; padding-bottom: 5px; }}
        .date-header {{ background: #555; color: #fff; padding: 2px 10px; font-size: 11px; margin: 15px 0 8px; border-radius: 3px; display: inline-block; }}
        .story-block {{ padding: 10px 0; border-bottom: 1px solid var(--border); }}
        .story-block.has-star {{ background: var(--hi); border-left: 4px solid #f1c40f; padding-left: 8px; }}
        .headline {{ color: var(--link); text-decoration: none; font-size: 15px; font-weight: bold; line-height: 1.4; }}
        .meta {{ font-size: 11px; color: #888; margin-top: 5px; }}
        .star-btn {{ cursor: pointer; color: #ddd; font-size: 18px; margin-right: 8px; }}
        .star-btn.active {{ color: #f1c40f; }}
        .kw-highlight {{ color: var(--kw); font-weight: bold; }}
        .btn {{ cursor: pointer; padding: 5px 12px; border: 1px solid var(--text); font-size: 12px; border-radius: 4px; font-weight: bold; background: var(--bg); color: var(--text); }}
        body.only-stars .story-block:not(.has-star) {{ display: none; }}
    </style></head><body>
        <div class='header'>
            <h1 style='margin:0; font-size:20px;'>{SITE_TITLE}</h1>
            <div>
                <span class='btn' onclick='toggleStats()'>📊 來源統計</span>
                <span class='btn' onclick='document.body.classList.toggle("only-stars")'>★ 精選</span>
                <small style='margin-left:10px; font-size:10px; color:#888;'>{now_str}</small>
            </div>
        </div>
        <div id='stats-panel'><div class='stats-grid'>{stats_cards}</div></div>
        <div class='wrapper'>
            {render_column(intl_raw, "Global Strategy", True)}
            {render_column(jk_raw, "Japan/Korea", True)}
            {render_column(tw_raw, "Taiwan Tech", False)}
        </div>
        <script>
            function toggleStats() {{ const p = document.getElementById('stats-panel'); p.style.display = (p.style.display==='block')?'none':'block'; }}
            function toggleStar(h) {{
                const el = document.getElementById('sb-'+h);
                const btn = el.querySelector('.star-btn');
                const link = el.getAttribute('data-link');
                let s = JSON.parse(localStorage.getItem('tech_stars')||'[]');
                if(s.includes(link)) {{ s=s.filter(i=>i!==link); el.classList.remove('has-star'); btn.classList.remove('active'); }}
                else {{ s.push(link); el.classList.add('has-star'); btn.classList.add('active'); }}
                localStorage.setItem('tech_stars', JSON.stringify(s));
            }}
            function init() {{
                const s = JSON.parse(localStorage.getItem('tech_stars')||'[]');
                document.querySelectorAll('.story-block').forEach(el => {{
                    if(s.includes(el.getAttribute('data-link'))) {{
                        el.classList.add('has-star'); el.querySelector('.star-btn').classList.add('active');
                    }}
                }});
            }}
            document.addEventListener('DOMContentLoaded', init);
        </script>
    </body></html>
    """
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)
    print(">>> [成功] 戰情室完整復活且具備過濾功能！", flush=True)

if __name__ == "__main__":
    main()
