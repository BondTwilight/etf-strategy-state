# -*- coding: utf-8 -*-
"""成本阶梯：暴跌日买卖价差会从 1 个 tick 扩到 2~3 个 tick，用它做资金规划"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

d = json.load(open("data/fixed_pool.json", encoding="utf-8"))
BMAP = {str(k): int(v) for k, v in d["bmap"].items()}

raw = pd.read_parquet("data/etf_qfq_cifang.parquet",
                      columns=["code", "date", "open", "close", "low"])
raw["date"] = raw["date"].astype(str).str[:10]
hist = {}
for code, g in raw.groupby("code", sort=False):
    f, _ = data_quality.repair_prices(g[["date", "open", "close", "low"]])
    hist[code] = f.reset_index(drop=True)
del raw
m = bt1.build_matrices(hist, start="2021-01-01", end="2026-10-20")

print("  %-34s %9s %9s %7s %6s %6s %5s" % ("成本模型", "年化", "回撤", "Calmar", "夏普", "胜率", "笔"))
for tf, base, name in [
    (0.0, 0.0005, "统一 5bp（理想盘口）"),
    (0.5, 0.0005, "半 tick，下限 5bp"),
    (1.0, 0.0005, "1 tick，下限 5bp"),
    (2.0, 0.0010, "2 tick，下限 10bp"),
    (3.0, 0.0010, "3 tick，下限 10bp"),
    (0.0, 0.0025, "统一 0.25%（压力情形）"),
]:
    r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True, trail=0.08, be_stop=0.03, cash_yield=0.025,
               slippage=base, tick_frac=tf)
    p = bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])
    wr = p["win_rate"] * 100 if np.isfinite(p["win_rate"]) else float("nan")
    print("  %-34s %8.2f%% %8.2f%% %7.2f %6.2f %5.1f%% %5d"
          % (name, p["cagr"] * 100, p["max_dd"] * 100, p["calmar"],
             p["sharpe"], wr, p["trades"]), flush=True)
