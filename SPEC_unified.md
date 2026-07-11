# 分析師統一評估系統 — 最終實作規格（v1）

> 目標：一個註冊表 → 同一支引擎 → 自動判斷時間窗 → 自動三層輸出 → 卡片完全對稱。
> 新分析師進來只貼一個 dict，零客製化。
>
> 本文件已對齊現有程式真實狀態（2026-06-12 稽核）。標 ✅ = 已存在可重用；⚠️ = 已有但需改；❌ = 待新增。

---

## 0. 現況稽核（動工前的事實基準）

| 元件 | 檔案 | 狀態 |
|------|------|------|
| 統一引擎 `build_curve` + `stats`（KOL/股癌/DAC 同跑） | `build_calendar_multi.py` | ✅ |
| 任意 hold 天數、call 頻率加權、週分批 t、分家族 FDR | `build_calendar_multi.py` | ✅ |
| signed 方向（+1看多/−1看空），方向性超額 `pex = sign×(標的−大盤)` | `build_calendar_multi.py:35` | ✅ |
| DAC 逐筆 LLM 抽時間窗 `timeframe_start/end` | `extract_dac_predictions.py`（deepseek） | ✅ |
| KOL 逐股 LLM 抽持有尺度（5級+原文 evidence，多為「未明示」） | `extract_horizon.py` → `horizon_labels.json` | ✅ 生好但**未接入引擎** |
| 前向超額多窗表（相對大盤，週分批，FDR） | `build_forward_excess_multi.py` | ✅ |
| 看空 → 第1層仍當「放空記分」而非現金 | `build_calendar_multi.py:66-67` | ⚠️ 要改 |
| 每筆 call 帶自己的窗（DAC 用 timeframe、KOL 用 horizon、缺的 fallback） | — | ❌ |
| 第3層大盤級預言改用絕對方向（`praw`） | — | ❌ |
| analysts.py 註冊表 | — | ❌ |
| 卡片三格指標統一（命中率/贏大盤率/最大回檔） | — | ⚠️ 部分 |

**KOL 尺度標籤實際分布**（佐證「全掃」是對的預設）：未明示 70、長線存股 8、波段 7、短線 1。
→ 多數 KOL 沒講持有期，標準多窗切片是主路徑，不是退路。

---

## 1. 統一抽象（一句話）

> **每個分析師 = 一串帶方向、帶時間窗的預測 `Call` + 一個 benchmark。其餘全部走同一引擎。**

### Call — 每筆預測的統一格式（所有 loader 必須輸出此格式）

```python
Call = dict(
    target=str,         # 標的代碼，例如 "2330" 或 "SPY"
    date=str,           # 宣告日 ISO "2024-04-01"
    sign=int,           # +1 看多 / -1 看空
    T_start=str|None,   # 評估窗開始 ISO；None = slice
    T_end=str|None,     # 評估窗結束 ISO；None = slice；未來日期 = pending
    window_type=str,    # "explicit" | "scale" | "slice"
)
```

**window_type 三種來源，接口層統一用日期區間表達（引擎內部再換算交易天數）：**

| window_type | T_start | T_end | 說明 |
|-------------|---------|-------|------|
| `explicit` | 日期 | 日期 | DAC 明確時間（LLM 已抽好） |
| `scale` | `date` | `date + N交易日換算成日期` | KOL 有尺度標籤，用 §4 映射表換算後填入 |
| `slice` | `None` | `None` | 無時間資訊，引擎走 HOLDS=[5,20,60,120,250] 迴圈 |

→ `T_end` 在今天之後 → 標 `pending`，不計入已結算統計。
→ DAC 的 target = benchmark（SPY vs SPY），於是 `pex≈0`，第3層自動改讀 `praw`（絕對方向）。零分支。

---

## 2. 三層輸出（同一份 build_curve 輸出的三種讀法）

| 層 | 在問什麼 | 從哪讀 | 操作定義 |
|----|----------|--------|----------|
| 1 策略表現 | 跟著他 $100 變多少 | `praw` 累積 vs benchmark 累積 | 看多持有、**看空→現金（不放空）** |
| 2 分類排名 | 同類誰強 | 標籤（擇時/選股）+ 組內排名 | 排名須標「描述性，FDR 後組內差異無統計意義」 |
| 3 預測準度 | 他說的準不準 | 個股級用 `pex`；**大盤級用 `praw`（絕對方向）** | 命中率、贏大盤率；未到期標 pending |

---

## 3. 五個收尾（本次實作範圍）

