# -*- coding: utf-8 -*-
"""优化扫描：诚实成本基线 / 保护位滞后 / trail 平台 / 低价标的剔除

结论用途：决定线上三个开关
  ① 滑点按 tick 建模（不再用统一 0.1%）
  ② 保护位用「已确认收盘价」还是「当日快照」
  ③ trail 取 8% 还是 9~10%
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

BASE_SLIP = 0.0005          # 5bp 基础滑点（冲击成本）
T0 = time.time()
FINAL = dict(trail=0.08, be_stop=0.03, cash_yield=0.025)

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
print("载入 %d 只，修正跳变 %d 根" % (len(hist), nfix), flush=True)

m = bt1.build_matrices(hist, start="2021-01-01", end="2026-10-20")


def show(name, mm=None, **kw):
    mm = mm if mm is not None else m
    r = bt.run(mm, BMAP, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True, **kw)
    p = bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])
    wr = p["win_rate"] * 100 if np.isfinite(p["win_rate"]) else float("nan")
    print("  %-40s %8.2f%% %8.2f%% %6.2f %6.2f %6.1f%% %4d"
          % (name, p["cagr"] * 100, p["max_dd"] * 100, p["calmar"],
             p["sharpe"], wr, p["trades"]), flush=True)
    return p


print("\n" + "=" * 108)
print("A. 诚实成本基线（trail8 + be3 + 计息2.5）")
print("=" * 108)
print("  %-40s %9s %9s %6s %6s %7s %4s" % ("", "年化", "回撤", "Calmar", "夏普", "胜率", "笔"))
show("① 统一滑点 0.10%（旧口径，偏乐观）", **FINAL, slippage=0.001)
show("② 统一滑点 0.25%（报告建议口径）", **FINAL, slippage=0.0025)
show("③ 半个 tick 建模（base 5bp）", **FINAL, slippage=BASE_SLIP, tick_frac=0.5)
show("④ 一个 tick 建模（base 5bp）", **FINAL, slippage=BASE_SLIP, tick_frac=1.0)
show("⑤ 一个 tick + 基础 10bp", **FINAL, slippage=0.001, tick_frac=1.0)

print("\n" + "=" * 108)
print("B. 保护位「收盘确认」的滞后代价（protect_lag=1：用前一交易日收盘判定）")
print("=" * 108)
show("⑥ trail8 当日确认（现状）·tick0.5", **FINAL, slippage=BASE_SLIP, tick_frac=0.5)
show("⑦ trail8 滞后一日确认 ·tick0.5", **FINAL, slippage=BASE_SLIP, tick_frac=0.5, protect_lag=1)
show("⑧ trail8 滞后一日确认 ·滑点0.25%", **FINAL, slippage=0.0025, protect_lag=1)

print("\n" + "=" * 108)
print("C. trail 平台复扫（tick0.5 建模，be3 + 计息2.5）")
print("=" * 108)
for tv in [0.08, 0.085, 0.09, 0.095, 0.10, 0.11, 0.12]:
    show("trail=%.1f%%" % (tv * 100), trail=tv, be_stop=0.03, cash_yield=0.025,
         slippage=BASE_SLIP, tick_frac=0.5)

print("\n" + "=" * 108)
print("D. 剔除低价标的（中位收盘价 < 0.5 元，tick 成本 > 0.2%）")
print("=" * 108)
px = m["close"]
med = np.nanmedian(px, axis=0)
codes = m["codes"]
keep = [c for c, v in zip(codes, med) if np.isfinite(v) and v >= 0.5]
drop = [c for c, v in zip(codes, med) if np.isfinite(v) and v < 0.5]
print("  全池 %d 只 → 保留 %d、剔除 %d（%s）"
      % (len(codes), len(keep), len(drop), ",".join(drop[:12])), flush=True)
m2 = bt1.build_matrices({c: hist[c] for c in keep}, start="2021-01-01", end="2026-10-20")
show("全池 trail9 ·tick0.5", trail=0.09, be_stop=0.03, cash_yield=0.025,
     slippage=BASE_SLIP, tick_frac=0.5)
show("剔除低价后 trail9 ·tick0.5", mm=m2, trail=0.09, be_stop=0.03, cash_yield=0.025,
     slippage=BASE_SLIP, tick_frac=0.5)

print("\n完成 %.0fs" % (time.time() - T0))
