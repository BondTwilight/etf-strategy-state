# -*- coding: utf-8 -*-
"""_probe_pxdiff.py —— 新旧库 3679 行偏离：谁对？

差异根源是 data_quality.repair_prices 在 2026-11-22 加了「尖峰判定」，不是数据源变了。
必须确认：新库把哪些标的的价格改了多少、改得对不对。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

new = pd.read_parquet("data/all_etf_1120.parquet")
old = pd.read_parquet("data/all_etf_1119.parquet")
for d in (new, old):
    d["code"] = d["code"].astype(str)
    d["date"] = d["date"].astype(str).str[:10]

j = new.merge(old[["code", "date", "close"]], on=["code", "date"], suffixes=("_n", "_o"))
j["r"] = j["close_n"] / j["close_o"]
dev = j[(j.r - 1).abs() > 0.001]
print("重叠 %d 行 ｜ 偏离 %d 行（%.2f%%）｜ 涉及 %d 只"
      % (len(j), len(dev), 100.0 * len(dev) / len(j), dev.code.nunique()))

print("\n按标的汇总（偏离行数 TOP15）：")
g = dev.groupby("code").agg(n=("r", "size"), rmin=("r", "min"), rmax=("r", "max"))
print(g.sort_values("n", ascending=False).head(15).to_string())

print("\n偏离最大 10 行（含两种口径的日涨跌，判断谁是真跳变）：")
worst = dev.reindex((dev.r - 1).abs().sort_values(ascending=False).index).head(10)
for _, x in worst.iterrows():
    c, d = x.code, x.date
    sn = new[(new.code == c) & (new.date <= d)].sort_values("date").close.tail(3)
    so = old[(old.code == c) & (old.date <= d)].sort_values("date").close.tail(3)
    print("  %-7s %s  新 %s ｜ 旧 %s" % (c, d,
          " ".join("%.3f" % v for v in sn.values), " ".join("%.3f" % v for v in so.values)))

# 用腾讯日线核对 3 只
print("\n用腾讯不复权日线核对（2021 年前后价格量级）：")
import web_quote
for c in ["510150", "513100", "510230"]:
    k = web_quote._kline_tencent(c, 400)
    if k.empty:
        print("  %s 腾讯无数据" % c)
        continue
    s = k.set_index("date")["close"].astype(float)
    print("  %s 腾讯 %s~%s ｜ 首 %.3f 末 %.3f ｜ 中位 %.3f"
          % (c, s.index[0], s.index[-1], s.iloc[0], s.iloc[-1], s.median()))

print("\n新库同三只：")
for c in ["510150", "513100", "510230"]:
    s = new[new.code == c].sort_values("date").set_index("date")["close"]
    o = old[old.code == c].sort_values("date").set_index("date")["close"]
    print("  %s 新 %s~%s 首 %.3f 末 %.3f ｜ 旧 首 %.3f 末 %.3f"
          % (c, s.index[0], s.index[-1], s.iloc[0], s.iloc[-1], o.iloc[0], o.iloc[-1]))