### 收尾 ①：看空 = 不買（不進策略組合，不是放空、也不是現金佔權重）
- 位置：`build_curve` 計 `praw` 處。
- **正確定義**：第1層 praw 組合**只計入看多（sign>0）標的**，等權持有；看空標的**完全不進組合**。某日無任何看多持倉＝空手（praw=0）。
- ⚠️ 易錯點：不可把看空標的當「現金 0 報酬」留在組合裡——那會以現金身分佔走資金權重、稀釋看多標的的報酬（股癌看空多，follow_end 會被腰斬 $478→$233）。「看壞石油 ≠ 把 1/3 資金擺現金」，而是「不碰石油」。
- 成本：只有看多進場算交易成本（`newentry` 僅 sign>0 累加）；看空＝不買＝無交易＝無成本。
- **`pex`（第3層）含全部持倉**（看多+看空），`sign×(標的−大盤)`，衡量看空準度；保留看多進場成本以與舊版回歸一致。
- 兩個 active 旗標：`act_long`（有看多持倉，第1層 hit_rate 用）、`act_any`（有任何持倉，第3層 beat_mkt 用）。
- 影響：KOL（全 +1，act_long=act_any）數字不動；股癌 follow_end 恢復 $478；DAC 看空 SPY 期間無看多持倉＝空手＝現金。

### 收尾 ②：每筆 call 攜帶自己的時間窗
- `build_curve` 改為接受 `List[Call]`，per-call 讀各自的 `T_start/T_end`。
- **接口層統一日期區間，引擎內部換算交易天數**（§1 Call schema）。
- 解析優先序（loader 負責，不是引擎）：
  1. 有 `timeframe_end`（DAC）→ `window_type="explicit"`，直接填入。
  2. 有 `horizon_labels` 尺度（KOL 少數）→ `window_type="scale"`，用 §4 映射表換算成 `T_end = date + N交易日`。
  3. 否則 → `window_type="slice"`，`T_start=T_end=None`。
- 引擎遇到 `slice` → 照舊跑 HOLDS=[5,20,60,120,250]。
- 維持向後相容：scale/slice 不改 fallback 邏輯，**KOL 數字不動**（驗證用）。

### 收尾 ③：第3層大盤級預言用絕對方向
- 當 `target == benchmark`（DAC：SPY vs SPY），第3層命中率改讀 `praw` 的正負（大盤有沒有照他講的方向走），不用 `pex`。
- 其餘（個股/產業）維持 `pex`（贏大盤率）。
- 實作：在 `stats` 或卡片層加 `is_market_bet` 旗標，決定命中率取 `praw` 或 `pex`。

### 收尾 ④：抽成 `analysts.py` 註冊表
```python
ANALYSTS = {
  "股癌（謝孟恭）": dict(
      loader="gooaye", benchmark="SPY", start="2020-03-01",
      label="個股選股", is_market_bet=False),
  "鄭博見 DAC": dict(
      loader="dac", benchmark="SPY", start="2020-03-01",
      label="大盤擇時", is_market_bet=True),
  # KOL 由 config.TARGET_CHANNELS 批次帶入，label="個股選股", benchmark="TAIEX"
}
```
- `loader`：負責把原始資料轉成統一 call 格式 `(target, date, sign, window)` 的函式名。
- 加新人＝加一個 dict + （若資料格式新）寫一個 loader。引擎、stats、FDR、卡片全自動。

### 收尾 ⑤：卡片三格指標統一
- 每張卡固定三格：**命中率 / 贏大盤率 / 最大回檔**，全部從 `stats` 輸出抓。
- `stats` 需補：`max_drawdown`（從 `praw` 累積曲線算）、`hit_rate`、`beat_mkt`。
- DAC 的「贏大盤率」格改顯示「方向命中率（絕對）」，因 is_market_bet=True。

### 收尾 ⑥：命中率基準前端可見化（把收尾③的隱藏 if 變成可切換鈕）

**動機**：收尾③用後端 `if is_market_bet` 默默決定「命中率用哪把尺」。讀者看到數字卻不知背後基準。改成**前端可見的基準鈕**：同一套程式碼、預設仍由類型決定（公正性零損失），但讀者看得到「現在用哪個基準」、也能自己切去體會差異。

**三個基準（每張卡依類型只露有意義的兩個，預設停對的那個）**：

| 基準（內部 key） | 公式 | ✓ 的意思 |
|------|------|---------|
| `mkt`（比大盤） | `excess > 0` | 跟他贏過傻抱大盤 |
| `dir`（方向對沒） | `sign × 標的報酬 > 0` | 他指的漲跌方向對 |
| `profit`（有賺沒） | `策略報酬 > 0` | 至少沒賠（多頭裡很寬鬆） |

| 分析師類型 | options | default |
|------------|---------|---------|
| 喊單型（KOL、股癌） | `["mkt", "profit"]` | `mkt` |
| 預言型（DAC、吳昌華） | `["dir", "mkt"]` | `dir` |

