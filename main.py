def main():
    # ... (之前的 fetch_data 與 cluster 邏輯不變) ...
    
    now_str = datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    all_st = {**intl_st, **jk_st, **tw_st}
    
    # --- 整理統計清單 (按數量排序) ---
    stats_items = []
    sorted_stats = sorted(all_st.items(), key=lambda x: x[1], reverse=True)
    for k, v in sorted_stats:
        status_color = "var(--accent)" if v > 0 else "#e74c3c"
        bar_width = min(v * 4, 100)
        item_html = f"""
        <div class='stat-row'>
            <span class='stat-name'>{"● " if v > 0 else "○ "}{k}</span>
            <div class='stat-bar-container'>
                <div class='stat-bar-fill' style='width: {bar_width}%; background: {status_color}'></div>
            </div>
            <span class='stat-count' style='color: {status_color}'>{v}</span>
        </div>"""
        stats_items.append(item_html)
    stats_html = "".join(stats_items)
    
    full_html = f"""
    <html><head><meta charset='UTF-8'><title>{SITE_TITLE}</title><style>
        :root {{ 
            --bg: #fff; --text: #333; --meta: #777; --border: #ddd; --hi: #ffff0033; --link: #1a0dab; --visited: #609; 
            --accent: #27ae60; --inactive: #bdc3c7;
        }}
        @media (prefers-color-scheme: dark) {{ 
            :root {{ --bg: #1a1a1a; --text: #ccc; --meta: #999; --border: #333; --hi: #ffd70033; --link: #8ab4f8; --visited: #c58af9; }} 
        }}
        body {{ font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.2; overflow-x: hidden; }}
        
        /* 頁首配置：將統計按鈕放右邊 */
        .header {{ padding: 10px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; background: var(--bg); z-index: 100; }}
        .header h1 {{ margin: 0; font-size: 18px; font-weight: 900; }}
        .controls {{ display: flex; gap: 10px; align-items: center; }}
        
        .btn {{ cursor: pointer; padding: 4px 12px; border: 1px solid var(--text); font-size: 11px; font-weight: bold; background: var(--bg); color: var(--text); border-radius: 4px; }}
        .btn.active {{ background: #f1c40f; border-color: #f1c40f; color: #000; }}
        
        /* 隱藏式統計面板 */
        #stats-details {{ display: none; padding: 15px 20px; background: rgba(0,0,0,0.02); border-bottom: 1px solid var(--border); column-count: 2; column-gap: 40px; }}
        @media (prefers-color-scheme: dark) {{ #stats-details {{ background: #222; }} }}
        @media (max-width: 800px) {{ #stats-details {{ column-count: 1; }} }}
        
        .stat-row {{ display: flex; align-items: center; gap: 12px; padding: 3px 0; border-bottom: 1px solid rgba(0,0,0,0.03); break-inside: avoid; }}
        .stat-name {{ font-size: 11px; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: monospace; }}
        .stat-bar-container {{ width: 80px; height: 6px; background: #eee; border-radius: 3px; overflow: hidden; }}
        .stat-bar-fill {{ height: 100%; border-radius: 3px; }}
        .stat-count {{ font-size: 11px; font-weight: bold; min-width: 25px; text-align: right; font-family: monospace; }}

        /* 主要新聞區 */
        .wrapper {{ display: grid; grid-template-columns: 1fr 1fr 1fr; width: 100%; max-width: 1900px; margin: 0 auto; gap: 1px; background: var(--border); }}
        .river {{ background: var(--bg); padding: 10px 15px; }}
        .river-title {{ font-size: 17px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 5px; }}
        .column-stats {{ font-size: 10px; color: var(--meta); margin-bottom: 10px; padding-bottom: 5px; border-bottom: 1px dashed var(--border); }}
        
        /* 新聞區塊與連結... (其餘 CSS 保持不變) */
        .story-block {{ padding: 8px 0; border-bottom: 1px solid var(--border); }}
        .headline {{ color: var(--link); text-decoration: none; font-size: 14.5px; font-weight: bold; }}
        .headline:visited {{ color: var(--visited); }}
        body.only-stars .story-block:not(.has-star) {{ display: none; }}
    </style></head><body>
        <div class='header'>
            <h1>{SITE_TITLE}</h1>
            <div class='controls'>
                <div id='stats-btn' class='btn' onclick='toggleStats()'>📊 來源統計</div>
                <div id='star-filter' class='btn' onclick='toggleStarFilter()'>★ 僅看星號</div>
                <div style="font-size:11px; color:var(--meta); margin-left:10px;">{now_str}</div>
            </div>
        </div>
        
        <div id="stats-details">{stats_html}</div>

        <div class='wrapper'>
            {render_column(intl_cls, "Global & Strategy")}
            {render_column(jk_cls, "Japan/Korea Tech")}
            {render_column(tw_cls, "Taiwan IT & Biz")}
        </div>
        
        <script>
            function toggleStats() {{
                const p = document.getElementById('stats-details');
                const btn = document.getElementById('stats-btn');
                const isOpen = p.style.display === 'block';
                p.style.display = isOpen ? 'none' : 'block';
                btn.classList.toggle('active', !isOpen);
            }}
            function toggleStarFilter() {{
                const btn = document.getElementById('star-filter');
                document.body.classList.toggle('only-stars');
                btn.classList.toggle('active');
            }}
            // ... (其餘星星 UI 腳本保持不變)
        </script>
    </body></html>
    """
    save_cache(TRANS_CACHE)
    os.makedirs('output', exist_ok=True)
    with open('output/index.html', 'w', encoding='utf-8') as f: f.write(full_html)
