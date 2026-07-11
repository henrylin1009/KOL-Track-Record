"""
rw_core.py — Romano-Wolf stepdown 多重檢定的純函式核心（無引擎依賴，供引擎與原型共用）

提供：
  weekly_excess(daily, act)         每日方向性超額(持倉日) → 週分批序列
  romano_wolf_reject(series, ...)   一組「週超額序列」→ stepdown 拒絕(顯著)的 key 集合

統計量 = 週超額的 studentized t（單尾：贏為好）。circular block bootstrap 置中施加 H0、
保留序列/重疊窗相關，取「仍存活欄」的 max-t 分布上分位當臨界值，由大到小逐步踢。
Romano & Wolf (2005, Econometrica; 2016 refinement)。
"""
from __future__ import annotations
from math import sqrt
import numpy as np
import pandas as pd


def weekly_excess(daily: pd.Series, act: pd.Series) -> pd.Series:
    """每日方向性超額(僅持倉日 act=True) → 週分批平均序列（index=週 period）。"""
    s = daily[act]
    if len(s) == 0:
        return pd.Series(dtype=float)
    return s.groupby(s.index.to_period("W")).mean()


def _stud_t(col: np.ndarray) -> float:
    x = col[~np.isnan(col)]
    n = len(x)
    if n < 3:
        return np.nan
    sd = x.std(ddof=1)
    if sd == 0:
        return 0.0
    return x.mean() / (sd / sqrt(n))


def romano_wolf_reject(series: dict, alpha: float = 0.05, B: int = 5000,
                       block: int = 5, min_weeks: int = 10, seed: int = 42):
    """series: {key: 週超額序列}。回傳 (rejected_set, t_obs_dict)。
    單尾（贏大盤/方向為正）。檢定數 < 2 時退化為單一 t>臨界（仍 bootstrap）。"""
    keys = [k for k, s in series.items() if len(s) >= min_weeks]
    if not keys:
        return set(), {}
    wide = pd.DataFrame({k: series[k] for k in keys}).sort_index()
    W, K = wide.shape
    M = wide.values
    t_obs = np.array([_stud_t(M[:, j]) for j in range(K)])
    M0 = M - np.nanmean(M, axis=0)                    # 置中 → H0

    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(W / block))
    Tstar = np.empty((B, K))
    for b in range(B):
        starts = rng.integers(0, W, size=n_blocks)
        idx = np.concatenate([(np.arange(s, s + block) % W) for s in starts])[:W]
        samp = M0[idx, :]
        for j in range(K):
            Tstar[b, j] = _stud_t(samp[:, j])
    Tstar = np.nan_to_num(Tstar, nan=-np.inf)

    order = np.argsort(-t_obs)
    active = list(range(K))
    rejected = set()
    for rank in range(K):
        j = order[rank]
        if j not in active:
            continue
        crit = np.quantile(Tstar[:, active].max(axis=1), 1 - alpha)
        if t_obs[j] > crit:
            rejected.add(keys[j])
            active.remove(j)
        else:
            break
    return rejected, {keys[j]: float(t_obs[j]) for j in range(K)}