- ⚠️ **預言型絕不出現 `profit`**：看空腿「跟他=轉現金=報酬0%」，`0 > 0` 永遠 false → 看空全滅。預言型的寬鬆版是 `dir`，不是 `profit`。
- ⚠️ **喊單型絕不出現 `dir`**：多頭裡喊多→標的漲是白送順風單，方向命中率人人爆表，無鑑別力。喊單型的寬鬆版是 `profit`。
- 預言型切 `mkt`（大盤 vs 大盤）→「贏大盤率」恆為 0% 平手；**保留此選項當教育用途**，讓讀者親眼看到為何相對基準對純擇時者沒意義。

**後端輸出（`build_call_results` / `stats`）**：
1. 每筆 call 多存 `ret`（標的原始報酬）與 `sign`，使前端能即時算三種命中。
2. 每位分析師輸出 `baseline = {"default": "mkt", "options": ["mkt", "profit"]}`（取代收尾③的單一隱藏分支）。
3. `stats` 對該分析師 `options` 中的每個基準各輸出一份命中率快取（`hit_by_baseline = {"mkt": 52, "profit": 60}`），前端切換時直接取值、不重算。

**前端（`generate_site.py` / `cmRender`）**：
4. 卡片第二部分上方加第三個鈕 `[基準▾]`，與 `[方向▾][天期▾]` 並列；初值讀 `baseline.default`，選項讀 `baseline.options`。
5. `make_stats3` 拿掉硬編 `is_market_bet` 分支 → 改讀當前基準鈕狀態取對應數字。
6. 第二部分數字 + 八欄表「結果」欄 onChange 跟基準鈕連動重算。
7. **順手修 `$4` 矛盾 bug**：判決句併入 `cmRender`，$ 值與判決文字都跟 `[方向▾]` 連動（現況：$ 跟著方向鈕變、判決文字寫死「做多腿」→ 切到看空時自相矛盾）。

---

## 4. 模糊時間詞映射表（公開記錄的預設）

| 模糊詞 | hold（交易日） |
|--------|----------------|
| 當沖隔日 / 搶短 / 隔日 | 5 |
| 短線 / 短期 / 即將 | 5 |
| 波段 / 一個月內 / 中線 | 20 |
| 中期 / 一季 | 60 |
| 長線 / 長期 / 存股 | 120（或 250） |
| 未明示 | → 走 slice 全掃 |

對齊 `extract_horizon.py` 的 5 級分類；卡片需註明此為公開預設映射。

---

## 5. 卡片統一元素（每張都有，僅表格內容/窗來源不同）

| 元素 | 來源 |
|------|------|
| Headline：$100 跟他 vs $100 買大盤 | `stats.follow_end` / `stats.mkt_end` |
| 淨值曲線（兩條） | `stats.curve` / `stats.mcurve` |
| 分組標籤 | `ANALYSTS[name].label` |
| 一句判決 | 由 excess_ann + fdr_sig 規則生成 |
| 三格：命中率/贏大盤率/最大回檔 | `stats` |
| 基準鈕 `[基準▾]`（收尾⑥） | `stats.baseline.{default,options}`；數字取 `stats.hit_by_baseline[當前基準]` |
| 多天期表 | window_type=slice → 5/20/60/120/250 Alpha 表；explicit/scale → 對應窗方向正確率（含 pending） |
| 加值區 | DAC 保留「預言中不中」原始表；其他人自訂 |

---

## 6. 驗收標準

1. **回歸測試**：所有人若強制走 slice，輸出須與現行 `calendar_multi.json` 逐欄一致（證明重構沒動到已驗證引擎，含 $221 可重現性）。
2. 股癌、DAC 第1層切換成「看空→現金」後，數字變化須能用「看空不再放空」解釋並記錄於 method note。
3. DAC 的 2026 預言正確標 pending、不污染已結算命中率。
4. 加一個假分析師（貼一個 dict）能跑出完整三層+卡片，全程不改引擎。
5. FDR 仍分家族（KOL 一家、股癌一家、DAC 一家）。

---

## 7. 實作順序建議

1. 收尾①（改一行區、低風險、先跑回歸測試確認 KOL 不變）。
2. 收尾④（抽 analysts.py，純重構，回歸測試護航）。
3. 收尾②（per-call 窗，最大改動，slice fallback 保證相容）。
4. 收尾③（大盤級絕對方向）。
5. 收尾⑤（stats 補指標 + 卡片 UI）。
6. 收尾⑥（基準鈕：後端吐 `ret`/`sign`/`baseline`/`hit_by_baseline` → 前端鈕連動 + 修 $ 判決句連動 bug）。先後端、再前端，因前端連動靠後端資料。

每一步跑一次 §6.1 回歸測試再進下一步。
