import feedparser, datetime, pytz, os, difflib, requests, json, re, time, random
from dateutil import parser as date_parser
from googletrans import Translator
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 版本資訊 ---
VERSION = "1.2.4"
SITE_TITLE = f"豆子版 Techmeme | v{VERSION}"

TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific"), "JST": pytz.timezone("Asia/Tokyo"), "KST": pytz.timezone("Asia/Seoul")}
translator = Translator()
FINAL_STATS = {}

NOISE_WORDS = ["快訊", "獨家", "Breaking", "Live", "Update", "更新", "最新", "直擊", "影", "圖", "報導", "Exclusive"]

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

def clean_x_title(text):
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\s\S+\.(com|org|net|me|gov|io|edu|tv)(\/\S*)?\s?$', '', text)
    return text.strip().rstrip(' ;:,.')

def badge_styler(tag_str):
    if not tag_str: return ""
    clean_tags = re.findall(r'\[(.*?)\]', tag_str)
    badges = ""
    for t in clean_tags:
        cls = "badge-default"
        if "X" in t: cls = "badge-x"
        elif "分析" in t: cls = "badge-analysis"
        elif "資安" in t: cls = "badge-sec"
        elif "日" in t: cls = "badge-jp"
        elif "韓" in t: cls = "badge-kr"
        elif "數位" in t: cls = "badge-digital"
        badges += f'<span class="badge {cls}">{t}</span>'
    return badges

def fetch_data(feed_list):
    all_articles = []
    now_tw = datetime.datetime.now(TW_TZ)
    limit_time = now_tw - datetime.timedelta(hours=96)
    for item in feed_list:
        url, tag = item['url'], item['tag']
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
            feed = feedparser.parse(resp.content)
            s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            s_name = s_name.split('|')[0].split('-')[0].strip()[:18]
            FINAL_STATS[s_name] = 0
            for entry in feed.entries[:25]:
                title = clean_x_title(entry.title) if "nitter" in url else entry.title.strip()
                if is_blacklisted(title): continue
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                try: p_date = date_parser.parse(raw_date, tzinfos=TZ_INFOS).astimezone(TW_TZ)
                except: p_date = now_tw
                if p_date < limit_time: continue
                
                keywords = []
                if 'tags' in entry: keywords = [t.term for t in entry.tags if t.term]
                elif 'category' in entry: keywords = [entry.category]
                
                all_articles.append({
                    'raw_title': title, 'link': entry.link, 'source': s_name, 
                    'time': p_date, 'tag_html': tag, 'item_tags': " / ".join(keywords[:2])
                })
                FINAL_STATS[s_name] += 1
        except: continue
    return all_articles

def get_pure_title(title):
    temp = title
    for noise in NOISE_WORDS:
        temp = temp.replace(f"【{noise}】", "").replace(f"[{noise}]", "").replace(noise, "")
    return temp.strip()

def cluster_articles(articles):
    clusters = []
    for art in sorted(articles, key=lambda x: x['time'], reverse=True):
        found = False
        pure_art_title = get_pure_title(art['raw_title'])
        for cluster in clusters:
            is_match = any(difflib.SequenceMatcher(None, get_pure_title(item['raw_title']), pure_art_title).ratio() > 0.33 for item in cluster)
            if is_match:
                cluster.append(art)
                found = True
                break
        if not found:
            clusters.append([art])
    return clusters

def render_clustered_html(clusters, need_trans=False):
    html = ""
    for group in clusters:
        main = group[0]
        display_title = highlight_keywords(translate_text(main['raw_title']) if need_trans else main['raw_title'])
        display_tags = translate_text(main['item_tags']) if (need_trans and main['item_tags']) else main['item_tags']
        badges = badge_styler(main['tag_html'])
        link_hash = str(abs(hash(main['link'])))[:10]
        tags_part = f"<span class='story-tags'>{display_tags}</span> · " if display_tags else ""
        time_str = main['time'].strftime('%m/%d %H:%M')
        
        html += f"""
        <div class='story-block' id='sb-{link_hash}' data-link='{main['link']}'>
            <div class='headline-wrapper'>
                <span class='star-btn' onclick='toggleStar("{link_hash}")'>★</span>
                <div style='display: flex; align-items: flex-start;'>
                    {badges}<a class='headline main-head' href='{main['link']}' target='_blank'>{display_title}</a>
                </div>
            </div>
            <div class='meta-line'>{tags_part}{main['source']} | {time_str}</div>
        """
        if len(group) > 1:
            html += "<div class='sub-news-list'>"
            seen_links = {main['link']}
            for sub in group[1:]:
                if sub['link'] in seen_links: continue
                sub_title = translate_text(sub['raw_title']) if need_trans else sub['raw_title']
                sub_time = sub['time'].strftime('%H:%M')
                html += f"<div class='sub-item'>• <a href='{sub['link']}' target='_blank'>{sub_title}</a> <span class='sub-meta'>({sub['source']} {sub_time})</span></div>"
                seen_links.add(sub['link'])
            html += "</div>"
        html += "</div>"
    return html

