# -*- coding: utf-8 -*-
"""_probe_prem_hist.py —— 验证极端溢价是否真实（159509 / 513100）

疑点：159509 现价 2.682、iopv 1.960 ⇒ 溢价 36.8%。两个独立源（次方 iopv、腾讯 f[77]/f[78]）
都给出同一结果，但仍需排除「份额折算导致价格与净值不可比」。

判别法：
  若发生过份额折算（如 1 拆 2），则折算日 iopv 会跳变而价格连续，溢价会从 ~0 跳到 ~100%。
  若溢价是渐变且长期稳定在 30%+，则是真实的 QDII 额度溢价。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import cifang_api

for code, name in [("159509", "纳指科技"), ("513100", "纳指100"), ("513520", "日经")]:
    data = cifang_api._get("/fund/hist_em", {
        "symbol": code, "start_date": "2024-01-01",
        "end_date": "2026-11-21", "adjust": "none"}) or {}
    rows = data.get(code) or []
    if not rows:
        print("%s 无数据" % code)
        continue
    d = pd.DataFrame(rows, columns=cifang_api.COLS[:len(rows[0])])
    d["date"] = d["date"].astype(str).str[:10]
    for k in ("close", "iopv"):
        d[k] = pd.to_numeric(d[k], errors="coerce")
    d = d[d["iopv"] > 0].sort_values("date").reset_index(drop=True)
    d["prem"] = (d["close"] / d["iopv"] - 1) * 100
    d["dp"] = d["prem"].diff()

    print("\n" + "=" * 78)
    print("%s %s ｜ %s ~ %s ｜ %d 个交易日" % (code, name, d.date.iloc[0], d.date.iloc[-1], len(d)))
    q = d["prem"].quantile([0, .05, .25, .5, .75, .95, 1])
    print("  溢价分位：P0 %+.1f%% ｜ P5 %+.1f%% ｜ P25 %+.1f%% ｜ P50 %+.1f%% ｜ P75 %+.1f%% ｜ P95 %+.1f%% ｜ P100 %+.1f%%"
          % tuple(q.values))
    print("  最新 %s ｜ close %.4f ｜ iopv %.4f ｜ 溢价 %+.2f%%"
          % (d.date.iloc[-1], d.close.iloc[-1], d.iopv.iloc[-1], d.prem.iloc[-1]))
    # 折算/跳变检测
    big = d[d["dp"].abs() > 15]
    if len(big):
        print("  ⚠️ 溢价单日跳变 >15pp 的日期（判份额折算）：")
        print(big[["date", "close", "iopv", "prem", "dp"]].to_string(index=False))
    else:
        print("  ✅ 无单日 >15pp 跳变 ⇒ 不是份额折算造成的假溢价")
    # 最近 12 个月按季度
    d["ym"] = d.date.str[:7]
    g = d.groupby("ym")["prem"].agg(["count", "median", "min", "max"]).tail(8)
    print("  近 8 个月溢价：")
    for ym, row in g.iterrows():
        print("     %s  n=%3d  中位 %+7.2f%%  区间 [%+.2f%%, %+.2f%%]"
              % (ym, row["count"], row["median"], row["min"], row["max"]))
