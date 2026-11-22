# -*- coding: utf-8 -*-
import os, sys, json
import numpy as np, pandas as pd
BASE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, BASE)
import bt_etf_dip as bt, bt_multi as bm, data_quality

df = pd.read_parquet(os.path.join(BASE, "data", "all_etf_1119.parquet"))
df["code"] = df["code"].astype(str)
pool = json.load(open(os.path.join(BASE, "data", "fixed_pool.json"), encoding="utf-8"))
codes = [str(c) for c in pool["codes"]]
bmap = {str(k): int(v) for k, v in pool["bmap"].items()}
hist = {}
for c in codes:
    s = df[df.code == c][["date", "open", "close", "high", "low"]].copy()
    if len(s) >= 80: hist[c] = s
hist, _ = data_quality.audit(hist, verbose=False)
m = bt.build_matrices(hist, start="2020-01-01", end="2026-11-19")
r = bm.run(m, bmap, max_hold=1, intraday_stop=True, exec_mode="close", cash0=100000.0)
t = r["trades"]
s = t[t.action == "sell"].copy()
s["year"] = pd.to_datetime(s["date"]).dt.year
print("trades by year:", s.groupby("year").size().to_dict())
print("\nTop 10 single-trade returns:")
print(s.nlargest(10, "ret")[["date", "code", "ret", "reason"]].to_string(index=False))
print("\nWorst 5:")
print(s.nsmallest(5, "ret")[["date", "code", "ret", "reason"]].to_string(index=False))
print("\n2022 sells:")
print(s[s.year == 2022][["date", "code", "ret", "reason"]].to_string(index=False))
