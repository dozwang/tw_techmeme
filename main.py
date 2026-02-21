import feedparser, datetime, pytz, os, difflib, requests, json, re
from dateutil import parser as date_parser
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from googletrans import Translator

# --- 基礎設定 ---
TW_TZ = pytz.timezone('Asia/Taipei')
translator = Translator()

def load_config():
    with open('feeds.json', 'r', encoding='utf-8') as f:
        return json.load(f)

CONFIG = load_config()

def highlight_keywords(text):
    """ 為白名單關鍵字加上高亮標籤 """
    for kw in CONFIG['WHITELIST']:
        # 使用正則表達式進行不分大小寫的替換，保留原始大小寫
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(f'<span class="kw-highlight">\\g<0></span>', text)
    return text

def is_similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio() > 0.85

def fetch_data(feed_list):
    data_by_date, stats = {}, {}
    now_utc = datetime.datetime.now(pytz.utc)
    limit_48h = now_utc - datetime.timedelta(hours=48)
    seen_titles = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...'}
    
    for item in feed_list:
        url, tag = item['url'], item['tag']
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding
            feed = feedparser.parse(resp.content)
            s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            stats[s_name] = 0
            for entry in feed.entries[:15]:
                title = entry.title.strip()
                if any(kw in title.lower() for kw in CONFIG['BLACKLIST']): continue
                if any(is_similar(title, seen) for seen in seen_titles): continue
                
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                if not raw_date: continue
                try:
                    p_date = date_parser.parse(raw_date)
                    if p_date.tzinfo is None: p_date = pytz.utc.localize(p_date)
                except: continue
                if p_date < limit_48h: continue
                
                p_date_tw = p_date.astimezone(TW_TZ)
                date_str = p_date_tw.strftime('%Y-%m-%d')
                
                # 組合標題與標籤
                display_tag = f'<span class="badge badge-{tag[1:-1]}">{tag}</span> ' if tag else ""
                data_by_date.setdefault(date_str, []).append({
                    'raw_title': title, 'link': entry.link, 'source': s_name, 
                    'time': p_date_tw, 'tag_html': display_tag,
                    'is_analysis': "[分析]" in tag
                })
                seen_titles.append(title)
                stats[s_name] += 1
        except: continue
    return data_by_date, stats

def cluster_and_translate(daily_data, need_trans=False):
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    results = {}
    for d_str, news_list in daily_data.items():
        if not news_list: continue
        titles = [n['raw_title'] for n in news_list]
        embeddings = model.encode(titles)
        clusters = DBSCAN(eps=0.42, min_samples=1, metric="cosine").fit_predict(embeddings)
        groups = {}
        for i, cid in enumerate(clusters): groups.setdefault(cid, []).append(news_list[i])
        
        final_groups = []
        for articles in groups.values():
            articles.sort(key=lambda x: x['time'])
            first = articles[0]
            if need_trans:
                try: 
                    translated = translator.translate(first['raw_title'], dest='zh-tw').text
                    first['display_title'] = first['tag_html'] + highlight_keywords(translated)
                except: first['display_title'] = first['tag_html'] + highlight_keywords(first['raw_title'])
            else:
                first['display_title'] = first['tag_html'] + highlight_keywords(first['raw_title'])
            
            is_priority = any(kw.lower() in first['raw_title'].lower() for kw in CONFIG['WHITELIST']) or first['is_analysis']
            final_groups.append({'articles': articles, 'priority': is_priority})
            
        final_groups.sort(key=lambda x: (x['priority'], x['articles'][0]['time']), reverse=True)
        results[d_str] = final_groups
    return results

def render_column(daily_clusters, title_prefix):
    html = f"<div class='river'><div class='river-title'>{title_prefix}</div>"
    for d_str in sorted(daily_clusters.keys(), reverse=True):
        html += f"<div class='date-header'>{d_str}</div>"
        for group in daily_clusters[d_str]:
            first = group['articles'][0]
            safe_id = first['link'].replace('"', '&quot;')
            meta = f" — {first['source']} {first['time'].strftime('%H:%M')}"
            
            pri_class = "priority" if group['priority'] else ""
            analysis_class = "analysis-text" if first['is_analysis'] else ""
            
            html += f"<div class='story-block {pri_class}' data-id=\"{safe_id}\">"
            html += f"<div class='headline-wrapper'><span class='star-btn' onclick='toggleStar(\"{safe_id}\")'>★</span>"
            html += f"<a class='headline {analysis_class}' href='{first['link']}'>{first['display_title']} <span class='source-tag'>{meta}</span></a></div>"
            
            # 副連結處理
            for up in sorted(group['articles'][1:], key=lambda x: x['time'], reverse=True)[:5]:
                html += f"<a class='sub-link' href='{up['link']}'>↳ {up['source']}: {up['raw_title']}</a>"
            html += "</div>"
    return html + "</div>"

