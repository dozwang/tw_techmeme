import feedparser, datetime, pytz, os, difflib, requests, json, re, time, random
from dateutil import parser as date_parser
from googletrans import Translator
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 版本資訊 ---
VERSION = "1.1.5"
SITE_TITLE = f"豆子版 Techmeme | v{VERSION}"

TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific"), "JST": pytz.timezone("Asia/Tokyo"), "KST": pytz.timezone("Asia/Seoul")}
translator = Translator()
FINAL_STATS = {}
DIAGNOSTIC_LOGS = []

def load_config():
    if os.path.exists('feeds.json'):
        try:
            with open('feeds.json', 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}, "WHITELIST": [], "BLACKLIST_GENERAL": [], "BLACKLIST_TECH_RELATED": [], "TERM_MAP": {}}

CONFIG = load_config()

def translate_text(text):
    if not text: return ""
    try:
        res = translator.translate(text, dest='zh-tw').text
        term_map = CONFIG.get('TERM_MAP', {})
        for wrong, right in term_map.items(): res = res.replace(wrong, right)
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

def clean_x_title(text):
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\s\S+\.(com|org|net|me|gov|io|edu|tv)(\/\S*)?\s?$', '', text)
    return text.strip().rstrip(' ;:,.')

def badge_styler(tag_str):
    """【v1.1.5 新增】日韓專屬標籤顏色與多標籤渲染"""
    if not tag_str: return ""
    clean_tags = re.findall(r'\[(.*?)\]', tag_str)
    badges = ""
    for t in clean_tags:
        cls = "badge-default"
        if "X" in t: cls = "badge-x"
        elif "分析" in t: cls = "badge-analysis"
        elif "資安" in t: cls = "badge-sec"
        elif "醫療" in t: cls = "badge-med"
        elif "WSJ" in t: cls = "badge-wsj"
        elif "日" in t: cls = "badge-jp"     # 日本標籤
        elif "韓" in t: cls = "badge-kr"     # 韓國標籤
        elif "數位" in t: cls = "badge-digital"
        badges += f'<span class="badge {cls}">{t}</span>'
    return badges

def fetch_from_html(name, url, selectors, tag_html, item_tags_selector=None):
    articles = []
    FINAL_STATS[name] = 0
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    }
    try:
        resp = requests.get(url, headers=headers, timeout=25, verify=False)
        if resp.status_code != 200:
            DIAGNOSTIC_LOGS.append(f"❌ {name}: HTTP {resp.status_code}"); return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = []
        for sel in selectors:
            items = soup.select(sel)
            if items: break
        for item in items[:15]:
            # 針對數位時代的特殊處理：找到 item_title 內的連結
            title_tag = item.select_one('.item_title, h3, a') if name == "數位時代" else item
            if not title_tag: continue
            
            link_tag = title_tag if title_tag.name == 'a' else title_tag.find('a')
            if not link_tag: continue
            
            title = link_tag.get_text().strip()
            link = link_tag.get('href', '')
            
            if not title or len(title) < 5 or is_blacklisted(title): continue
            if link.startswith('/'): link = "/".join(url.split('/')[:3]) + link
            
            item_tags = ""
            if item_tags_selector:
                # 往上回朔找容器中的分類標籤
                parent = item.find_parent(class_=re.compile(r'item|box|card')) or item.parent
                tag_el = parent.select_one(item_tags_selector) if parent else None
                if tag_el: item_tags = tag_el.get_text().strip()

            articles.append({'raw_title': title, 'link': link, 'source': name, 'time': datetime.datetime.now(TW_TZ), 'tag_html': tag_html, 'item_tags': item_tags})
            FINAL_STATS[name] += 1
        DIAGNOSTIC_LOGS.append(f"✅ {name}: 抓取成功 ({FINAL_STATS[name]} 則)")
    except Exception as e:
        DIAGNOSTIC_LOGS.append(f"❌ {name}: 異常 ({str(e)[:30]})")
    return articles

