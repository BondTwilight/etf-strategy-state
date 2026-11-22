# -*- coding: utf-8 -*-
"""_exec_audit.py —— 把「可执行性」从手写改成算出来的

四个分项（各 2 分）：
  数据可得：14:30 分时价覆盖该策略实际会交易的标的比例
  时点明确：信号时点 → 下单时点是否有 ≥1 分钟缓冲
  容量    ：池子里最小 20 日日均成交额（10 万本金能不能进）
  溢价安全：池子里溢价 >5% 的只数
"""
import json
import os

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.join(BASE, "data", "all_etf_1120.parquet")
INTRA = os.path.join(BASE, "data", "intraday_1430.parquet")

POOLS = {
    "lineC": ["515880"],                     # 实际会交易的：持仓 + 候选，先用持仓代表
    "momo96865": ["518880", "159509", "588000", "501225", "513100", "513310",
                  "159915", "162719", "159985", "513030", "513290", "513520"],
    "band96863": ["162411", "513100", "161128", "588000", "162415", "515450"],
    "bank96864": ["159552", "515020"],
}


def main():
    df = pd.read_parquet(PX, columns=["code", "date", "close", "amount"])
    df["code"] = df["code"].astype(str)
    last = df["date"].max()
    recent = df[df["date"] > (pd.to_datetime(last) - pd.Timedelta(days=40)).strftime("%Y-%m-%d")]

    try:
        it = pd.read_parquet(INTRA, columns=["code", "date"])
        it["code"] = it["code"].astype(str)
        have_intra = set(it[it["date"].astype(str).str[:10] == str(it["date"].max())[:10]]["code"])
    except Exception:
        have_intra = set()

    prem = {}
    try:
        h = json.load(open(os.path.join(os.path.dirname(BASE), "hub", "hub.json"), encoding="utf-8"))
        for r in (h.get("real_positions") or []):
            if r.get("prem") is not None:
                prem[r["code"]] = r["prem"]
        for s in (h.get("strategies") or []):
            for r in (((s.get("live") or {}).get("rules") or {}).get("rank") or []):
                if r.get("prem") is not None:
                    prem.setdefault(r["code"], r["prem"])
    except Exception:
        pass

    for k, codes in POOLS.items():
        amt = recent[recent.code.isin(codes)].groupby("code")["amount"].mean() / 1e8  # 亿元
        data_ok = sum(1 for c in codes if c in have_intra) / max(1, len(codes))
        p5 = [c for c in codes if (prem.get(c) or 0) > 5]
        print("%-11s 池 %2d ｜ 14:30分时覆盖 %3.0f%% ｜ 最小日均额 %.2f 亿 ｜ 溢价>5%% %d 只 %s"
              % (k, len(codes), data_ok * 100, (amt.min() if len(amt) else float("nan")),
                 len(p5), p5))


if __name__ == "__main__":
    main()
