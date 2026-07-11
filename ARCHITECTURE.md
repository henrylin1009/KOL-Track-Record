# 專案架構地圖

> 一句話：用真實股價驗證「台灣財經 YouTube KOL 喊的單，能不能賺贏大盤」，再做成互動網站讓散戶自己判斷。
> 結論（誠實的負面結果）：用同一把嚴格的尺掃 13 人，**多重比較校正後無一人穩定贏大盤**。

本檔只描述「**現役核心**」。研究歷程中被否證/取代的腳本已移到 [`archive/`](archive/)（移動非刪除，保留研究證據）——說明見 [`archive/README.md`](archive/README.md)。

---

## 系統其實很小：執行時真正互相依賴的只有 5 個檔

```
build_calendar_multi.py  ──import──>  config.py
   （核心引擎）           ──import──>  analysts.py ──> config.py
                         ──import──>  rw_core.py（Romano-Wolf 統計）

generate_site.py         ──import──>  verdict_rules.py
   （網站生成器）
```

主目錄看起來檔案多，是因為混了三種東西：**程式（~40 個 .py）+ 資料/產出（.json/.db/.pkl）+ 文件（.md）**。其中真正組成「系統」的活檔，分四段如下。

---

## 「統一」的完成度：引擎已統一，抽取與網站資料源遷移中

「每位都用同一把尺」這件事分三層，目前**只有最關鍵的引擎層真正統一**，另兩層的統一機制已蓋好但人還沒全搬過去——這是研究決策刻意暫緩，非工程疏漏（詳見 strategy.md 的「全遷 A/B/C/D 決策」）。

| 層 | 狀態 | 說明 |
|----|------|------|
| ③ 判決引擎 | ✅ **已統一** | `build_calendar_multi.py` 一個 `build_curve`/統計/Romano-Wolf 跑全部 13 人，只讀 `calendar_multi.json` + 價格快取 |
| ② 抽取/載入 | ✅ **已遷移（2026-07-01）** | KOL 全改統一抽取，數字已定版並重鎖 baseline（郭哲榮 $293→$241、謝晨彥 $339→$213…雙向移動，但**結論不變且更誠實**：Romano-Wolf 存活仍 = 0）。被取代的**個人專屬抽取器已歸檔**（見 archive/） |
| ④ 網站資料源 | 📊 **部分收斂** | `generate_site.py` 仍讀數個 gooaye/dac 補充 JSON（因子拆解、預測力表、DAC 淨值）——**引擎不算的補充描述**，非判決。要不要併進 calendar_multi.json 是「網站內容決策」，非清理 |

> 圖例：**（無標記）= 已統一/共用**；**📊 = 引擎不算的補充描述（保留但屬「描述非判決」）**。

---

## 四段資料流

```
① 抓資料 ──> ② LLM 讀懂 ──> ③ 回測+統計（心臟）──> ④ 做成網站
字幕+股價     抽出買賣決策     跟他 vs 買大盤+顯著性     互動卡片牆
```

### 段① 抓資料

| 檔案 | 幹嘛 |
|------|------|
| `youtube_fetcher.py` | YouTube 字幕底層工具（yt-dlp 主、transcript-api 備援，優先 ASR 字幕） |
| `fetch_transcripts.py` | ★**通用字幕抓取器**（吃 `@handle`，取代已歸檔的 fetch_dac/wu 專用版） |
| `groq_transcriber.py` | 沒字幕時用 Groq Whisper 把語音轉文字（備用） |
| `build_density_stocks.py` | 批次抓 10 頻道字幕 → 算個股提及密度 → 存 DB |
| `scan_stock_universe.py` / `clean_universe.py` | 掃「被提到過的股票清單」並清掉誤匹配 |
| `build_yf_cache.py` / `build_full_price_cache.py` | yfinance 抓全台股 1900+ 支還權股價（含下市股，堵 survivorship） |
| `backfill_delisted.py` / `ensure_prices.py` | 補抓缺漏 / 下市股的價格 |
| `data_loader.py` | FinMind 封裝 + 重試 + 快取（被價格快取腳本共用的底層工具） |
| `signals_stocks.db` | 主資料庫（SQLite）：影片紀錄 / 提及密度 / 情緒分數 |
| `full_price_cache.pkl` | 主力股價快取（pickle，34MB） |

### 段② 用 LLM 讀懂字幕

把「老師講的一大段話」變成「結構化買賣決策」。

