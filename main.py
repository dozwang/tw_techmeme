import feedparser, datetime, pytz, os, requests, json, re, sys, time
from dateutil import parser as date_parser
from google import genai
import urllib3
from concurrent.futures import ThreadPoolExecutor

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 配置 ---
VERSION = "2.6.6"
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

def get_processed_content(articles, zone_name):
    """【v2.6.6】加入摘要生成邏輯"""
    if not articles: return []
    if not client: return [[a] for a in articles]
    
    print(f"\n>>> 正在生成 {zone_name} 摘要與聚合...")
    chunk_size = 10 # 縮小分塊以換取更長的輸出空間
    company_map, translated_map, summary_map = {}, {}, {}

    for start in range(0, len(articles), chunk_size):
        chunk = articles[start : start + chunk_size]
        titles_input = "\n".join([f"ID_{i+start}: {a['raw_title']}" for i, a in enumerate(chunk)])
        
        # 要求 AI 額外產出 summary 欄位
        prompt = f"""
        任務：翻譯標題並提供 20 字內繁中簡要摘要。
        1. 標題翻譯：移除雜訊，統一術語。
        2. 摘要：總結核心重點。
        3. 回傳 JSON: [{{'id': 編號, 'company': '公司', 'title': '翻譯標題', 'summary': '摘要'}}]
        待處理：{titles_input}
        """
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
        except: pass

    final_clusters, used_indices = [], set()
    for comp, indices in company_map.items():
        cluster = []
        is_p = any(p.capitalize() in comp for p in PRIORITY_COMPANIES)
        for idx in indices:
            if idx < len(articles) and idx not in used_indices:
                a = articles[idx]
                a['display_title'] = translated_map.get(idx, a['raw_title'])
                a['ai_summary'] = summary_map.get(idx, "")
                a['is_priority'] = is_p
                cluster.append(a); used_indices.add(idx)
        if cluster: final_clusters.append(cluster)
    
    for i, a in enumerate(articles):
        if i not in used_indices:
            a['display_title'] = translated_map.get(i, a['raw_title'])
            a['ai_summary'] = summary_map.get(i, "")
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
            # 備援：如果 AI 摘要失敗，可以從這裡抓一段 description
            raw_summary = re.sub(r'<[^>]+>', '', entry.get('summary', entry.get('description', '')))[:50].strip()
            if not clean_t: continue
            try: p_date = date_parser.parse(entry.get('published', entry.get('pubDate', entry.get('updated', None))), tzinfos=TZ_INFOS).astimezone(TW_TZ)
            except: p_date = datetime.datetime.now(TW_TZ)
            if p_date < limit_date: continue
            results.append({'raw_title': clean_t, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag': item['tag'], 'raw_summary': raw_summary})
            FINAL_STATS[s_name] = FINAL_STATS.get(s_name, 0) + 1
    except: pass
    return results

# [fetch_raw_data 邏輯保持不變...]

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
            
            # 使用 ai_summary 或 raw_summary 作為副標
            summary_text = m.get('ai_summary') or m.get('raw_summary', '')
            
            html += f"""
            <div class='story-block' id='sb-{hid}' data-link='{m['link']}' data-ts='{int(m['time'].timestamp())}' style='{p_style}'>
                <div class='grid-layout'>
                    <div class='star-col'><span class='star-btn' onclick='toggleStar("{hid}")'>★</span></div>
                    <div class='text-col'>
                        <a class='headline' href='{m['link']}' target='_blank'>{badge}{m.get('display_title', m['raw_title'])}</a>
                        <div class='summary-line'>{summary_text}</div>
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
                    sub_sum = s.get('ai_summary') or s.get('raw_summary', '')
                    html += f"<div class='sub-item'>• <a href='{s['link']}' target='_blank'>{s.get('display_title', s['raw_title'])}</a> <span class='sub-sum'>- {sub_sum}</span></div>"
                html += "</div>"
            html += "</div>"
        return html

    # [CSS 更新摘要樣式]
    style_patch = """
        .summary-line { font-size: 12px; color: #666; margin-top: 4px; line-height: 1.4; }
        .sub-sum { font-size: 11px; color: #999; }
        @media (prefers-color-scheme: dark) { 
            .summary-line { color: #aaa; } 
            .sub-sum { color: #777; }
        }
    """
    
    # [接續先前的 HTML 生成邏輯，將 style_patch 注入 <style> 中]
    # ...
