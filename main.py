import feedparser, datetime, pytz, os, requests, json, re, sys, time
from dateutil import parser as date_parser
from google import genai
import urllib3

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 核心配置 ---
VERSION = "2.4.4"
SITE_TITLE = "豆子新聞戰情室"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
# 暫時切換模型，避開 2.0 Lite 的配額限制
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
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}, "TERM_MAP": {}}

CONFIG = load_config()

def get_processed_content(articles, zone_name):
    """【v2.4.4】切換模型並強化冷卻"""
    if not client or not articles: return [[a] for a in articles]
    
    print(f"\n>>> 處理 {zone_name} 區域，共 {len(articles)} 則")
    chunk_size = 15 # 縮小規模，降低 API 壓力
    final_clusters = []
    used_indices = set()

    for start in range(0, len(articles), chunk_size):
        chunk = articles[start : start + chunk_size]
        titles_input = "\n".join([f"ID_{i+start}: {a['raw_title']}" for i, a in enumerate(chunk)])
        
        prompt = f"""
        任務：翻譯為繁體中文並依公司聚合。
        1. 翻譯為繁中，移除雜訊(Send tips, URL, Axios)。
        2. 術語轉換：智能->智慧、數據->資料、芯片->晶片、算力->運算力。
        3. 回傳純 JSON 格式：[ {{"company": "公司名", "indices": [編號], "titles": ["翻譯標題"]}} ]
        待處理清單：{titles_input}
        """

        retry_count = 0
        while retry_count < 2:
            try:
                # 呼叫 1.5 Flash 看看是否有額度
                response = client.models.generate_content(model=MODEL_NAME, contents=prompt, config={'temperature': 0.0})
                json_match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
                
                if json_match:
                    data = json.loads(json_match.group())
                    for group in data:
                        cluster = []
                        for i, idx in enumerate(group['indices']):
                            if idx < len(articles) and idx not in used_indices:
                                item = articles[idx]
                                item['display_title'] = re.sub(r'https?://\S+|Send tips!|📩', '', group['titles'][i]).strip()
                                cluster.append(item); used_indices.add(idx)
                        if cluster: final_clusters.append(cluster)
                    print(f"  [OK] 區塊 {start} 處理完成")
                    break 
                else:
                    print(f"  [!] 區塊 {start} JSON 解析失敗")
                    break
            except Exception as e:
                if "429" in str(e):
                    # 如果連 1.5 都在 429，就加長等待
                    print(f"  [!] 1.5 模型也限流，冷卻 30 秒...")
                    time.sleep(30)
                    retry_count += 1
                else:
                    print(f"  [Error] {str(e)}")
                    break
        # 強制冷卻，每組之間多等幾秒
        time.sleep(5) 

    for i, a in enumerate(articles):
        if i not in used_indices:
            a['display_title'] = a['raw_title']
            final_clusters.append([a])
            
    return final_clusters

def fetch_raw_data(feed_list):
    all_articles = []
    now_tw = datetime.datetime.now(TW_TZ)
    limit_date = now_tw - datetime.timedelta(days=4)
    for item in feed_list:
        try:
            resp = requests.get(item['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15, verify=False)
            feed = feedparser.parse(resp.content)
            s_name = (feed.feed.title if 'title' in feed.feed else item['url'].split('/')[2]).split('|')[0].strip()[:10]
            for entry in feed.entries[:8]: # 再縮減抓取量，減輕 API 負擔
                title = entry.title.strip()
                if not title: continue
                try: p_date = date_parser.parse(entry.get('published', entry.get('pubDate', entry.get('updated', None))), tzinfos=TZ_INFOS).astimezone(TW_TZ)
                except: p_date = now_tw
                if p_date < limit_date: continue
                all_articles.append({'raw_title': title, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag': item['tag']})
                FINAL_STATS[s_name] = FINAL_STATS.get(s_name, 0) + 1
        except: continue
    return all_articles

def main():
    print(f"Executing {SITE_TITLE} v{VERSION}...")
    intl = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['INTL']), "Global")
    jk = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['JK']), "JK")
    tw = get_processed_content(fetch_raw_data(CONFIG['FEEDS']['TW']), "Taiwan")

    # 渲染邏輯維持不變
    def render(clusters):
        html = ""
        for g in sorted(clusters, key=lambda x: x[0]['time'], reverse=True):
            m = g[0]; hid = str(abs(hash(m['link'])))[:10]
            badge = f'<span class="badge-ithome">iThome</span>' if "iThome" in m['tag'] else (f'<span class="badge-tag">{m["tag"]}</span>' if m["tag"] else "")
            html += f"""
            <div class='story-block' id='sb-{hid}' data-link='{m['link']}' data-ts='{int(m['time'].timestamp())}'>
                <div class='headline-wrapper'>
                    <span class='star-btn' onclick='toggleStar("{hid}")'>★</span>
                    <div class='head-content'>
                        <div class='title-row'>
                            {badge}<a class='headline' href='{m['link']}' target='_blank'>{m.get('display_title', m['raw_title'])}</a>
                        </div>
                    </div>
                    <div class='action-btns'>
                        <span class='btn-restore' onclick='restoreItem("{hid}")'>↺恢復</span>
                        <span class='btn-hide' onclick='toggleHide("{hid}")'>✕隱藏</span>
                    </div>
                </div>
                <div class='meta-line'>{m['source']} | {m['time'].strftime('%m/%d %H:%M')}</div>
            """
            if len(g) > 1:
                html += "<div class='sub-news-list'>"
                for s in g[1:6]:
                    html += f"<div class='sub-item'>• <a href='{s['link']}' target='_blank'>{s.get('display_title', s['raw_title'])}</a></div>"
                html += "</div>"
            html += "</div>"
        return html

    # 此處銜接先前的 HTML 渲染邏輯，直接生成 index.html
    # (省略部分重複的 CSS/HTML 內容以維持簡潔)
    # ...