def fetch_data(feed_list):
    data_by_date, seen = {}, []
    now_utc = datetime.datetime.now(pytz.utc)
    limit_time = now_utc - datetime.timedelta(hours=96)
    for item in feed_list:
        url, tag = item['url'], item['tag']
        is_x = "nitter" in url.lower()
        # 跳過 RSS 抓不到的站點
        if any(x in url for x in ["cio.com.tw", "bnext.com.tw"]): continue
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
            feed = feedparser.parse(resp.content)
            s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            s_name = s_name.split('|')[0].split('-')[0].strip()[:18]
            FINAL_STATS[s_name] = 0
            for entry in feed.entries[:25]:
                title = clean_x_title(entry.title) if is_x else entry.title.strip()
                if is_blacklisted(title) or any(is_similar(title, s) for s in seen): continue
                keywords = []
                if 'tags' in entry: keywords = [t.term for t in entry.tags if t.term]
                elif 'category' in entry: keywords = [entry.category]
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                try: p_date = date_parser.parse(raw_date, tzinfos=TZ_INFOS).astimezone(pytz.utc)
                except: p_date = now_utc
                if p_date < limit_time: continue
                date_str = p_date.astimezone(TW_TZ).strftime('%Y-%m-%d')
                data_by_date.setdefault(date_str, []).append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date.astimezone(TW_TZ), 'tag_html': tag, 'item_tags': " / ".join(keywords[:2])})
                seen.append(title); FINAL_STATS[s_name] += 1
        except: continue
    return data_by_date

def render_column(data, title, need_trans=False):
    html = f"<div class='river'><div class='river-title'>{title}</div>"
    sorted_dates = sorted(data.keys(), reverse=True)
    if not sorted_dates: html += "<div style='color:#888; padding:20px;'>區間內無更新</div>"
    for d_str in sorted_dates:
        html += f"<div class='date-header'>{d_str}</div>"
        for art in data[d_str]:
            display_title = highlight_keywords(translate_text(art['raw_title']) if need_trans else art['raw_title'])
            display_tags = translate_text(art['item_tags']) if (need_trans and art['item_tags']) else art['item_tags']
            badges = badge_styler(art['tag_html'])
            link_hash = str(abs(hash(art['link'])))[:10]
            tags_part = f"<span class='story-tags'>{display_tags}</span> · " if display_tags else ""
            html += f"""
            <div class='story-block' id='sb-{link_hash}' data-link='{art['link']}'>
                <div class='headline-wrapper'>
                    <span class='star-btn' onclick='toggleStar("{link_hash}")'>★</span>
                    <div style='display: flex; align-items: flex-start;'>
                        {badges}
                        <a class='headline' href='{art['link']}' target='_blank'>{display_title}</a>
                    </div>
                </div>
                <div class='meta-line'>{tags_part}{art['source']} | {art['time'].strftime('%H:%M')}</div>
            </div>"""
    return html + "</div>"

