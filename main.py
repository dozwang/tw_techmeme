

    <html><head><meta charset='UTF-8'><title>豆子版 Techmeme，彙整台美日韓最新IT新聞. 2026.v1</title><style>
        :root { 
            --bg: #fff; --text: #333; --meta: #777; --border: #ddd; --hi: #ffff0033;
            --link: #1a0dab; /* 經典深藍 */
            --visited: #609; /* 經典已讀紫 */
        }
        @media (prefers-color-scheme: dark) {
            :root { 
                --bg: #1a1a1a; --text: #ccc; --meta: #999; --border: #333; --hi: #ffd70033;
                --link: #8ab4f8; --visited: #c58af9;
            }
        }
        body { font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.2; }
        .header { padding: 10px 20px; border-bottom: 2px solid var(--text); display: flex; justify-content: space-between; align-items: center; }
        .controls { display: flex; gap: 10px; align-items: center; }
        .filter-btn { cursor: pointer; padding: 3px 8px; border: 1px solid var(--text); font-size: 11px; font-weight: bold; background: var(--bg); color: var(--text); }
        .filter-btn.active { background: #f1c40f; border-color: #f1c40f; color: #000; }
        .column-stats { font-size: 10px; color: var(--meta); margin-bottom: 10px; padding-bottom: 5px; border-bottom: 1px dashed var(--border); font-family: monospace; }
        .stats-summary { background: var(--bg); padding: 5px 20px; font-size: 11px; cursor: pointer; border-bottom: 1px solid var(--border); color: var(--meta); }
        .stats-details { display: none; padding: 15px; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 5px; border-bottom: 1px solid var(--border); }
        .wrapper { display: grid; grid-template-columns: 1fr 1fr 1fr; width: 100%; max-width: 1900px; margin: 0 auto; gap: 1px; background: var(--border); min-height: 100vh; }
        .river { background: var(--bg); padding: 10px 15px; }
        .river-title { font-size: 17px; font-weight: 900; border-bottom: 2px solid var(--text); margin-bottom: 5px; }
        .date-header { background: #444; color: #fff; padding: 2px 8px; font-size: 11px; margin: 15px 0 5px; font-weight: bold; }
        .day-count { float: right; opacity: 0.7; font-weight: normal; }
        .story-block { padding: 8px 0; border-bottom: 1px solid var(--border); transition: background 0.2s; cursor: help; }
        .story-block:hover { background: rgba(0,0,0,0.02); }
        @media (prefers-color-scheme: dark) { .story-block:hover { background: rgba(255,255,255,0.03); } }
        .story-block.priority { border-left: 3px solid #0000ee44; padding-left: 8px; }
        .badge { font-size: 10px; padding: 1px 4px; border-radius: 3px; font-weight: bold; }
        .badge-分析 { background: #8e44ad; color: #fff; }
        .badge-日 { background: #c0392b; color: #fff; }
        .badge-韓 { background: #2980b9; color: #fff; }
        .kw-highlight { background-color: var(--hi); border-radius: 2px; padding: 0 2px; font-weight: 600; color: #000; }
        .analysis-text { color: #8e44ad !important; }
        
        /* 連結樣式優化 */
        .headline { 
            color: var(--link); 
            text-decoration: none; 
            font-size: 15px; 
            font-weight: bold; 
        }
        .headline:visited { color: var(--visited); }
        .headline:hover { text-decoration: underline; }
        
        .sub-link { 
            display: block; 
            font-size: 11px; 
            color: var(--link); 
            opacity: 0.85; 
            margin: 3px 0 0 22px; 
            text-decoration: none; 
        }
        .sub-link:visited { color: var(--visited); }
        .sub-link:hover { text-decoration: underline; opacity: 1; }

        .source-tag { font-size: 11px; color: var(--meta); font-weight: normal; }
        .original-title { font-size: 11px; color: var(--meta); margin: 2px 0 4px 22px; }
        .star-btn { cursor: pointer; color: #ccc; margin-right: 6px; transition: color 0.2s; }
        .star-btn.active { color: #f1c40f; }
        body.only-stars .story-block:not(.has-star) { display: none; }
    </style></head><body>
        <div class='header'>
            <h1>豆子版 Techmeme，彙整台美日韓最新IT新聞. 2026.v1</h1>
            <div class='controls'>
                <div id='star-filter' class='filter-btn' onclick='toggleStarFilter()'>僅顯示星號 ★</div>
                <div style="font-size:11px;">2026-02-21 10:42</div>
            </div>
        </div>
        <div class="stats-summary" onclick="toggleStats()">📊 來源統計 <span id="toggle-txt">▼</span></div>
        <div id="stats-details" class="stats-details"><div class='stat-item'>9to5Google: <span>0</span></div><div class='stat-item'>Ars Technica - All content: <span>0</span></div><div class='stat-item'>Bloomberg Technology: <span>0</span></div><div class='stat-item'>CIO Taiwan: <span>0</span></div><div class='stat-item'>DIGITIMES電子時報: <span>0</span></div><div class='stat-item'>IT - 전자신문: <span>0</span></div><div class='stat-item'>MacRumors: Mac News and Rumors - All Stories: <span>0</span></div><div class='stat-item'>Nikkei Asia: <span>0</span></div><div class='stat-item'>SiliconANGLE: <span>0</span></div><div class='stat-item'>Stratechery: <span>0</span></div><div class='stat-item'>TechCrunch: <span>0</span></div><div class='stat-item'>TechNews 科技新報: <span>0</span></div><div class='stat-item'>Techmeme - Full article | The Verge: <span>0</span></div><div class='stat-item'>Technology: <span>0</span></div><div class='stat-item'>WIRED: <span>0</span></div><div class='stat-item'>iThome 新聞: <span>0</span></div><div class='stat-item'>it.impress.co.jp: <span>0</span></div><div class='stat-item'>www.bnext.com.tw: <span>0</span></div><div class='stat-item'>www.cna.com.tw: <span>0</span></div><div class='stat-item'>ビジネス+IT HotTopics: <span>0</span></div><div class='stat-item'>ビジネス+IT IT導入検討コンテンツ: <span>0</span></div><div class='stat-item'>全記事新着 - 日経クロステック: <span>0</span></div><div class='stat-item'>經濟日報：不僅新聞速度 更有脈絡深度: <span>0</span></div></div>
        <div class='wrapper'>
            <div class='river'><div class='river-title'>Global & Strategy</div><div class='column-stats'>無新資訊</div></div>
            <div class='river'><div class='river-title'>Japan/Korea Tech</div><div class='column-stats'>無新資訊</div></div>
            <div class='river'><div class='river-title'>Taiwan IT & Biz</div><div class='column-stats'>無新資訊</div></div>
        </div>
        <script>
            function toggleStats() {
                const p = document.getElementById('stats-details');
                p.style.display = p.style.display === 'grid' ? 'none' : 'grid';
            }
            function toggleStarFilter() {
                const btn = document.getElementById('star-filter');
                document.body.classList.toggle('only-stars');
                btn.classList.toggle('active');
            }
            function toggleStar(link) {
                let b = JSON.parse(localStorage.getItem('tech_bookmarks') || '[]');
                if (b.includes(link)) b = b.filter(i => i !== link);
                else b.push(link);
                localStorage.setItem('tech_bookmarks', JSON.stringify(b));
                updateStarUI();
            }
            function updateStarUI() {
                const b = JSON.parse(localStorage.getItem('tech_bookmarks') || '[]');
                document.querySelectorAll('.story-block').forEach(el => {
                    const id = el.getAttribute('data-id');
                    const isStarred = b.includes(id);
                    el.querySelector('.star-btn').classList.toggle('active', isStarred);
                    el.classList.toggle('has-star', isStarred);
                });
            }
            document.addEventListener('DOMContentLoaded', updateStarUI);
        </script>
    </body></html>
    
