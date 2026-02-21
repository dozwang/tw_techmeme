import feedparser
import datetime
import pytz
import os
from dateutil import parser as date_parser
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from googletrans import Translator

# --- 設定與清單 ---
TW_TZ = pytz.timezone('Asia/Taipei')
translator = Translator()

FEEDS_TW = [
    "https://www.digitimes.com.tw/rss/news.xml", "https://technews.tw/feed/",
    "https://www.ithome.com.tw/rss", "https://www.bnext.com.tw/rss",
    "https://www.ctee.com.tw/rss/tech", "https://money.udn.com/rssfeed/news/1001/5591/1059?ch=money",
    "https://futurecity.cw.com.tw/rss", "https://www.managertoday.com.tw/rss",
    "https://www.cna.com.tw/cna2018/api/jsnews.aspx?type=ait", "https://www.cio.com.tw/feed/"
]

FEEDS_INTL = [
    "https://feeds.bloomberg.com/technology/news.rss", "https://www.ft.com/technology?format=rss",
    "https://www.wired.com/feed/rss", "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/partner/techmeme-full-article/rss.xml",
    "https://www.cnbc.com/id/19854910/device/rss/rss.html", "https://www.theinformation.com/feed",
    "https://feeds.arstechnica.com/arstechnica/index/", "https://www.bleepingcomputer.com/feed/"
]

def fetch_data(urls):
    data_by_date = {}
    now_utc = datetime.datetime.now(pytz.utc)
    limit_48h = now_utc - datetime.timedelta(hours=48)
    
    for url in urls:
        feed = feedparser.parse(url)
        s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
        for entry in feed.entries[:10]:
            try:
                p_date = date_parser.parse(entry.published)
                if p_date.tzinfo is None: p_date = pytz.utc.localize(p_date)
                if p_date < limit_48h: continue
                
                p_date_tw = p_date.astimezone(TW_TZ)
                date_str = p_date_tw.strftime('%Y-%m-%d')
                
                data_by_date.setdefault(date_str, []).append({
                    'title': entry.title, 'link': entry.link, 'source': s_name,
                    'time': p_date_tw, 'fresh': (now_utc - p_date).total_seconds() < 3600
                })
            except: continue
    return data_by_date

def cluster_and_translate(daily_data, is_intl=False):
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    results = {}
    for d_str, news_list in daily_data.items():
        if not news_list: continue
        titles = [n['title'] for n in news_list]
        embeddings = model.encode(titles)
        clusters = DBSCAN(eps=0.45, min_samples=1, metric="cosine").fit_predict(embeddings)
        
        groups = {}
        for i, cid in enumerate(clusters):
            groups.setdefault(cid, []).append(news_list[i])
        
        # 執行 1+5 策略與翻譯
        for cid, articles in groups.items():
            articles.sort(key=lambda x: x['time']) # 第一則為最早
            if is_intl:
                try:
                    articles[0]['trans_title'] = translator.translate(articles[0]['title'], dest='zh-tw').text
                except: articles[0]['trans_title'] = articles[0]['title']
            
            # 找出最新的 5 則報導 (排除第一則)
            articles.sort(key=lambda x: x['time'], reverse=True)
        results[d_str] = groups
    return results

def render_column(daily_clusters, title_prefix):
    html = f"<div class='river'><div class='river-title'>{title_prefix}</div>"
    sorted_dates = sorted(daily_clusters.keys(), reverse=True)
    for d_str in sorted_dates:
        html += f"<div class='date-header'>{d_str}</div>"
        for gid, articles in daily_clusters[d_str].items():
            # 1+5 邏輯應用
            articles.sort(key=lambda x: x['time'])
            first = articles[0]
            latest_updates = sorted([a for a in articles[1:]], key=lambda x: x['time'], reverse=True)[:5]
            others = [a for a in articles if a not in [first] + latest_updates]

            fresh_cls = "fresh" if first['fresh'] else ""
            display_title = first.get('trans_title', first['title'])
            
            html += f"<div class='story-block {fresh_cls}'>"
            html += f"<a class='headline' href='{first['link']}'>{display_title} <span class='source-tag'>[{first['source']}]</span></a>"
            if 'trans_title' in first:
                html += f"<div class='original-title'>{first['title']}</div>"
            
            for up in latest_updates:
                up_title = up.get('trans_title', up['title'])
                html += f"<a class='sub-link' href='{up['link']}'>↳ <span class='source-name'>{up['source']} ({up['time'].strftime('%H:%M')})</span>: {up_title}</a>"
            
            if others:
                other_str = ", ".join([f"{o['source']}" for o in others[:8]])
                html += f"<div class='other-mentions'>Also: {other_str}</div>"
            html += "</div>"
    html += "</div>"
    return html

def main():
    tw_raw = fetch_data(FEEDS_TW)
    intl_raw = fetch_data(FEEDS_INTL)
    
    tw_clusters = cluster_and_translate(tw_raw, is_intl=False)
    intl_clusters = cluster_and_translate(intl_raw, is_intl=True)
    
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    
    full_html = f"""
    <html><head><meta charset='UTF-8'><style>
        body {{ font-family: system-ui; background: #f4f4f4; margin: 0; }}
        .header {{ background: #fff; padding: 15px 40px; border-bottom: 2px solid #000; display: flex; justify-content: space-between; align-items: center; }}
        .wrapper {{ display: flex; max-width: 1400px; margin: 0 auto; gap: 1px; background: #ccc; }}
        .river {{ flex: 1; background: #f8f9fa; padding: 20px; }}
        .river-title {{ font-size: 24px; font-weight: 900; border-bottom: 2px solid #000; margin-bottom: 15px; padding-bottom: 5px; }}
        .date-header {{ background: #333; color: #fff; padding: 4px 12px; font-size: 13px; margin: 20px 0 10px; display: inline-block; }}
        .story-block {{ background: #fff; padding: 15px; margin-bottom: 12px; border: 1px solid #eee; }}
        .fresh {{ background: #ffffe0; border-left: 4px solid #ffd700; }}
        .headline {{ color: #0000ee; text-decoration: none; font-size: 17px; font-weight: bold; line-height: 1.3; }}
        .original-title {{ font-size: 11px; color: #999; margin: 2px 0 8px; }}
        .sub-link {{ display: block; font-size: 12px; color: #444; margin-top: 5px; text-decoration: none; padding-left: 10px; }}
        .source-tag {{ font-size: 11px; color: #666; font-weight: normal; }}
        .other-mentions {{ font-size: 11px; color: #888; margin-top: 8px; padding-left: 10px; font-style: italic; }}
    </style></head><body>
        <div class='header'><h1>Taiwan & Intl Techmeme</h1><div>更新時間: {now_str} (台北)</div></div>
        <div class='wrapper'>
            {render_column(intl_clusters, "Global Technology")}
            {render_column(tw_clusters, "Taiwan Tech & Biz")}
        </div>
    </body></html>
    """
    os.makedirs('output', exist_ok=True)
    with open('output/index.html', 'w', encoding='utf-8') as f: f.write(full_html)

if __name__ == "__main__":
    main()
