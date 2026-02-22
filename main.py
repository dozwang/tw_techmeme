import feedparser, datetime, pytz, os, difflib, requests, json, re, time, random
from dateutil import parser as date_parser
from googletrans import Translator
from bs4 import BeautifulSoup
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
    return {"FEEDS": {"INTL": [], "JK": [], "TW": []}, "WHITELIST": []}

CONFIG = load_config()

def translate_text(text):
    if not text: return ""
    try:
        res = translator.translate(text, dest='zh-tw').text
        it_fixes = {"副駕駛": "Copilot", "智能": "智慧", "數據": "資料", "服務器": "伺服器", "軟件": "軟體", "網絡": "網路", "信息": "資訊"}
        for w, r in it_fixes.items(): res = res.replace(w, r)
        return res
    except: return text

def is_similar(a, b): return difflib.SequenceMatcher(None, a, b).ratio() > 0.3

def fetch_data(feed_list):
    data_by_date, stats, seen = {}, {}, []
    now_utc = datetime.datetime.now(pytz.utc)
    limit_time = now_utc - datetime.timedelta(hours=48)
    for item in feed_list:
        url, tag = item['url'], item['tag']
        try:
            print(f"  [RSS] 正在嘗試抓取: {url[:50]}...", flush=True)
            # 增加 Headers 讓 RSS 抓取更穩定
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
            feed = feedparser.parse(resp.content)
            s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            stats[s_name] = 0
            for entry in feed.entries[:20]:
                title = entry.title.strip()
                if any(is_similar(title, s) for s in seen): continue
                raw_date = entry.get('published', entry.get('pubDate', entry.get('updated', None)))
                try: p_date = date_parser.parse(raw_date, tzinfos=TZ_INFOS).astimezone(pytz.utc)
                except: p_date = now_utc
                if p_date < limit_time: continue
                p_date_tw = p_date.astimezone(TW_TZ)
                date_str = p_date_tw.strftime('%Y-%m-%d')
                data_by_date.setdefault(date_str, []).append({
                    'raw_title': title, 
                    'link': entry.link, 
                    'source': s_name, 
                    'time': p_date_tw, 
                    'tag_html': tag
                })
                seen.append(title); stats[s_name] += 1
        except Exception as e:
            print(f"  [跳過] {url[:30]} 抓取失敗: {e}")
            continue
    return data_by_date, stats, seen

def main():
    print(">>> [1/2] 開始 RSS 全面抓取...", flush=True)
    # 將所有來源合併抓取，確保不漏掉任何一個
    intl_raw, intl_st, s1 = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_raw, jk_st, s2 = fetch_data(CONFIG['FEEDS']['JK'])
    tw_raw, tw_st, s3 = fetch_data(CONFIG['FEEDS']['TW'])
    
    print(">>> [2/2] 正在產出網頁並進行翻譯...", flush=True)
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    
    # 建立統計文字
    all_stats = {**intl_st, **jk_st, **tw_st}
    stats_html = " | ".join([f"<span>{k}: {v}</span>" for k, v in sorted(all_stats.items(), key=lambda x: x[1], reverse=True)])

    # 簡單的渲染逻辑
    def simple_render(data):
        res = ""
        for d_str in sorted(data.keys(), reverse=True):
            res += f"<div style='background:#444; color:#fff; padding:2px 10px; font-size:12px;'>{d_str}</div>"
            for art in data[d_str]:
                # 這裡加入翻譯
                trans_title = translate_text(art['raw_title'])
                res += f"<div style='margin:10px 0; border-bottom:1px solid #eee; padding-bottom:5px;'>"
                res += f"<a href='{art['link']}' target='_blank' style='text-decoration:none; color:#1a0dab; font-weight:bold;'>{art['tag_html']} {trans_title}</a>"
                res += f"<div style='font-size:11px; color:#666;'>{art['source']} | {art['time'].strftime('%H:%M')}</div>"
                res += "</div>"
        return res

    full_html = f"""
    <html><head><meta charset='UTF-8'><title>{SITE_TITLE}</title>
    <style>body{{font-family:sans-serif; max-width:1200px; margin:0 auto; padding:20px; line-height:1.5;}}
    .grid{{display:grid; grid-template-columns: 1fr 1fr 1fr; gap:20px;}}
    .stats{{font-size:11px; color:#777; margin-bottom:20px; border-bottom:1px solid #ddd; padding-bottom:10px;}}
    </style></head><body>
    <h1>{SITE_TITLE}</h1>
    <div class='stats'>最後更新: {now_str} <br> {stats_html}</div>
    <div class='grid'>
        <div><h2>Global</h2>{simple_render(intl_raw)}</div>
        <div><h2>Japan/Korea</h2>{simple_render(jk_raw)}</div>
        <div><h2>Taiwan</h2>{simple_render(tw_raw)}</div>
    </div>
    </body></html>
    """
    
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)
    print(">>> [成功] 戰情室網頁產出完畢！", flush=True)

if __name__ == "__main__":
    main()
