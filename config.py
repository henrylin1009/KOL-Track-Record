"""
全域設定：7 大科技板塊、龍頭股、回測參數、API 設定。

注意：
- 各板塊龍頭股為「市值前三大」的代表性選擇（hand-picked），可日後依實際市值動態更新。
- 做多落地方式 = 買該板塊龍頭股、均分資金（對應 PLAN.md 第 4.1 節）。
- API key 統一從 .env 讀取，不寫死在程式碼中。
"""

from __future__ import annotations
import os
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_PATH, override=True)  # 永遠從專案根目錄讀取 .env

# --------------------------------------------------------------------------
# 7 大科技板塊與其龍頭股（stock_id -> 中文名稱）
# 板塊日報酬 = 成分股日報酬等權平均
# --------------------------------------------------------------------------
SECTORS: dict[str, dict[str, str]] = {
    "先進封裝": {
        "3711": "日月光投控",
        "6147": "頎邦",
        "8150": "南茂",
    },
    "IC設計": {
        "2454": "聯發科",
        "3034": "聯詠",
        "2379": "瑞昱",
    },
    "散熱": {
        "3017": "奇鋐",
        "3324": "雙鴻",
        "2421": "建準",
    },
    "PCB": {
        "3037": "欣興",
        "8046": "南電",
        "3189": "景碩",
    },
    "組裝": {
        "2317": "鴻海",
        "2382": "廣達",
        "3231": "緯創",
    },
    "記憶體": {
        "2408": "南亞科",
        "2344": "華邦電",
        "4967": "十銓",
    },
    "面板": {
        "3481": "群創",
        "2409": "友達",
        "6116": "彩晶",
    },
}

SECTOR_NAMES: list[str] = list(SECTORS.keys())

TAIEX_INDEX_ID = "TAIEX"

# --------------------------------------------------------------------------
# 回測期間
# --------------------------------------------------------------------------
BACKTEST_START = "2024-01-01"
BACKTEST_END = "2026-06-01"

# --------------------------------------------------------------------------
# 計量參數
# --------------------------------------------------------------------------
OLS_LOOKBACK_DAYS = 60          # 滾動 OLS 去大盤化視窗（日）
RESID_MOM_SHORT = 20            # 殘差動能短窗（日）
RESID_MOM_LONG = 60             # 殘差動能長窗（日）
CROWDING_LOOKBACK_DAYS = 60     # 當沖擁擠度 z-score 時序視窗

# --------------------------------------------------------------------------
# 交易與成本（對應 PLAN.md 第 5 階段一）
# --------------------------------------------------------------------------
TOP_N = 2                       # 只做多排名 Top 1 與 Top 2
TAX_RATE_NORMAL = 0.003         # 一般交易證交稅 0.3%（賣出課徵）
FEE_RATE = 0.001425             # 券商手續費（單邊，未折讓）
FEE_DISCOUNT = 0.5             # 手續費折讓（5 折，常見電子下單）
SLIPPAGE_RATE = 0.001           # 滑價假設（單邊 0.1%）

# --------------------------------------------------------------------------
# 風控（保命鈕，回測階段先記錄、實盤再強制）
# --------------------------------------------------------------------------
WEEKLY_MAX_DRAWDOWN_STOP = 0.08  # 單週帳戶虧損達 8% → 降半倉
DAYTRADE_TURNOVER_PANIC = 0.65   # 當沖週轉率踩踏警戒線

# --------------------------------------------------------------------------
# 特徵權重（MVP 透明加權打分；之後才換 LightGBM）
# 正值 = 分數越高排名越前
# --------------------------------------------------------------------------
FEATURE_WEIGHTS: dict[str, float] = {
    "resid_mom_short": 0.30,     # 殘差短期動能
    "resid_mom_long": 0.20,      # 殘差長期動能
    "crowding_z": -0.20,         # 擁擠度（過熱 → 反應過度 → 扣分）
    "margin_chg_z": -0.10,       # 融資爆增（散戶追高 → 扣分）
    "sentiment_signal": 0.20,    # 情緒條件式訊號（見 sentiment.py）
}

