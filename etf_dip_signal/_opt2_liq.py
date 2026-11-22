# -*- coding: utf-8 -*-
"""优化候选：流动性闸门（近20日日均成交额）
经济含义：只买盘口够厚的标的，直接对冲「滑点被低估」这一最大风险。
必须验证的是：它改善的是成本，还是仅仅又一次参数挖掘。
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

BASE = dict(trail=0.08, be_stop=0.03, cash_yield=0.025,
            slippage=0.0005, tick_frac=0.5)

d = json.load(open("data/fixed_pool.json", encoding="utf-8"))
BMAP = {str(k): int(v) for k, v in d["bmap"].items()}

raw = pd.read_parquet("data/etf_qfq_cifang.parquet",
                      columns=["code", "date", "open", "close", "low", "amount"])
raw["date"] = raw["date"].astype(str).str[:10]
hist, amt = {}, {}
for code, g in raw.groupby("code", sort=False):
    f, _ = data_quality.repair_prices(g[["date", "open", "close", "low"]])
    hist[code] = f.reset_index(drop=True)
    amt[code] = pd.Series(g["amount"].to_numpy(dtype=float),
                          index=g["date"].to_numpy())
del raw

m = bt1.build_matrices(hist, start="2021-01-01", end="2026-10-20")
dates = [str(x)[:10] for x in m["dates"]]
codes = m["codes"]

ADF = pd.DataFrame({c: amt[c].reindex(dates) for c in codes})
ADV20 = ADF.rolling(20, min_periods=10).mean().shift(1)   # 只用 t-1 及之前
print("ADV 矩阵 %s ｜ 有效值占比 %.1f%%"
      % (ADV20.shape, 100 * ADV20.notna().mean().mean()), flush=True)


def show(name, liq=None, **kw):
    r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True, liq=liq, **kw)
    p = bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])
    wr = p["win_rate"] * 100 if np.isfinite(p["win_rate"]) else float("nan")
    print("  %-34s %8.2f%% %8.2f%% %6.2f %6.2f %6.1f%% %4d"
          % (name, p["cagr"] * 100, p["max_dd"] * 100, p["calmar"],
             p["sharpe"], wr, p["trades"]), flush=True)
    return p


print("\n" + "=" * 96)
print("流动性闸门（近20日日均成交额，只用 t-1 及之前数据）")
print("=" * 96)
print("  %-34s %9s %9s %6s %6s %7s %4s" % ("", "年化", "回撤", "Calmar", "夏普", "胜率", "笔"))
base = show("无闸门（现状）", **BASE)
for th in (0.1, 0.3, 0.5, 1.0):
    liq = (ADV20.to_numpy() >= th * 1e8)
    show("ADV ≥ %.0f 千万" % th, liq=liq, **BASE)

print("\n【补充】闸门在不同滑点下的表现（看它是否只在低成本假设下才显得好）")
for slip in (0.001, 0.0025):
    print("  滑点 %.2f%%：" % (slip * 100))
    show("    无闸门", slippage=slip, tick_frac=0.5, trail=0.08, be_stop=0.03,
         cash_yield=0.025)
    liq = (ADV20.to_numpy() >= 0.3 * 1e8)
    show("    ADV ≥ 3 千万", liq=liq, slippage=slip, tick_frac=0.5, trail=0.08,
         be_stop=0.03, cash_yield=0.025)
