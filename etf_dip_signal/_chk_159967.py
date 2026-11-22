# -*- coding: utf-8 -*-
"""补拉 159967 最新行情，核实 10-27~10-30 是否跌破保护线"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cifang_api

raw = cifang_api.hist_em(["159967"], "2026-10-15", "2026-11-03", adjust="qfq")
df = raw.get("159967")
if df is None or df.empty:
    print("无数据"); raise SystemExit
df["date"] = df["date"].astype(str).str[:10]
df = df.sort_values("date").reset_index(drop=True)
print(df[["date", "close", "low"]].to_string(index=False))

ENTRY = 0.5876
row = df[df["date"] == "2026-10-21"]
if row.empty:
    print("\n10-21 无数据，改用区间首日折算")
    base = float(df["close"].iloc[0])
else:
    base = float(row["close"].iloc[0])
df["real"] = ENTRY * df["close"] / base
df["pnl"] = df["real"] / ENTRY - 1

print("\n159967 ｜ 成本 %.4f ｜ -8%%线 %.4f ｜ -15%%线 %.4f"
      % (ENTRY, ENTRY * 0.92, ENTRY * 0.85))
print("%-12s %8s %9s %9s  %s" % ("日期", "复权收", "还原真实价", "相对成本", "判断"))
for r in df.itertuples():
    tag = ""
    if r.pnl <= -0.15:
        tag = "★已破 -15%"
    elif r.pnl <= -0.08:
        tag = "★已破 -8%（应触发移动止盈）"
    print("%-12s %8.4f %9.4f %8.2f%%  %s"
          % (r.date, r.close, r.real, r.pnl * 100, tag))
