"""
resolve_target.py — 標的解析器（決策 → 可算報酬的 ticker(s)）

統一管線第③步：把 LLM 抽出的「他講什麼」變成股票代號。
  asset  商品/大盤   → ASSET_TICKER（黃金→GLD、美股→SPY…）
  stock  個股        → 反查 tw_name_map（name→code）；美股個股走小別名表
  sector 板塊/主題   → sector_basket 查表；新板塊用 LLM 依 industry 生成等權成分

原型階段：新板塊寫到 sector_basket.proto.json（不碰正本 sector_basket.json）。
解析失敗一律「明確回空 + 記原因」，不靜默吞。

用法：
  from resolve_target import Resolver
  r = Resolver()
  r.resolve("stock", "台積電")   # -> (["2330"], "tw_name_map")
  r.resolve("sector", "航運")    # -> (["2603","2609","2615","2606"], "sector_basket")
  r.resolve("asset", "黃金")     # -> (["GLD"], "asset_ticker")
"""
from __future__ import annotations
import json, os, re
from pathlib import Path

from extract_predictions import ASSET_TICKER

# 商品/大盤的中文別名 → asset 標籤（再經 ASSET_TICKER）
ASSET_ALIAS = {
    "黃金": "gold", "金價": "gold",
    "比特幣": "crypto", "加密貨幣": "crypto", "虛擬貨幣": "crypto", "比特": "crypto",
    "美股": "us", "標普": "us", "標普500": "us", "s&p": "us", "納斯達克": "us",
    "道瓊": "us", "美國大盤": "us",
    "港股": "hk", "恒生": "hk",
    "a股": "china", "中國股市": "china", "上證": "china", "陸股": "china",
    "台股": "taiwan", "台股大盤": "taiwan", "加權指數": "taiwan", "大盤": "taiwan",
}

# 指名美股個股別名（KOL 偶爾提及）
US_STOCK_ALIAS = {
    "輝達": "NVDA", "英偉達": "NVDA", "nvidia": "NVDA",
    "特斯拉": "TSLA", "tesla": "TSLA",
    "蘋果": "AAPL", "apple": "AAPL",
    "谷歌": "GOOGL", "微軟": "MSFT", "亞馬遜": "AMZN", "超微": "AMD", "amd": "AMD",
}

TW_NAME_MAP = "tw_name_map.json"
SECTOR_BASKET = "sector_basket.json"   # 唯一正式板塊籃檔（新板塊 LLM 生成後也 append 回此檔）


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).lower()