| 檔案 | 幹嘛 |
|------|------|
| `extract_decisions.py` | ★**統一抽取器**：一個 prompt 處理喊單/預言/板塊三型 → 決策（標的/多空/日期/原文證據） |
| `resolve_target.py` | 名稱 → 代碼（「台積電」→ 2330），新板塊用 LLM 生成籃子 |
| `extract_predictions.py` | ★**通用版預言抽取器**（泛化自 wu/dac，取代下列 ⏳ 派系） |
| `extract_all_kols.py` | 批次對 10 位 KOL 跑統一抽取 → `data_cache/kol_*_decisions.json` |
| `classify_analyst.py` | 判型閘門：call（喊單型） vs forecast（預言型） |
| `build_sentiment_groq.py` / `build_sentiment_stocks.py` / `llm_scorer.py` | 舊版情緒評分（DeepSeek 三維分數），保留供 `load_kol` 讀 signals_stocks.db |
| `*_predictions.json` / `*_decisions.json` | LLM 抽出來的結構化結果 |

### 段③ 回測 + 統計（心臟）

| 檔案 | 幹嘛 |
|------|------|
| `build_calendar_multi.py` | ★★★ 全站核心引擎。calendar-time 固定資金 + call 頻率加權 + 看空持現金 + 週分批 t；13 人 × 5 天期 → `calendar_multi.json` |
| `rw_core.py` | ★ Romano-Wolf stepdown 多重檢定（circular block bootstrap，控 FWER）— 最終判決法 |
| `verdict_rules.py` | 同一張規則表對所有人生成中性判決句（消滅手寫特例） |
| `analysts.py` | ★ 分析師註冊表 + 各型 Call loader。**加新人＝填一筆 dict，不改引擎** |
| `survivorship_test.py` | ★ 方法論招牌：證明早期看似找到的 alpha 大半是 survivorship bias |
| 📊 `backtest_gooaye_factor/kolstyle/predict/v2.py` | 股癌**補充描述**（因子拆解／預測力表／三版本淨值）；主判決已用統一引擎，這些只餵網站的補充區塊 |
| 📊 `backtest_dac.py` / `backtest_dac_equity.py` | DAC 淨值圖（補充）；命中率判決已由引擎 `direction_hit_rate` 涵蓋 |
| `calendar_multi.json` | ★ 全站主資料檔：13 人 × 5 天數的所有結果 |

### 段④ 做成網站

| 檔案 | 幹嘛 |
|------|------|
| `generate_site.py` | ★ 網站生成器。⏳ 目前同時讀 13 個 JSON（calendar_multi.json + dac_*/gooaye_*/kol_* 等派系檔）；全遷後應收斂成只讀 calendar_multi.json |
| `index.html` | 最終產品：自包含互動網站（卡片牆 + modal + 可調天數/方向控制條） |
| `audit/*.md` | 每人的審計摺疊說明 |

### 自動化 / 維運

| 檔案 | 幹嘛 |
|------|------|
| `add_analyst.py` | 端到端：一行指令 `@handle` → 抓字幕→抽預言→補價→註冊 |
| `config.py` | 全域設定（頻道清單、龍頭股、回測參數、API） |
| `regression_test.py` | 改完 code 後驗證結果有沒有跑掉 |

---

## 怎麼重跑（從已抽好的資料開始最快）

```bash
source .venv/bin/activate
python build_calendar_multi.py   # 引擎 → calendar_multi.json（印出 13 人 × 5 天期表）
python generate_site.py          # → index.html
open index.html
```

---

## 五個堵死「假 alpha」的防呆（這是專案真正的含金量）

| 漏洞 | 會製造的假象 | 防呆 |
|------|------|------|
| 無限資金（每筆 +$1） | 灌出假 alpha | calendar-time 固定資金（Jaffe 1974） |
| 重疊窗口相關 | t 值灌水 | 日報酬壓成週 → 週分批 t |
| 等權作弊 | 小型妖股灌爆報酬 | call 頻率加權（反覆喊的大型股佔重） |
| 放空幻覺 | 散戶做不到的策略 | 看空 = 持現金，不計入散戶淨值 |
| 多重比較 | 掃 54 檢定總會矇中幾個 | Romano-Wolf stepdown（控 FWER） |

---

## 統一收尾狀態（2026-07-01 完成）

- ✅ 引擎統一、KOL 全遷統一抽取、數字定版、baseline 重鎖、回歸綠燈、`generate_site` 實跑通過。
- ✅ 被取代的個人專屬抽取器（fetch_dac/wu、extract_dac/wu、extract_gooaye_open、map_gooaye_themes）已歸檔；多餘的 calendar_multi 中間檔移入 `archive/data_backup/`。
- 📊 唯一保留的「派系」是 gooaye/dac 的**補充描述**腳本（因子拆解等），因為網站仍顯示那些區塊——這是**內容決策**（要不要在站上呈現），非清理問題。若日後決定站上只留判決、拿掉補充描述，這些也可歸檔。