def main():
    intl_raw, intl_st = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_raw, jk_st = fetch_data(CONFIG['FEEDS']['JK'])
    tw_raw, tw_st = fetch_data(CONFIG['FEEDS']['TW'])
    
    intl_cls = cluster_and_translate(intl_raw, need_trans=True)
    jk_cls = cluster_and_translate(jk_raw, need_trans=True)
    tw_cls = cluster_and_translate(tw_raw, need_trans=False)
    
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    all_st = {**intl_st, **jk_st, **tw_st}
    stats_html = "".join([f"<div class='stat-item'>{k}: <span>{v}</span></div>" for k, v in sorted(all_st.items())])
    
    full_html = f"""
    <html><head><meta charset='UTF-8'><title>台版 Techmeme 戰情室</title><style>
        :root {{ --bg: #fff; --text: #000; --link: #0000ee; --meta: #777; --border: #ddd; --hi: #ffff0033; }}
        @media (prefers-color-scheme: dark) {{
            :root {{ --bg: #1a1a1a; --text: #e0e0e0; --link: #8ab4f8; --meta: #999; --border: #333; --hi: #ffd70033; }}
        }}
        body {{ font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.2; }}
        .header {{ padding: 10px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; }}
        .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; width: 100%; max-width: 1900px; margin: 0 auto; gap: 1px; background: var(--border); }}
        .river {{ background: var(--bg); padding: 10px 15px; }}
        .river-title {{ font-size: 18px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 10px; }}
        .date-header {{ background: #444; color: #fff; padding: 2px 8px; font-size: 11px; margin: 15px 0 5px; display: inline-block; font-weight: bold; }}
        .story-block {{ padding: 8px 0; border-bottom: 1px solid var(--border); }}
        .story-block.priority {{ border-left: 3px solid #0000ee44; padding-left: 8px; }}
        
        /* 標籤配色 */
        .badge {{ font-size: 10px; padding: 1px 4px; border-radius: 3px; font-weight: bold; }}
        .badge-分析 {{ background: #8e44ad; color: #fff; }}
        .badge-日 {{ background: #c0392b; color: #fff; }}
        .badge-韓 {{ background: #2980b9; color: #fff; }}
        
        /* 高亮與分析樣式 */
        .kw-highlight {{ background-color: var(--hi); border-radius: 2px; padding: 0 2px; font-weight: 600; }}
        .analysis-text {{ color: #8e44ad !important; }}
        
        .headline {{ color: var(--link); text-decoration: none; font-size: 15px; font-weight: bold; }}
        .source-tag {{ font-size: 11px; color: var(--meta); font-weight: normal; }}
        .sub-link {{ display: block; font-size: 11px; color: var(--text); opacity: 0.7; margin: 3px 0 0 20px; text-decoration: none; }}
        .star-btn {{ cursor: pointer; color: #ccc; margin-right: 6px; }}
        .star-btn.active {{ color: #f1c40f; }}
    </style></head><body>
        <div class='header'><h1>Techmeme 戰情室</h1><div>{now_str}</div></div>
        <div class="wrapper">{render_column(intl_cls, "Global & Strategy")}{render_column(jk_cls, "Japan/Korea Tech")}{render_column(tw_cls, "Taiwan IT & Biz")}</div>
        <script>
            function toggleStar(link) {{
                let b = JSON.parse(localStorage.getItem('tech_bookmarks') || '[]');
                b.includes(link) ? b = b.filter(i => i !== link) : b.push(link);
                localStorage.setItem('tech_bookmarks', JSON.stringify(b));
                location.reload();
            }}
            document.addEventListener('DOMContentLoaded', () => {{
                JSON.parse(localStorage.getItem('tech_bookmarks') || '[]').forEach(link => {{
                    const el = document.querySelector(`[data-id="${{link}}"]`);
                    if (el) el.querySelector('.star-btn').classList.add('active');
                }});
            }});
        </script>
    </body></html>
    """
    os.makedirs('output', exist_ok=True)
    with open('output/index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__": main()
