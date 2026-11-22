# -*- coding: utf-8 -*-
"""穷举参数的后果：前段挑最优 → 后段检验

设计：
  拟合段 2021-01-01 ~ 2023-12-31（3 年）
  检验段 2024-01-01 ~ 2026-10-20（2.8 年，拟合时完全没看过）
  网格：trail 8 档 × be_stop 4 档 = 32 组
若"穷举找最优"有效，则拟合段最优那组在检验段也应靠前。
若无效，则拟合段最优在检验段会掉到中下游 —— 这就是过拟合的直接证据。
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

BASE = dict(cash_yield=0.025, slippage=0.002)

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

# 拟合段要多取 60 根做 warmup，所以从 2020-10 起算矩阵，再切片
M_FIT = bt1.build_matrices(hist, start="2020-11-01", end="2023-12-31")
M_TST = bt1.build_matrices(hist, start="2023-11-01", end="2026-10-20")
print("矩阵：拟合 %s ｜ 检验 %s" % (M_FIT["close"].shape, M_TST["close"].shape), flush=True)


def one(m, trail, be):
    kw = dict(BASE, trail=trail)
    if be is not None:
        kw["be_stop"] = be
    r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True, **kw)
    p = bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])
    return p["cagr"] * 100, p["max_dd"] * 100, p["trades"]


rows = []
t0 = time.time()
for tr in (0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.12):
    for be in (None, 0.02, 0.03, 0.05):
        cf, df_, nf = one(M_FIT, tr, be)
        ct, dt_, nt = one(M_TST, tr, be)
        rows.append((tr, be, cf, df_, nf, ct, dt_, nt))
        print("  trail %.0f%% / be %-4s  拟合 %6.2f%% %7.2f%% %2d笔 ｜ 检验 %6.2f%% %7.2f%% %2d笔  (%.0fs)"
              % (tr * 100, ("关闭" if be is None else "%.0f%%" % (be * 100)),
                 cf, df_, nf, ct, dt_, nt, time.time() - t0), flush=True)

df = pd.DataFrame(rows, columns=["trail", "be", "cagr_fit", "dd_fit", "n_fit",
                                 "cagr_tst", "dd_tst", "n_tst"])
df.to_csv("回测输出/walkforward_grid.csv", index=False, encoding="utf-8-sig")

print("\n" + "=" * 96)
print("按「拟合段年化」排序 Top 6 —— 这就是穷举会选出来的参数")
print("=" * 96)
top = df.sort_values("cagr_fit", ascending=False).head(6)
print("  %-8s %-6s %10s %10s  %10s %10s  %s"
      % ("trail", "be", "拟合年化", "拟合回撤", "检验年化", "检验回撤", "检验排名"))
for i, r in top.iterrows():
    rank = int(df["cagr_tst"].rank(ascending=False)[i])
    print("  %-8.0f %-6s %9.2f%% %9.2f%%  %9.2f%% %9.2f%%  %d/%d"
          % (r.trail * 100, ("关闭" if pd.isna(r.be) else "%.0f%%" % (r.be * 100)),
             r.cagr_fit, r.dd_fit, r.cagr_tst, r.dd_tst, rank, len(df)))

cur = df[(df.trail == 0.08) & (df.be == 0.03)].iloc[0]
print("\n  当前线上参数（trail 8%% / be 3%%）：拟合 %6.2f%% ｜ 检验 %6.2f%%（检验第 %d/%d 名）"
      % (cur.cagr_fit, cur.cagr_tst, int(df["cagr_tst"].rank(ascending=False)[
          df.index[(df.trail == 0.08) & (df.be == 0.03)][0]]), len(df)))

print("\n" + "=" * 96)
print("统计")
print("=" * 96)
print("  拟合段年化：均值 %.2f%%  标准差 %.2fpp  最好 %.2f%%  最差 %.2f%%"
      % (df.cagr_fit.mean(), df.cagr_fit.std(), df.cagr_fit.max(), df.cagr_fit.min()))
print("  检验段年化：均值 %.2f%%  标准差 %.2fpp  最好 %.2f%%  最差 %.2f%%"
      % (df.cagr_tst.mean(), df.cagr_tst.std(), df.cagr_tst.max(), df.cagr_tst.min()))
ic = np.corrcoef(df.cagr_fit, df.cagr_tst)[0, 1]
print("  拟合段与检验段年化的相关系数 r = %.3f" % ic)
print("  → r 接近 0 或为负，说明「拟合段最优」对「检验段」没有预测力")