def main():
    now_tw_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    print(f">>> [v{VERSION}] 更新數位時代 X 來源並同步時區...")
    
    intl_list = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_list = fetch_data(CONFIG['FEEDS']['JK'])
    tw_list = fetch_data(CONFIG['FEEDS']['TW'])
    
    special_sites = [
        ("CIO Taiwan", "https://www.cio.com.tw/category/it-strategy/", ["h3 a", ".entry-title a"], "[分析]", ".category-label"),
        ("數位時代", "https://www.bnext.com.tw/articles", [".item_box", ".post_item"], "[數位]", ".item_tag")
    ]
    for name, url, sels, tag, tag_sel in special_sites:
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
            soup = BeautifulSoup(resp.text, 'html.parser')
            items = []
            for sel in sels:
                items = soup.select(sel)
                if items: break
            for item in items[:10]:
                title_tag = item.select_one('.item_title, h3, a') if name == "數位時代" else item
                link_tag = title_tag if title_tag and title_tag.name == 'a' else (title_tag.find('a') if title_tag else None)
                if not link_tag: continue
                title = link_tag.get_text().strip()
                if is_blacklisted(title): continue
                link = link_tag.get('href', '')
                if link.startswith('/'): link = "/".join(url.split('/')[:3]) + link
                tw_list.append({
                    'raw_title': title, 'link': link, 'source': name, 
                    'time': datetime.datetime.now(TW_TZ), 'tag_html': tag, 'item_tags': ""
                })
        except: pass

    intl_groups = cluster_articles(intl_list)
    jk_groups = cluster_articles(jk_list)
    tw_groups = cluster_articles(tw_list)

    stats_list = "".join([f"<li>{v} - {k}</li>" for k, v in sorted(FINAL_STATS.items(), key=lambda x: x[1], reverse=True)])
    
    full_html = f"""
    <html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{SITE_TITLE}</title>
    <style>
        :root {{ --bg: #fff; --text: #333; --border: #eee; --link: #1a0dab; --hi: #ff98001a; --kw: #e67e22; --tag: #888; }}
        @media (prefers-color-scheme: dark) {{ :root {{ --bg: #111; --text: #ddd; --border: #222; --link: #8ab4f8; --tag: #777; }} }}
        body {{ font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.4; padding-bottom: 50px; }}
        .header {{ padding: 12px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 1000; }}
        .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1px; background: var(--border); }}
        @media (max-width: 900px) {{ .wrapper {{ grid-template-columns: 1fr; }} }}
        .river {{ background: var(--bg); padding: 14px; }}
        .river-title {{ font-size: 18px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 15px; }}
        .story-block {{ padding: 15px 0; border-bottom: 1px solid var(--border); }}
        .main-head {{ font-size: 16px; font-weight: 800; text-decoration: none; color: var(--link); }}
        .meta-line {{ font-size: 11px; color: var(--tag); margin-top: 5px; margin-left: 28px; }}
        .sub-news-list {{ margin: 8px 0 0 45px; border-left: 2px solid var(--border); padding-left: 12px; }}
        .sub-item {{ font-size: 13px; margin-bottom: 4px; color: var(--text); }}
        .sub-item a {{ text-decoration: none; color: var(--text); }}
        .sub-meta {{ font-size: 10px; color: var(--tag); }}
        .badge {{ display: inline-block; padding: 1px 6px; font-size: 10px; border-radius: 4px; margin-right: 6px; font-weight: 800; white-space: nowrap; height: 18px; margin-top: 2px; }}
        .badge-x {{ background: #1da1f2 !important; color: #fff !important; }}
        .badge-jp {{ background: #ff5722 !important; color: #fff !important; }}
        .badge-kr {{ background: #303f9f !important; color: #fff !important; }}
        .badge-digital {{ background: #27ae60 !important; color: #fff !important; }}
        .star-btn {{ cursor: pointer; color: #ddd; font-size: 18px; margin-right: 10px; float: left; }}
        .star-btn.active {{ color: #f1c40f; }}
        .kw-highlight {{ color: var(--kw); font-weight: bold; background: #ff980015; }}
        .btn {{ cursor: pointer; padding: 5px 12px; border: 1px solid var(--text); font-size: 11px; border-radius: 6px; background: var(--bg); color: var(--text); font-weight: bold; }}
        .update-time {{ font-size: 10px; color: var(--tag); margin-left: 10px; }}
    </style></head><body>
        <div class='header'><h1 style='margin:0; font-size:20px;'>{SITE_TITLE}</h1>
        <div>
            <span class='update-time'>最後更新: {now_tw_str}</span>
            <span class='btn' onclick='toggleStats()'>📊 統計</span> 
            <span class='btn' onclick='document.body.classList.toggle("only-stars")'>★ 精選</span>
        </div></div>
        <div id='stats-panel' style='display:none; padding:15px; background:#8882; border-bottom:1px solid var(--border);'><ul style='column-count:3; list-style:none; padding:0; margin:0; font-size:11px;'>{stats_list}</ul></div>
        <div class='wrapper'>
            <div class='river'><div class='river-title'>Global Strategy</div>{render_clustered_html(intl_groups, True)}</div>
            <div class='river'><div class='river-title'>Japan/Korea</div>{render_clustered_html(jk_groups, True)}</div>
            <div class='river'><div class='river-title'>Taiwan Tech</div>{render_clustered_html(tw_groups, False)}</div>
        </div>
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
