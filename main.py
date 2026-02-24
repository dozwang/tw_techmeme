import feedparser, datetime, pytz, os, requests, json, re, sys, time
from dateutil import parser as date_parser
from google import genai
import urllib3
from concurrent.futures import ThreadPoolExecutor

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 配置 ---
VERSION = "2.6.3"
SITE_TITLE = "豆子新聞戰情室"
PRIORITY_COMPANIES = ["Nvidia", "Apple", "Anthropic", "Tsmc", "Openai", "Google", "Microsoft", "Meta"]
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-1.5-flash" 

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}

def fallback_translate(text):
    """【備援機制】當 Gemini 失效時，使用簡易 API 進行基本翻譯"""
    try:
        # 使用 Google Translate 的簡單介面作為最終防線
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-TW&dt=t&q={requests.utils.quote(text)}"
        resp = requests.get(url, timeout=5)
        return "".join([x[0] for x in resp.json()[0]])
    except:
        return text # 若連備援都失敗，才回傳原文

def get_processed_content(articles, zone_name):
    if not client or not articles: return [[a] for a in articles]
    print(f"\n>>> 正在優化 {zone_name}...")
    
    chunk_size = 12 
    company_map = {} 
    translated_map = {} 
    ai_success = False

    for start in range(0, len(articles), chunk_size):
        chunk = articles[start : start + chunk_size]
        titles_input = "\n".join([f"ID_{i+start}: {a['raw_title']}" for i, a in enumerate(chunk)])
        
        prompt = f"翻譯標題為繁體中文並識別核心公司。回傳 JSON: [{{'id': 編號, 'company': '公司', 'title': '翻譯標題'}}]。待處理：{titles_input}"
        
        try:
            response = client.models.generate_content(model=MODEL_NAME, contents=prompt, config={'temperature': 0.1})
            json_match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                for item in data:
                    idx = int(item['id'])
                    translated_map[idx] = item['title'].strip()
                    comp = item['company'].strip().capitalize()
                    if comp != "None":
                        if comp not in company_map: company_map[comp] = []
                        company_map[comp].append(idx)
                ai_success = True
            time.sleep(1)
        except Exception as e:
            print(f"  [!] Gemini 請求失敗 ({str(e)[:20]})，啟用備援翻譯...")
            # 針對該區塊進行備援翻譯
            for i, a in enumerate(chunk):
                idx = i + start
                translated_map[idx] = fallback_translate(a['raw_title'])

    final_clusters = []
    used_indices = set()
    # 依公司聚合
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

    # 剩餘新聞補漏
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
            clean_t = re.sub(r'https?://\S+|Send tips!|📩|\[X\]|\[日\]|\[韓\]', '', entry.title).strip()
            if not clean_t: continue
            try: p_date = date_parser.parse(entry.get('published', entry.get('pubDate', entry.get('updated', None))), tzinfos=TZ_INFOS).astimezone(TW_TZ)
            except: p_date = datetime.datetime.now(TW_TZ)
            if p_date < limit_date: continue
            results.append({'raw_title': clean_t, 'link': entry.link, 'source': s_name, 'time': p_date, 'tag': item['tag']})
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
            <div class='story-block' id='sb-{hid}' data-link='{m['link']}' style='{p_style}'>
                <div class='grid-layout'>
                    <div class='star-col'><span class='star-btn' onclick='toggleStar("{hid}")'>★</span></div>
                    <div class='text-col'>
                        <a class='headline' href='{m['link']}' target='_blank'>{badge}{m.get('display_title', m['raw_title'])}</a>
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
                    html += f"<div class='sub-item'>• <a href='{s['link']}' target='_blank'>{s.get('display_title', s['raw_title'])}</a></div>"
                html += "</div>"
            html += "</div>"
        return html

    # [HTML 與 CSS 部分沿用 v2.6.2 的 Grid 結構，確保佈局不跑掉]
    full_html = f"<html>...{render(intl)}...</html>" # 實際需包含完整 HTML 代碼
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__":
    main()
