# -*- coding: utf-8 -*-
"""同主题同步性过滤：候选的「超额跌幅」是情绪冲击还是个体事件？

excess = 候选近 5 日收益 − 全池中位数近 5 日收益
  excess 很小（≈0） ⇒ 全池一起跌，是系统性冲击 → 按理论更该反转
  excess 很负      ⇒ 只有它跌，是个体/主题事件 → 未必反转

测试两个方向：
  A) 只买「跌幅不显著超过全池」的（excess >= min）  → 避开个体崩盘
  B) 只买「显著弱于全池」的（excess <= max）        → 专挑独立超跌
主窗口 + 长窗口双验证，判据：同向、且改善 > 2σ(≈7pp 回撤 / 4pp 年化)。
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

BASE = dict(trail=0.08, be_stop=0.03, cash_yield=0.025, slippage=0.002)

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
print("载入 %d 只" % len(hist), flush=True)

M = {
    "主 2021": bt1.build_matrices(hist, start="2021-01-01", end="2026-10-20"),
    "长 2016": bt1.build_matrices(hist, start="2016-01-01", end="2026-10-20"),
}


def show(tag, **kw):
    outs = []
    for wname, m in M.items():
        r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode="close",
                   timeout_live=True, **BASE, **kw)
        p = bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])
        outs.append((p["cagr"] * 100, p["max_dd"] * 100, p["trades"]))
    print("  %-26s 主 %6.2f%%/%7.2f%%/%2d笔 ｜ 长 %6.2f%%/%7.2f%%/%2d笔"
          % (tag, outs[0][0], outs[0][1], outs[0][2],
             outs[1][0], outs[1][1], outs[1][2]), flush=True)
    return outs


print("\n" + "=" * 108)
print("A) 只买「跌幅没有显著超过全池」的候选（剔除个体崩盘）")
print("=" * 108)
show("不过滤（现状）")
for x in (-0.10, -0.07, -0.05, -0.03, 0.0):
    show("excess >= %+.0f%%" % (x * 100), excess_min=x)

print("\n" + "=" * 108)
print("B) 反向：只买「显著弱于全池」的候选（专挑独立超跌）")
print("=" * 108)
for x in (-0.03, -0.05, -0.08):
    show("excess <= %+.0f%%" % (x * 100), excess_max=x)
