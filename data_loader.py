"""資料採集層：FinMind 封裝 + 斷線重試 + 本地快取 + 完整性檢查/警報。

對應 PLAN.md 第 1 節「數據採集與資料庫防禦」：
- 斷線重試（指數退避）。
- 本地快取（FinMind 免費版每小時約 300 次請求）。
- 完整性檢查：任一板塊缺收盤價/當沖量即發警報，禁止 NaN 進入下一步。
"""

from __future__ import annotations

import os
import time
import warnings

import pandas as pd
from FinMind.data import DataLoader

import config


class DataIntegrityError(Exception):
    """資料完整性檢查失敗 → 觸發警報、中止管線（絕不讓 NaN 進入下一步）。"""


class TWDataLoader:
    def __init__(self, cache_dir: str = config.CACHE_DIR, max_retries: int = 4):
        self.dl = DataLoader()
        # 有 token 就登入，突破免費版 300次/小時限制
        if config.FINMIND_API_TOKEN:
            try:
                self.dl.login_by_token(api_token=config.FINMIND_API_TOKEN)
            except Exception as e:
                warnings.warn(f"FinMind token 登入失敗，改用匿名模式: {e}")
        self.cache_dir = cache_dir
        self.max_retries = max_retries
        os.makedirs(cache_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # 底層：帶斷線重試 + 快取的單一資料集抓取
    # ------------------------------------------------------------------
    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.pkl")

    def _fetch_with_retry(self, fn, **kwargs) -> pd.DataFrame:
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                df = fn(**kwargs)
                if df is None or len(df) == 0:
                    raise ValueError("empty response")
                return df
            except Exception as e:  # 斷線 / API 延遲 / 限流
                last_err = e
                wait = 2 ** attempt
                warnings.warn(f"[retry {attempt+1}/{self.max_retries}] {fn.__name__} {kwargs}: {e}; wait {wait}s")
                time.sleep(wait)
        raise DataIntegrityError(f"抓取失敗（已重試 {self.max_retries} 次）: {fn.__name__} {kwargs} -> {last_err}")

    def _cached(self, key: str, fn, **kwargs) -> pd.DataFrame:
        path = self._cache_path(key)
        if os.path.exists(path):
            return pd.read_pickle(path)
        df = self._fetch_with_retry(fn, **kwargs)
        df.to_pickle(path)
        return df

    # ------------------------------------------------------------------
    # 各資料流
    # ------------------------------------------------------------------
    def stock_daily(self, stock_id: str, start: str, end: str) -> pd.DataFrame:
        key = f"price_{stock_id}_{start}_{end}"
        df = self._cached(key, self.dl.taiwan_stock_daily,
                          stock_id=stock_id, start_date=start, end_date=end)
        return df

    def margin(self, stock_id: str, start: str, end: str) -> pd.DataFrame:
        key = f"margin_{stock_id}_{start}_{end}"
        return self._cached(key, self.dl.taiwan_stock_margin_purchase_short_sale,
                            stock_id=stock_id, start_date=start, end_date=end)

    def day_trading(self, stock_id: str, start: str, end: str) -> pd.DataFrame:
        key = f"daytrade_{stock_id}_{start}_{end}"
        return self._cached(key, self.dl.taiwan_stock_day_trading,
                            stock_id=stock_id, start_date=start, end_date=end)

    def taiex(self, start: str, end: str) -> pd.DataFrame:
        key = f"taiex_{start}_{end}"
        df = self._cached(key, self.dl.taiwan_stock_total_return_index,
                          index_id=config.TAIEX_INDEX_ID, start_date=start, end_date=end)
        return df

    # ------------------------------------------------------------------
    # 完整性檢查（PLAN.md 防禦機制）
    # ------------------------------------------------------------------
    @staticmethod
    def check_integrity(df: pd.DataFrame, required_cols: list[str], label: str) -> None:
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            raise DataIntegrityError(f"[{label}] 缺少欄位: {missing_cols}")
        for c in required_cols:
            n_nan = df[c].isna().sum()
            if n_nan > 0:
                raise DataIntegrityError(
                    f"[{label}] 欄位 '{c}' 有 {n_nan} 個空值（NaN），警報！禁止進入下一步。"
                )
        if len(df) == 0:
            raise DataIntegrityError(f"[{label}] 資料為空，警報！")


def to_date_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    return out.set_index("date").sort_index()
