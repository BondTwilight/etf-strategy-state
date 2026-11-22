# -*- coding: utf-8 -*-
"""P1 正式版：信号深度闸门 min_depth 的净值对照（现金腿）"""
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


def perf(eq, trades):
    eq = eq.dropna(); ret = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    sharpe = ret.mean() / ret.std() * np.sqrt(252)
    s = trades[trades.action == "sell"] if len(trades) else pd.DataFrame()
    return dict(cagr=cagr, mdd=mdd, sharpe=sharpe, calmar=cagr / abs(mdd),
                n=len(s), win=(s.ret > 0).mean() if len(s) else np.nan,
                avg=s.ret.mean() if len(s) else np.nan)


for start in ["2018-01-01", "2020-01-01"]:
    m = bt.build_matrices(hist, start=start, end="2026-11-19")
    print("\n" + "=" * 90)
    print("窗口 %s ~ 2026-11-19 ｜ 起点在世 %d ｜ 期内 %d" % (
        start, int(np.isfinite(m["close"][0]).sum()),
        int(np.isfinite(m["close"]).any(axis=0).sum())))
    print("=" * 90)
    print("%-12s %9s %9s %8s %8s %7s %7s %8s" % (
        "min_depth", "年化", "回撤", "夏普", "卡玛", "交易", "胜率", "均值"))
    for md in [0, 0.5, 1.0, 2.0, 3.0, 4.0]:
        r = bm.run(m, bmap, max_hold=1, intraday_stop=True, exec_mode="close",
                   cash0=100000.0, min_depth=md)
        p = perf(r["equity"], r["trades"])
        print("%-12s %+8.2f%% %8.2f%% %8.2f %8.2f %7d %6.1f%% %+7.2f%%" % (
            ("基线" if md == 0 else ">=%.1fpp" % md), p["cagr"] * 100, p["mdd"] * 100,
            p["sharpe"], p["calmar"], p["n"], p["win"] * 100, p["avg"] * 100))
