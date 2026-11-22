# -*- coding: utf-8 -*-
"""_verify_nov.py —— 11 月（10-31~11-20）6 只消费池表现 + 96863 实际持仓路径"""
import json
import os
import sys

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)
import _p4_band as pb

CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]
N = {"162411": "油气", "513100": "纳指100", "161128": "标普信息",
     "588000": "科创50", "162415": "美国消费", "515450": "红利低波"}
pb.DATA = os.path.join(BASE, "data", "all_etf_1120.parquet")
codes, _ = pb.load_pool_codes()
hist, p_all, _ = pb.load_all(set(codes) | set(CONSUME))

px = p_all[CONSUME]
print("11 月（10-31 收盘 → 11-20 收盘）")
base = px.loc[:"2026-10-31"].iloc[-1]
last = px.iloc[-1]
for c in CONSUME:
    r = (last[c] / base[c] - 1) * 100
    # 19 日区间涨幅（以 11-20 为终点，look=18 ⇒ 往前 18 个交易日）
    s = px[c].dropna()
    m19 = (s.iloc[-1] / s.iloc[-19] - 1) * 100 if len(s) > 19 else float("nan")
    print("  %-8s %-10s 11月 %+7.2f%% ｜ 19日区间 %+7.2f%%" % (c, N[c], r, m19))

print("\n96863 交易记录（2026-10-01 起）")
r = pb.run_band(px.loc["2021-01-04":])
tr = r["trades"]
print("trades 类型", type(tr), "列", list(tr.columns) if isinstance(tr, pd.DataFrame) else "")
if isinstance(tr, pd.DataFrame) and len(tr):
    t = tr.copy()
    dc = "date" if "date" in t.columns else ("d" if "d" in t.columns else None)
    if dc:
        t[dc] = t[dc].astype(str).str[:10]
        print(t[t[dc] >= "2026-10-01"].to_string(index=False))
    else:
        print(t.tail(10).to_string(index=False))
    print("\n总记录 %d ｜ 平仓 %d" % (len(t), int((t["action"] != "buy").sum())))