def main():
    print(f">>> [v{VERSION}] 啟動深度抓取與標籤顯色...")
    intl_raw = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_raw = fetch_data(CONFIG['FEEDS']['JK'])
    tw_raw = fetch_data(CONFIG['FEEDS']['TW'])
    
    # --- 強攻選擇器優化 (針對 2026 版) ---
    special_sites = [
        ("CIO Taiwan", "https://www.cio.com.tw/category/it-strategy/", ["h3 a", ".entry-title a"], "[分析]", ".category-label"),
        ("數位時代", "https://www.bnext.com.tw/articles", [".item_box", ".post_item"], "[數位]", ".item_tag")
    ]
    today_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d')
    for name, url, sels, tag, tag_sel in special_sites:
        arts = fetch_from_html(name, url, sels, tag, tag_sel)
        tw_raw.setdefault(today_str, []).extend(arts)

    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    stats_list = "".join([f"<li>{v} - {k}</li>" for k, v in sorted(FINAL_STATS.items(), key=lambda x: x[1], reverse=True)])
    diag_html = "".join([f"<div style='margin-bottom:5px;'>{log}</div>" for log in DIAGNOSTIC_LOGS])

    full_html = f"""
    <html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{SITE_TITLE}</title>
    <style>
        :root {{ --bg: #fff; --text: #333; --border: #eee; --link: #1a0dab; --hi: #ff98001a; --kw: #e67e22; --tag: #888; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #111; --text: #ddd; --border: #222; --link: #8ab4f8; --tag: #777; }} }}
        body {{ font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.5; padding-bottom: 50px; }}
        .header {{ padding: 12px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 1000; }}
        .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1px; background: var(--border); }}
        @media (max-width: 900px) {{ .wrapper {{ grid-template-columns: 1fr; }} }}
        .river {{ background: var(--bg); padding: 14px; }}
        .river-title {{ font-size: 18px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 15px; }}
        .date-header {{ background: #444; color: #fff; padding: 2px 8px; font-size: 10px; margin: 12px 0 6px; border-radius: 4px; display: inline-block; font-weight:bold; }}
        .story-block {{ padding: 12px 0; border-bottom: 1px solid var(--border); }}
        .headline {{ color: var(--link); text-decoration: none; font-size: 15px; font-weight: 600; line-height: 1.4; }}
        .meta-line {{ font-size: 11px; color: var(--tag); margin-top: 5px; margin-left: 28px; }}
        .story-tags {{ font-style: italic; color: var(--tag); }}
        
        /* 膠囊標籤 v1.1.5 版 */
        .badge {{ display: inline-block; padding: 1px 6px; font-size: 10px; border-radius: 4px; margin-right: 6px; font-weight: 800; line-height: 16px; white-space: nowrap; height: 18px; align-self: flex-start; margin-top: 2px; }}
        .badge-x {{ background: #1da1f2 !important; color: #fff !important; }}
        .badge-analysis {{ background: #673ab7 !important; color: #fff !important; }}
        .badge-sec {{ background: #e91e63 !important; color: #fff !important; }}
        .badge-wsj {{ background: #333 !important; color: #fff !important; }}
        .badge-jp {{ background: #ff5722 !important; color: #fff !important; }} /* 日本: 橘紅 */
        .badge-kr {{ background: #303f9f !important; color: #fff !important; }} /* 韓國: 深藍 */
        .badge-digital {{ background: #27ae60 !important; color: #fff !important; }}
        .badge-default {{ background: #888; color: #fff; }}

        .star-btn {{ cursor: pointer; color: #ddd; font-size: 18px; margin-right: 10px; float: left; }}
        .star-btn.active {{ color: #f1c40f; }}
        .kw-highlight {{ color: var(--kw); font-weight: bold; background: #ff980015; }}
        .btn {{ cursor: pointer; padding: 5px 12px; border: 1px solid var(--text); font-size: 11px; border-radius: 6px; background: var(--bg); color: var(--text); font-weight: bold; }}
        .debug-footer {{ margin-top: 50px; padding: 20px; background: #8882; color: #888; font-family: monospace; font-size: 12px; border-top: 2px solid var(--border); }}
        body.only-stars .story-block:not(.has-star) {{ display: none; }}
    </style></head><body>
        <div class='header'><h1 style='margin:0; font-size:20px;'>{SITE_TITLE}</h1>
        <div><span class='btn' onclick='toggleStats()'>📊 統計</span> <span class='btn' onclick='document.body.classList.toggle("only-stars")'>★ 精選</span></div></div>
        <div id='stats-panel' style='display:none; padding:15px; background:#8882; border-bottom:1px solid var(--border); font-size:11px;'><ul style='column-count:3; list-style:none; padding:0; margin:0;'>{stats_list}</ul></div>
        <div class='wrapper'>{render_column(intl_raw, "Global Strategy", True)}{render_column(jk_raw, "Japan/Korea", True)}{render_column(tw_raw, "Taiwan Tech", False)}</div>
        <div class='debug-footer'><h3>🛠️ 診斷報告</h3>{diag_html}</div>
        <script>
            function toggleStats() {{ const p = document.getElementById('stats-panel'); p.style.display = (p.style.display==='block')?'none':'block'; }}
            function toggleStar(h) {{
                const el = document.getElementById('sb-'+h); const btn = el.querySelector('.star-btn'); const link = el.getAttribute('data-link');
                let s = JSON.parse(localStorage.getItem('tech_stars')||'[]');
                if(s.includes(link)) {{ s=s.filter(i=>i!==link); el.classList.remove('has-star'); btn.classList.remove('active'); }}
                else {{ s.push(link); el.classList.add('has-star'); btn.classList.add('active'); }}
                localStorage.setItem('tech_stars', JSON.stringify(s));
            }}
            document.addEventListener('DOMContentLoaded', () => {{
                const s = JSON.parse(localStorage.getItem('tech_stars')||'[]');
                document.querySelectorAll('.story-block').forEach(el => {{
                    if(s.includes(el.getAttribute('data-link'))) {{ el.classList.add('has-star'); el.querySelector('.star-btn').classList.add('active'); }}
                }});
            }});
        </script></body></html>
    """
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__":
    main()