class Resolver:
    def __init__(self, use_llm_for_sector: bool = True):
        self.use_llm = use_llm_for_sector
        # 反向名稱表：name → code（含正規化鍵）
        self.name2code: dict[str, str] = {}
        self.code_industry: dict[str, str] = {}
        self.industry_codes: dict[str, list[str]] = {}
        tw = json.loads(Path(TW_NAME_MAP).read_text(encoding="utf-8"))
        for code, v in tw.items():
            nm = v.get("name", "")
            if nm:
                self.name2code.setdefault(_norm(nm), code)
            ind = v.get("industry", "")
            self.code_industry[code] = ind
            if ind:
                self.industry_codes.setdefault(ind, []).append(code)
        # 板塊籃（單一正式檔）
        self.baskets: dict[str, list[str]] = {}
        if os.path.exists(SECTOR_BASKET):
            self.baskets.update(json.loads(Path(SECTOR_BASKET).read_text(encoding="utf-8")))
        self.unresolved: list[tuple] = []   # (type,name,reason) 稽核用

    # ── 個股 ──（回傳 codes, market, source）
    def _stock(self, name: str):
        n = _norm(name)
        if re.fullmatch(r"\d{4}", name or ""):
            return [name], "tw", "code_literal"
        if n in self.name2code:
            return [self.name2code[n]], "tw", "tw_name_map"
        if n in US_STOCK_ALIAS:
            return [US_STOCK_ALIAS[n]], "us", "us_alias"
        for nm, code in self.name2code.items():
            if len(nm) >= 2 and (nm in n or n in nm):
                return [code], "tw", "tw_name_map_fuzzy"
        return [], None, "stock_not_found"

    # ── 商品/大盤 ──
    # asset 標籤 → 市場分類
    _ASSET_MARKET = {"us": "us", "hk": "us", "china": "us",
                     "gold": "commodity", "crypto": "commodity", "taiwan": "tw"}

    def _asset(self, name: str):
        n = _norm(name)
        tag = ASSET_ALIAS.get(n)
        if not tag:
            for k, v in ASSET_ALIAS.items():
                if k in n:
                    tag = v; break
        if tag and tag in ASSET_TICKER:
            return [ASSET_TICKER[tag]], self._ASSET_MARKET.get(tag, "us"), "asset_ticker"
        return [], None, "asset_not_found"

    # ── 板塊 ──（台股板塊 → tw）
    def _sector(self, name: str, date: str | None = None):
        if name in self.baskets:
            return self.baskets[name], "tw", "sector_basket"
        n = _norm(name)
        for k, codes in self.baskets.items():
            if _norm(k) == n:
                return codes, "tw", "sector_basket"
        if self.use_llm:
            codes = self._llm_sector(name, date)
            if codes:
                self.baskets[name] = codes
                self._persist_proto(name, codes)
                return codes, "tw", "sector_basket_llm"
        return [], None, "sector_not_found"

    def _llm_sector(self, name: str, date: str | None = None) -> list[str]:
        """依【業務定義】列板塊成員（非挑代表/明星股），等權籃回測用。
        嚴謹規則（斬 look-ahead）：只依主營業務判定、禁用任何股價/報酬/事後表現；
        point-in-time（不納入喊盤日後才上市或轉入者）；求廣度 6–12 支降低選股偏誤。"""
        try:
            from dotenv import dotenv_values
            from openai import OpenAI
            key = dotenv_values(".env").get("DEEPSEEK_API_KEY")
            if not key:
                return []
            client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
            inds = list(self.industry_codes.keys())
            asof = date or "該喊盤當時"
            prompt = (
                f"任務：列出台股主題板塊「{name}」的成分股，供『買進該板塊等權籃』的歷史回測。\n"
                f"【嚴格規則】\n"
                f"1. 只依公司【主營業務／產品線】判定是否屬於此板塊；"
                f"嚴禁用任何股價、報酬、漲跌、市值排名、事後表現、誰是贏家來挑選（這是歷史回測，用未來資訊＝作弊）。\n"
                f"2. Point-in-time：只列在 {asof} 之前【就已上市、且當時主業就屬於此板塊】的公司；"
                f"忽略之後才 IPO、或後來才跨入此領域、或純蹭題材的公司。\n"
                f"3. 只列【本業核心 pure-play】（最主要營收就來自此板塊），最多 8–10 支；"
                f"純 play 少就少列（緊主題如 CoWoS 可能只 3–5 支），"
                f"【不要】把邊緣沾邊、上下游、蹭題材、或整個大產業的公司全列進來（過度納入會稀釋、失真）。\n"
                f"4. 若此板塊無明確對應的上市櫃公司（純概念、太模糊、或非台股），回傳空陣列 []。\n"
                f"參考官方產業分類：{('、'.join(inds))[:500]}\n"
                f'只輸出 JSON：{{"codes":["2603","2609"]}}')
            resp = client.chat.completions.create(
                model="deepseek-chat", temperature=0.0, max_tokens=800,  # 夠大，避免長清單被截斷→JSON壞→靜默回[]
                messages=[{"role": "user", "content": prompt}])
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
            codes = json.loads(raw).get("codes", [])
            # 只留真實 4 碼、且在名冊內（防幻覺代碼）；軟上限 10 支防過度納入稀釋
            return [c for c in codes
                    if re.fullmatch(r"\d{4}", str(c)) and c in self.code_industry][:10]
        except Exception:
            return []

    def _persist_proto(self, name: str, codes: list[str]):
        """新 LLM 生成的板塊籃 append 回正式檔（公開可審）。"""
        cur = {}
        if os.path.exists(SECTOR_BASKET):
            cur = json.loads(Path(SECTOR_BASKET).read_text(encoding="utf-8"))
        cur[name] = codes
        Path(SECTOR_BASKET).write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 主入口 ──
    def resolve(self, target_type: str, name: str, date: str | None = None):
        """回傳 (codes:list[str], market:str|None, source:str)。
        market ∈ {tw, us, commodity}。失敗 codes=[] 且記入 self.unresolved。
        date：該 call 的日期（YYYY-MM-DD），板塊解析用來做 point-in-time（不納入喊盤日後才出現的公司）。"""
        t = (target_type or "").lower()
        if t == "stock":
            codes, market, src = self._stock(name)
        elif t == "asset":
            codes, market, src = self._asset(name)
        elif t == "sector":
            codes, market, src = self._sector(name, date)
        else:
            codes, market, src = [], None, f"unknown_type:{target_type}"
        if not codes:
            self.unresolved.append((target_type, name, src))
        return codes, market, src


if __name__ == "__main__":
    r = Resolver(use_llm_for_sector=False)
    for tt, nm in [("stock", "台積電"), ("stock", "長榮"), ("stock", "2330"),
                   ("asset", "黃金"), ("asset", "美股"), ("asset", "台股大盤"),
                   ("sector", "航運"), ("sector", "半導體"), ("stock", "不存在的公司")]:
        print(f"{tt:7} {nm:8} → {r.resolve(tt, nm)}")
    print("未解析:", r.unresolved)
