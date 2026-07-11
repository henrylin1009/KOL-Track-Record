# A 階段自助步驟：S3 + Athena（全程用網頁 console）

要上傳的檔案：`data_cache/calls_flat.parquet`（521 KB，94,177 列逐筆回測）

---

## 1. 建 S3 bucket 並上傳資料

1. Console 搜尋 **S3** → **Create bucket**
2. Bucket name 取全球唯一的名字，例如 `henry-kol-backtest`（記住這名字，後面要用）
3. Region 選 **us-east-1**（Athena 同區、教學資源最多），其他預設即可 → **Create bucket**
4. 點進 bucket → **Create folder** → 命名 `calls` → 建立
5. 進 `calls/` 資料夾 → **Upload** → 把本機 `data_cache/calls_flat.parquet` 拖進去 → **Upload**

> 資料現在在 `s3://henry-kol-backtest/calls/calls_flat.parquet`

---

## 2. 設定 Athena 查詢結果位置（第一次用必做一次）

1. Console 搜尋 **Athena** → 打開 **Query editor**
2. 若跳「set up a query result location」→ 點 **Settings** → **Manage**
3. Location 填 `s3://henry-kol-backtest/athena-results/`（同 bucket 開個新資料夾即可）→ **Save**

---

## 3. 建表（把 S3 的 Parquet 變成能查的 table）

Query editor 貼下面 DDL，把 bucket 名字換成你的，按 **Run**：

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS calls_flat (
  analyst     string,
  market      string,
  label       string,
  `date`      string,
  ticker      string,
  direction   string,
  hold_days   double,
  strat_ret   double,
  bench_ret   double,
  excess_ret  double,
  hit         string,
  is_pending  boolean,
  period      string
)
STORED AS PARQUET
LOCATION 's3://henry-kol-backtest/calls/';
```

> 注意 LOCATION 是**資料夾**（`calls/`）不是檔名——Athena 會讀夾裡所有 parquet。

---

## 4. 開查！幾條可直接跑的分析 SQL

**① 各分析師 20 日超額勝率排行**
```sql
SELECT analyst,
       COUNT(*) AS n_settled,
       ROUND(100.0*SUM(CASE WHEN hit='hit' THEN 1 END)/COUNT(*),1) AS win_rate_pct,
       ROUND(AVG(excess_ret),2) AS avg_excess
FROM calls_flat
WHERE hold_days=20 AND is_pending=false
GROUP BY analyst
HAVING COUNT(*)>=30
ORDER BY win_rate_pct DESC;
```

**② 同一筆 call 在不同持有天期，勝率怎麼變**
```sql
SELECT hold_days,
       ROUND(100.0*SUM(CASE WHEN hit='hit' THEN 1 END)/COUNT(*),1) AS win_rate_pct
FROM calls_flat
WHERE is_pending=false
GROUP BY hold_days
ORDER BY hold_days;
```

**③ 看多 vs 看空，誰比較準（20 日）**
```sql
SELECT direction,
       COUNT(*) AS n,
       ROUND(100.0*SUM(CASE WHEN hit='hit' THEN 1 END)/COUNT(*),1) AS win_rate_pct,
       ROUND(AVG(excess_ret),2) AS avg_excess
FROM calls_flat
WHERE hold_days=20 AND is_pending=false
GROUP BY direction;
```

**④ 被喊最多次的前 15 檔標的**
```sql
SELECT ticker, COUNT(DISTINCT analyst) AS n_analysts, COUNT(*) AS n_call_rows
FROM calls_flat
WHERE hold_days=20
GROUP BY ticker
ORDER BY n_call_rows DESC
LIMIT 15;
```

---

## 成本備忘

Parquet 521KB，每條查詢掃幾百 KB。Athena $5/TB → 一次查約 $0.000002。查上千次也花不到一分錢。放心跑。

## 完成後

跑出結果截圖存證 → 履歷可寫「將回測資料存入 S3，以 Athena SQL 做探索式分析」。
接著回來做 SQL 頁（把這些查詢做進網站）+ B（EC2 部署）。
