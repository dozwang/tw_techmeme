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
        return res
    except: return text

def is_similar(a, b): return difflib.SequenceMatcher(None, a, b).ratio() > 0.35

def fetch_via_proxy(name, url, selectors, tag_name):
    """【輕量穿牆】"""
    print(f"  [嘗試抓取] {name}...", flush=True)
    headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'}
    articles = []
    try:
        # 改用更穩定的代理方式或直接請求
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200: 
            print(f"  [失敗] {name} HTTP {resp.status_code}", flush=True)
            return []
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = []
        for sel in selectors:
            items = soup.select(sel)
            if items: break
            
        for item in items[:10]:
            title = item.get_text().strip()
            link = item.get('href', '')
            if not title or len(title) < 5: continue
            if link.startswith('/'): link = "/".join(url.split('/')[:3]) + link
            articles.append({'raw_title': title, 'link': link, 'source': name, 'time': datetime.datetime.now(TW_TZ), 'tag_html': tag_name})
        print(f"  [成功] {name} 抓到 {len(articles)} 則", flush=True)
    except Exception as e:
        print(f"  [異常] {name}: {e}", flush=True)
    return articles

def fetch_data(feed_list):
    data_by_date, stats, seen = {}, {}, []
    now_utc = datetime.datetime.now(pytz.utc)
    limit_time = now_utc - datetime.timedelta(hours=48)
    for item in feed_list:
        url, tag = item['url'], item['tag']
        try:
            print(f"  [RSS] 抓取 {url[:40]}...", flush=True)
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            feed = feedparser.parse(resp.content)
            s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
            stats[s_name] = 0
            for entry in feed.entries[:15]:
                title = entry.title.strip()
                if any(is_similar(title, s) for s in seen): continue
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

def simple_cluster(news_list):
    """輕量化聚合：不再依賴重型 AI 模型"""
    if not news_list: return []
    groups = []
    used = set()
    for i, a in enumerate(news_list):
        if i in used: continue
        current_group = [a]
        used.add(i)
        for j, b in enumerate(news_list):
            if j not in used and is_similar(a['raw_title'], b['raw_title']):
                current_group.append(b)
                used.add(j)
        groups.append({'articles': current_group, 'priority': False})
    return groups

def main():
    print(">>> [1/3] 開始 RSS 抓取...", flush=True)
    intl_raw, intl_st, s1 = fetch_data(CONFIG['FEEDS']['INTL'])
    jk_raw, jk_st, s2 = fetch_data(CONFIG['FEEDS']['JK'])
    tw_raw, tw_st, s3 = fetch_data(CONFIG['FEEDS']['TW'])
    all_seen = s1 + s2 + s3
    
    print(">>> [2/3] 開始 HTML 攻堅...", flush=True)
    today_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d')
    for name, url, sels, tag in [
        ('Nikkei Asia', 'https://asia.nikkei.com/Business', ['h3 a'], ''),
        ('CIO Taiwan', 'https://www.cio.com.tw/category/it-strategy/', ['h3.entry-title a'], '[分析]'),
        ('數位時代', 'https://www.bnext.com.tw/articles', ['a.item_title'], '[數位]')
    ]:
        web = fetch_via_proxy(name, url, sels, tag)
        if web:
            target = tw_raw if name in ['CIO Taiwan', '數位時代'] else intl_raw
            target.setdefault(today_str, []).extend(web)
            if name == '數位時代': tw_st[name] = len(web)
            elif name == 'Nikkei Asia': intl_st[name] = len(web)
            elif name == 'CIO Taiwan': tw_st[name] = len(web)

    print(">>> [3/3] 產出 HTML 網頁...", flush=True)
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    # 這裡省略部分複雜翻譯邏輯以加速執行
    
    final_stats = {**intl_st, **jk_st, **tw_st}
    stats_items = "".join([f"<div style='font-size:11px;'>{k}: {v}</div>" for k, v in final_stats.items()])

    full_html = f"<html><body><h1>{SITE_TITLE}</h1><p>更新時間: {now_str}</p><div>{stats_items}</div><hr><h3>抓取完成，請查看下方 Log。</h3></body></html>"
    
    with open('index.html', 'w', encoding='utf-8') as f: f.write(full_html)
    print(">>> [成功] 流程全部跑完！", flush=True)

if __name__ == "__main__":
    main()