# --------------------------------------------------------------------------
# ILRS 資訊生命週期輪動策略參數（對應 ilrs_backtest.py）
# --------------------------------------------------------------------------
ILRS_DENSITY_BUY_MAX = 0.20        # 絕對模式買點：KOL 密度 ≤ 20%（孤獨萌芽期）
ILRS_DENSITY_SELL_MIN = 0.70       # 絕對模式賣點：KOL 密度 ≥ 70%（擁擠瘋狂期）
# 密度模式：
#   "absolute" = 直接用密度百分比比 BUY_MAX/SELL_MIN。
#   "xs_rank"  = 每週把 7 板塊依密度做橫斷面百分位排名（解決「絕對門檻失效」：
#                參數防禦發現密度≤20% 佔 81%、≥70% 僅 5%，絕對門檻幾乎不篩）。
ILRS_DENSITY_MODE = "xs_rank"
ILRS_RANK_BUY_MAX = 0.40           # xs_rank 買點：密度排名百分位 ≤ 0.40（相對最孤獨的板塊）
ILRS_RANK_SELL_MIN = 0.70          # xs_rank 賣點：密度排名百分位 ≥ 0.70（相對最擁擠的板塊）
ILRS_BREAKOUT_WINDOW = 20          # 累積殘差突破：過去 N 日最高點
ILRS_MA_WINDOW = 5                 # 累積殘差跌破 N 日均線 → 動能轉弱賣出
ILRS_N_SLOTS = 3                   # 3 個儲位，各 1/3 倉位
ILRS_STOP_LOSS = -0.07             # 進場價 -7% 硬停損（100% 平倉）

# --------------------------------------------------------------------------
# 本地快取（FinMind 免費版每小時約 300 次請求，務必快取）
# --------------------------------------------------------------------------
CACHE_DIR = "data_cache"

# --------------------------------------------------------------------------
# API 設定（從 .env 讀取，不寫死）
# --------------------------------------------------------------------------
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
DEEPSEEK_MODEL: str = "deepseek-chat"   # DeepSeek-V3，繁中理解佳、成本低

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")  # 備用：Claude（反諷辨識更強）

FINMIND_API_TOKEN: str = os.getenv("FINMIND_TOKEN", "")  # 變數名 FINMIND_TOKEN，空字串 = 免費匿名

FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")       # Financial Modeling Prep（備用資料源）
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")     # FRED 總經數據（後續加總經因子用）

YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "")  # 可選，無則手動提供影片 ID

# --------------------------------------------------------------------------
# 目標 YouTube 投顧頻道
# channel_id: YouTube channel ID（@handle 需先查出來）
# name: 中文頻道名
# --------------------------------------------------------------------------
#
# 10 個摩爾系「每日選股喊盤型」投顧頻道（同質性高，適合量化板塊被點名密度）。
# subtitle_rate = 用 yt-dlp 抽樣最近 6 部影片的中文字幕命中率（2026-06 實測），僅供參考。
# 全部以 yt-dlp 為主字幕引擎抓取（見 youtube_fetcher.py）。
TARGET_CHANNELS: list[dict] = [
    {"channel_id": "UChfl3auNxAxOR3wy8a8ysQQ", "name": "郭哲榮", "subtitle_rate": 1.00,
     "note": "摩爾投顧投資長，台股散戶影響力最大的頻道之一"},
    {"channel_id": "UCxhmFqqd28z04vjagnMpJpg", "name": "江國中", "subtitle_rate": 1.00,
     "note": "摩爾投顧，資金集中鎖定主升段飆股"},
    {"channel_id": "UCWNzVtz0t-e4jMKxaXqvfYA", "name": "謝晨彥", "subtitle_rate": 1.00,
     "note": "摩爾投顧，記憶體/AI題材常見"},
    {"channel_id": "UC8DboML09XD8xUKBuYmRDcw", "name": "陳俊言", "subtitle_rate": 1.00,
     "note": "摩爾投顧，反市場散戶羊群、洞悉資金作手"},
    {"channel_id": "UCalPYf4c96yADeRPBIdHOxw", "name": "張貽程", "subtitle_rate": 1.00,
     "note": "摩爾投顧，外資出身資深操盤手（外資超錢線）"},
    {"channel_id": "UCWHR2sdmPvJSJ6TYhX2r8YQ", "name": "何基鼎", "subtitle_rate": 0.83,
     "note": "摩爾投顧，結合總經/財報/技術面（鼎極操盤手）"},
    {"channel_id": "UC9Pd7LN9potuHVafJCLX7Pw", "name": "林鈺凱", "subtitle_rate": 0.83,
     "note": "摩爾投顧，外資交易室出身（股林高手）"},
    {"channel_id": "UCleWOsRmPBhWPvQlSTy7fPw", "name": "林漢偉", "subtitle_rate": 0.67,
     "note": "摩爾投顧，私募基金操盤手出身（決勝關鍵）"},
    {"channel_id": "UCiBLyIFu3KjG2opa7uQHZbQ", "name": "陳昆仁", "subtitle_rate": 0.50,
     "note": "摩爾投顧，精準掌握主流趨勢買賣點（仁者無敵）"},
    {"channel_id": "UCZn9BeImRq3SDLC8WVrVmUw", "name": "鐘崑禎", "subtitle_rate": 0.33,
     "note": "摩爾投顧，期貨操盤手法操作股票（字幕命中率較低）"},
]

