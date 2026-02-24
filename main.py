import feedparser, datetime, pytz, os, requests, json, re, sys, time
from dateutil import parser as date_parser
from google import genai
import urllib3

if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 核心自訂清單 ---
VERSION = "2.5.8"
SITE_TITLE = "豆子新聞戰情室"
# 優先公司清單：置頂且強化聚合
PRIORITY_COMPANIES = ["Nvidia", "Apple", "Anthropic", "Tsmc", "Openai", "Google", "Microsoft", "Meta"]

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemma-3-27b-it" 
client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

TW_TZ = pytz.timezone('Asia/Taipei')
TZ_INFOS = {"PST": pytz.timezone("US/Pacific"), "PDT": pytz.timezone("US/Pacific")}

def get_processed_content(articles, zone_name):
    """【v2.5.8】強化翻譯覆蓋率與優先公司置頂"""
    if not client or not articles: return [[a] for a in articles]
    print(f"\n>>> 處理 {zone_name}，共 {len(articles)} 則")
    
    chunk_size = 12 
    company_map = {} 
    translated_map = {} # 儲存所有翻譯結果
    
    for start in range(0, len(articles), chunk_size):
        chunk = articles[start : start + chunk_size]
        titles_input = "\n".join([f"ID_{i+start}: {a['raw_title']}" for i, a in enumerate(chunk)])
        
        prompt = f"""
        任務：精確翻譯標題為繁體中文並識別核心公司。
        1. 翻譯：翻譯為繁中，徹底移除雜訊(Send tips, URL, Axios, 📩)。
        2. 術語：智能->智慧、數據->資料、芯片->晶片、算力->運算力。
        3. Entity：識別核心公司(如 Apple, Nvidia)。若無則標為 "None"。
        4. 必須回傳純 JSON 陣列，確保每個 ID 都有對應翻譯。
        [ {{"id": 編號, "company": "公司", "title": "翻譯標題"}} ]
        清單：{titles_input}
        """
        
        try:
            response = client.models.generate_content(model=MODEL_NAME, contents=prompt, config={'temperature': 0.1})
            json_match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                for item in data:
                    idx = item['id']
                    comp = item['company'].strip().capitalize()
                    translated_map[idx] = item['title'].strip()
                    if comp != "None":
                        if comp not in company_map: company_map[comp] = []
                        company_map[comp].append(idx)
            time.sleep(2)
        except: continue

    final_clusters = []
    used_indices = set()

    # 1. 優先處理有公司的群組 (包含優先清單判斷)
    for comp, indices in company_map.items():
        cluster = []
        is_priority = any(p.capitalize() in comp for p in PRIORITY_COMPANIES)
        for idx in indices:
            if idx < len(articles) and idx not in used_indices:
                a = articles[idx]
                a['display_title'] = translated_map.get(idx, a['raw_title'])
                a['is_priority'] = is_priority
                cluster.append(a); used_indices.add(idx)
        if cluster: final_clusters.append(cluster)

    # 2. 補漏剩餘新聞
    for i, a in enumerate(articles):
        if i not in used_indices:
            a['display_title'] = translated_map.get(i, a['raw_title'])
            a['is_priority'] = False
            final_clusters.append([a])
    
    # 3. 排序：優先公司在前
    final_clusters.sort(key=lambda x: (x[0].get('is_priority', False), x[0]['time']), reverse=True)
    return final_clusters

# [render 函式補強 CSS 以防止截圖中的按鈕重疊問題]
def render(clusters):
    html = ""
    for g in clusters:
        m = g[0]; hid = str(abs(hash(m['link'])))[:10]
        # 優先公司加上明顯邊框
        p_style = "border-left: 4px solid #f1c40f; background: rgba(241,196,15,0.05);" if m.get('is_priority') else ""
        badge = f'<span class="badge-ithome">iThome</span>' if "iThome" in m['tag'] else ""
        
        html += f"""
        <div class='story-block' id='sb-{hid}' data-link='{m['link']}' style='{p_style}'>
            <div class='headline-wrapper'>
                <div class='star-cell'><span class='star-btn' onclick='toggleStar("{hid}")'>★</span></div>
                <div class='head-content'>
                    <a class='headline' href='{m['link']}' target='_blank'>{badge}{m.get('display_title', m['raw_title'])}</a>
                </div>
                <div class='action-btns'>
                    <span class='btn-restore' onclick='restoreItem("{hid}")'>恢復</span>
                    <span class='btn-hide' onclick='toggleHide("{hid}")'>隱藏</span>
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

# [其餘 HTML 結構中，CSS 應包含下列修正以解決重疊]
# .action-btns { flex-shrink: 0; min-width: 80px; text-align: right; }
# .headline { word-break: break-word; flex: 1; }
