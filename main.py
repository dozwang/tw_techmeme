import feedparser
import datetime
import pytz
from dateutil import parser as date_parser
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from googletrans import Translator

# 設定時區
TW_TZ = pytz.timezone('Asia/Taipei')
translator = Translator()

def fetch_data(urls, is_intl=False):
    data_by_date = {}
    now = datetime.datetime.now(pytz.utc)
    limit_48h = now - datetime.timedelta(hours=48)
    
    for url in urls:
        feed = feedparser.parse(url)
        s_name = feed.feed.title if 'title' in feed.feed else url.split('/')[2]
        
        for entry in feed.entries:
            try:
                # 統一轉為 UTC 再轉為 台灣時間
                p_date = date_parser.parse(entry.published)
                if p_date.tzinfo is None: p_date = pytz.utc.localize(p_date)
                p_date_tw = p_date.astimezone(TW_TZ)
                
                if p_date < limit_48h: continue
                
                date_str = p_date_tw.strftime('%Y-%m-%d')
                data_by_date.setdefault(date_str, []).append({
                    'title': entry.title,
                    'link': entry.link,
                    'source': s_name,
                    'time': p_date_tw,
                    'fresh': (now - p_date).total_seconds() < 3600
                })
            except: continue
    return data_by_date

def process_intl_news(daily_intl_news):
    """
    國外新聞處理邏輯：1.先聚合 2.翻譯聚合後的標題
    """
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    processed_daily = {}

    for d_str, news_list in daily_intl_news.items():
        if not news_list: continue
        # 叢集 (Clustering)
        titles = [n['title'] for n in news_list]
        embeddings = model.encode(titles)
        clusters = DBSCAN(eps=0.45, min_samples=1, metric="cosine").fit_predict(embeddings)
        
        day_groups = {}
        for i, cid in enumerate(clusters):
            day_groups.setdefault(cid, []).append(news_list[i])
        
        # 翻譯 (只翻譯每一組的頭條以節省資源並維持效率)
        for cid, articles in day_groups.items():
            try:
                # 翻譯標題
                translated = translator.translate(articles[0]['title'], dest='zh-tw').text
                articles[0]['trans_title'] = translated
            except:
                articles[0]['trans_title'] = articles[0]['title'] # 失敗則用原標
                
        processed_daily[d_str] = day_groups
    return processed_daily

# (此處省略 Render HTML 部分，邏輯與先前相同，但左側使用 trans_title)
