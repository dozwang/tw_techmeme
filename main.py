import feedparser
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
import os

# 1. RSS 來源清單
RSS_FEEDS = [
    "https://technews.tw/feed/",
    "https://www.ithome.com.tw/rss",
    "https://www.inside.com.tw/feed"
]

def fetch_news():
    entries = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]: # 每個來源取前 10 則
            entries.append({'title': entry.title, 'link': entry.link, 'source': feed.feed.title})
    return entries

def cluster_news(news):
    titles = [n['title'] for n in news]
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    embeddings = model.encode(titles)
    
    # 聚類：eps 控制相似度，0.3~0.5 是不錯的範圍
    clusters = DBSCAN(eps=0.4, min_samples=1, metric="cosine").fit_predict(embeddings)
    
    organized = {}
    for i, cluster_id in enumerate(clusters):
        organized.setdefault(cluster_id, []).append(news[i])
    return organized

def generate_html(organized_news):
    os.makedirs('output', exist_ok=True)
    html_content = "<html><head><meta charset='UTF-8'><title>台版 Techmeme</title>"
    html_content += "<style>body{font-family:sans-serif; max-width:800px; margin:auto; padding:20px; background:#f4f4f4;}"
    html_content += ".cluster{background:white; padding:15px; margin-bottom:10px; border-radius:5px; border-left:5px solid #007bff;}"
    html_content += "a{text-decoration:none; color:#333;} .sub-link{display:block; font-size:0.9em; color:#666; margin-left:20px;}</style></head><body>"
    html_content += "<h1>台版 Techmeme 🇹🇼</h1>"
    
    for articles in organized_news.values():
        html_content += f"<div class='cluster'><a href='{articles[0]['link']}'><h3>{articles[0]['title']}</h3></a>"
        for sub in articles[1:]:
            html_content += f"<a class='sub-link' href='{sub['link']}'>↳ {sub['title']} ({sub['source']})</a>"
        html_content += "</div>"
    
    html_content += "</body></html>"
    with open('output/index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)

if __name__ == "__main__":
    news = fetch_news()
    organized = cluster_news(news)
    generate_html(organized)