# KOL 密度分母設定：
# 名目總頻道數（10），但實際密度以「當週有發片且抓到字幕的頻道數」為動態分母，
# 避免某頻道停更／當週無字幕時把密度低估。見 llm_scorer / build_historical_sentiment。
KOL_DENSITY_TOTAL: int = len(TARGET_CHANNELS)
# 動態分母的下限：當週有效頻道數低於此值，該週密度視為不可靠（NaN），不產生訊號。
KOL_DENSITY_MIN_ACTIVE: int = 4

# 撈過去幾天的影片字幕（週五收盤後回溯 7 天）
SUBTITLE_LOOKBACK_DAYS: int = 7

# --------------------------------------------------------------------------
# LLM 評分設定
# --------------------------------------------------------------------------
LLM_TEMPERATURE: float = 0.1      # 低溫保證輸出穩定
LLM_MAX_TOKENS: int = 1024
LLM_RETRY: int = 3                # JSON 解析失敗最多重試次數

# --------------------------------------------------------------------------
# 本地 SQLite（用於即時訊號管線，回測用 data_cache pkl）
# --------------------------------------------------------------------------
DB_PATH: str = "signals.db"

# --------------------------------------------------------------------------
# 個股 ILRS：Groq 語音密度（signals_stocks.db，與板塊版完全分離）
# --------------------------------------------------------------------------
STOCK_KEYWORDS: dict[str, list[str]] = {
    "3711": ["日月光", "ASE"],
    "6147": ["頎邦"],
    "8150": ["南茂"],
    "2454": ["聯發科", "MediaTek", "MTK", "發科", "連發科"],
    "3034": ["聯詠"],
    "2379": ["瑞昱", "Realtek"],
    "3017": ["奇鋐", "奇紅", "旗宏"],
    "3324": ["雙鴻", "雙紅"],
    "2421": ["建準"],
    "3037": ["欣興"],
    "8046": ["南電"],
    "3189": ["景碩"],
    "2317": ["鴻海", "富士康", "Foxconn"],
    "2382": ["廣達"],
    "3231": ["緯創", "偽創", "尾創"],
    "2408": ["南亞科"],
    "2344": ["華邦電", "華邦"],
    "4967": ["十銓"],
    "3481": ["群創"],
    "2409": ["友達"],
    "6116": ["彩晶"],
}

STOCK_DENSITY_BUY_MAX:  float = 0.10
STOCK_DENSITY_SELL_MIN: float = 0.60
STOCK_CUM_RESID_MA:     int   = 10
STOCK_TRAILING_STOP:    float = -0.07
STOCK_MA_STOP:          int   = 10
STOCK_DB_PATH: str = "signals_stocks.db"

GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_WHISPER_MODEL: str = "whisper-large-v3-turbo"
