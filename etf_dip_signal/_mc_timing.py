# -*- coding: utf-8 -*-
"""蒙特卡洛：把「信号价 = 收盘价」换成「信号价 = 收盘价×(1+ε)」
ε ~ N(实测均值, 实测标准差)，看年化/回撤的离散度。
若离散度 ≥ 3.8pp，则聚宽 A/B 的 3.83pp 无法与噪声区分。
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

N_SEED = 20
BASE_SLIP = 0.002          # 与聚宽同口径
FINAL = dict(trail=0.08, be_stop=0.03, cash_yield=0.025, slippage=BASE_SLIP)

# ---- 读实测分布 ----
cal = pd.read_csv("data/minute_calib.csv")
MU = float(cal["r50"].mean())          # 14:50 相对收盘的均值
SD = float(cal["r50"].std())           # 14:50 相对收盘的 std
print("实测 14:50 相对收盘：均值 %+.4f%%  标准差 %.4f%%  （n=%d）"
      % (MU * 100, SD * 100, len(cal)), flush=True)

d = json.load(open("data/fixed_pool.json", encoding="utf-8"))
BMAP = {str(k): int(v) for k, v in d["bmap"].items()}

raw = pd.read_parquet("data/etf_qfq_cifang.parquet",
                      columns=["code", "date", "open", "close", "low"])
raw["date"] = raw["date"].astype(str).str[:10]
base_hist = {}
for code, g in raw.groupby("code", sort=False):
    f, _ = data_quality.repair_prices(g[["date", "open", "close", "low"]])
    base_hist[code] = f.reset_index(drop=True)
del raw
print("载入 %d 只" % len(base_hist), flush=True)


def run_once(m):
    r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True, **FINAL)
    p = bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])
    return p["cagr"] * 100, p["max_dd"] * 100, p["trades"]


t0 = time.time()
m0 = bt1.build_matrices(base_hist, start="2021-01-01", end="2026-10-20")
c0, dd0, n0 = run_once(m0)
print("\n基准（ε=0，即收盘价成交）：年化 %.2f%%  回撤 %.2f%%  %d 笔  (%.0fs)"
      % (c0, dd0, n0, time.time() - t0), flush=True)
del m0

cagrs, dds, ntr = [], [], []
for seed in range(N_SEED):
    rng = np.random.default_rng(1000 + seed)
    h = {}
    for code, g in base_hist.items():
        gg = g.copy()
        eps = 1.0 + rng.normal(MU, SD, len(gg))
        for col in ("open", "close", "low"):
            gg[col] = gg[col] * eps
        h[code] = gg
    m = bt1.build_matrices(h, start="2021-01-01", end="2026-10-20")
    c, dd, n = run_once(m)
    cagrs.append(c)
    dds.append(dd)
    ntr.append(n)
    print("  seed %2d：年化 %6.2f%%  回撤 %6.2f%%  %d 笔   (%.0fs)"
          % (seed, c, dd, n, time.time() - t0), flush=True)
    del m, h

a = np.array(cagrs)
b = np.array(dds)
print("\n" + "=" * 72)
print("蒙特卡洛结果（%d 次，ε ~ N(%+.4f%%, %.4f%%)）" % (N_SEED, MU * 100, SD * 100))
print("=" * 72)
print("  年化：均值 %.2f%%  中位 %.2f%%  标准差 %.2fpp  最小 %.2f%%  最大 %.2f%%"
      % (a.mean(), np.median(a), a.std(ddof=1), a.min(), a.max()))
print("  ｜年化−基准｜ 中位 %.2fpp ｜ 90%% 分位 %.2fpp" % (np.median(np.abs(a - c0)),
                                                    np.quantile(np.abs(a - c0), 0.9)))
print("  回撤：均值 %.2f%%  标准差 %.2fpp  最差 %.2f%%" % (b.mean(), b.std(ddof=1), b.min()))
print("  交易笔数：%d ~ %d（基准 %d）" % (min(ntr), max(ntr), n0))
print("\n  → 聚宽 A/B 观测到的差异是 3.83pp；")
print("     本蒙特卡洛一个标准差的宽度是 %.2fpp。" % a.std(ddof=1))
verdict = "属于噪声范围" if a.std(ddof=1) * 2 >= 3.83 else "明显大于噪声，可能是真实效应"
print("     2σ = %.2fpp ⇒ 3.83pp %s" % (a.std(ddof=1) * 2, verdict))
