# -*- coding: utf-8 -*-
"""精简版：只验「移动止盈8%」是否等价于「把止损收到 -8%」
尽量省内存：只保留 close/low/open 三列
"""
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
nfix = 0
for code, g in raw.groupby("code", sort=False):
    f, hits = data_quality.repair_prices(g[["date", "open", "close", "low"]])
    nfix += len(hits)
    hist[code] = f.reset_index(drop=True)
del raw
print("载入 %d 只，修正跳变 %d 根" % (len(hist), nfix))

m = bt1.build_matrices(hist, start="2021-01-01", end="2026-10-20")
del hist
print("矩阵就绪：%d 天 × %d 只" % m["close"].shape)


def show(name, **kw):
    r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True, **kw)
    p = bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])
    wr = p["win_rate"] * 100 if np.isfinite(p["win_rate"]) else float("nan")
    print("  %-28s %8.2f%% %8.2f%% %7.2f %7.2f %7.1f%% %5d"
          % (name, p["cagr"] * 100, p["max_dd"] * 100, p["calmar"],
             p["sharpe"], wr, p["trades"]), flush=True)


print("\n  %-28s %9s %9s %8s %8s %8s %5s" % ("", "年化", "回撤", "Calmar", "夏普", "胜率", "交易"))
show("stop=-15% 无保护（原包）", stop_loss=0.15)
for sl in (0.06, 0.08, 0.10):
    show("纯止损 stop=-%.0f%%" % (sl * 100), stop_loss=sl)
show("trail8+be3（线上当前）", stop_loss=0.15, trail=0.08, be_stop=0.03)
show("stop=-8%+be3", stop_loss=0.08, be_stop=0.03)
