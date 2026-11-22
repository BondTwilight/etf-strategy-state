# -*- coding: utf-8 -*-
"""_verify_all.py —— 一次性核准看板上所有要引用的数字（新库 all_etf_1120）

原则：看板里出现的每个数字，都必须在这个脚本里有对应输出。
凡是本脚本没有输出的历史数字，一律不能写进看板。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import bt_etf_dip as bt
import bt_multi as bm
import data_quality
import _p4_band as pb
import _p5_bank as p5
import _p6_momo as m6

DATA = os.path.join(BASE, "data", "all_etf_1120.parquet")
END = "2026-11-20"
CASH0 = 100000.0
pb.DATA = DATA
p5.DATA = DATA
m6.DATA = DATA
CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]


def stat(eq, trades):
    eq = pd.Series(eq).dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    dr = eq.pct_change().dropna()
    vol = dr.std() * np.sqrt(252)
    sh = dr.mean() * 252 / vol if vol > 0 else np.nan
    t = trades if isinstance(trades, pd.DataFrame) else pd.DataFrame()
    if isinstance(trades, list) and trades:
        try:
            t = pd.DataFrame(trades)
        except Exception:
            t = pd.DataFrame()
    closed = t[t["action"] != "buy"] if len(t) and "action" in t.columns else pd.DataFrame()
    n = len(closed)
    win = float((closed["ret"] > 0).mean()) if n else np.nan
    return dict(cagr=cagr * 100, dd=dd * 100, sh=sh, n=n, win=win,
                calmar=cagr / abs(dd) if dd < 0 else np.nan,
                final=eq.iloc[-1] / CASH0)


print("=" * 96)
print("【1】线C 乖离抄底 · 多起点 + 成本阶梯")
print("=" * 96)
codes, bmap = pb.load_pool_codes()
hist, p_all, fixed = pb.load_all(set(codes) | set(CONSUME) | set(m6.CODES))
h381 = {c: hist[c] for c in codes if c in hist}
mC = bt.build_matrices(h381, start="2021-01-04", end=END)
LC = {}
for s in ["2021-01-04", "2022-01-01", "2023-01-01"]:
    mm = bt.build_matrices(h381, start=s, end=END)
    r = bm.run(mm, bmap, max_hold=1, intraday_stop=True, exec_mode="close", timeout_live=True)
    st = stat(r["equity"], r["trades"])
    LC[s] = st
    print("  %s 起：年化 %+7.2f%% ｜ 回撤 %7.2f%% ｜ 夏普 %.2f ｜ 卡玛 %.2f ｜ 平仓 %3d ｜ 胜率 %5.1f%%"
          % (s, st["cagr"], st["dd"], st["sh"], st["calmar"], st["n"], st["win"] * 100))
print("\n  成本阶梯（2021 起）：")
for slip, tag in [(0.0, "零成本"), (0.001, "现行 0.1%"), (0.002, "2tick 0.2%"),
                  (0.003, "3tick 0.3%"), (0.005, "5tick 0.5%")]:
    r = bm.run(mC, bmap, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True, slippage=slip)
    st = stat(r["equity"], r["trades"])
    print("     %-14s 年化 %+7.2f%% ｜ 回撤 %7.2f%%" % (tag, st["cagr"], st["dd"]))
print("  关掉盘中止损（2021 起，slip 0.1%）：")
r = bm.run(mC, bmap, max_hold=1, intraday_stop=False, exec_mode="close", timeout_live=True)
st = stat(r["equity"], r["trades"])
print("     %-14s 年化 %+7.2f%% ｜ 回撤 %7.2f%% ｜ 卡玛 %.2f"
      % ("无盘中止损", st["cagr"], st["dd"], st["calmar"]))

print("\n" + "=" * 96)
print("【2】momo 原版 96865 · 多起点")
print("=" * 96)
pm = m6.load_px("2015-01-05", END)
V1, V2 = m6.build_signals(pm, 20, 26)
MOMO = {}
for s in ["2018-01-01", "2020-01-01", "2022-01-01", "2023-01-01", "2024-01-01"]:
    i0 = int(np.where(pm.index >= s)[0][0])
    sub = pm.loc[s:END]
    r = m6.run(sub, V1[i0:], V2[i0:])
    st = stat(r["equity"], r["trades"])
    MOMO[s] = st
    print("  %s 起：年化 %+7.2f%% ｜ 回撤 %7.2f%% ｜ 夏普 %.2f ｜ 平仓 %3d ｜ 期末 %.2f×"
          % (s, st["cagr"], st["dd"], st["sh"], st["n"], st["final"]))
print("  成本 3tick（0.3% 滑点，2018 起）：")
i0 = int(np.where(pm.index >= "2018-01-01")[0][0])
r = m6.run(pm.loc["2018-01-01":END], V1[i0:], V2[i0:], slip4=30)
st = stat(r["equity"], r["trades"])
print("     年化 %+7.2f%% ｜ 回撤 %7.2f%% ｜ 平仓 %3d" % (st["cagr"], st["dd"], st["n"]))
print("  零成本（2018 起）：")
r = m6.run(pm.loc["2018-01-01":END], V1[i0:], V2[i0:], slip4=0)
st = stat(r["equity"], r["trades"])
print("     年化 %+7.2f%% ｜ 回撤 %7.2f%%" % (st["cagr"], st["dd"]))

print("\n" + "=" * 96)
print("【3】消费轮动 96863 · 多起点")
print("=" * 96)
B12 = {}
for s in ["2020-01-01", "2021-01-04", "2022-01-01"]:
    r = pb.run_band(p_all[CONSUME].loc[s:END])
    st = stat(r["equity"], r["trades"])
    B12[s] = st
    print("  %s 起：年化 %+7.2f%% ｜ 回撤 %7.2f%% ｜ 夏普 %.2f ｜ 平仓 %3d"
          % (s, st["cagr"], st["dd"], st["sh"], st["n"]))

print("\n" + "=" * 96)
print("【4】等股灾 96864 · 五起点 + 拆件")
print("=" * 96)
p56 = p5.load_pair("2024-06-28", END)
for s in ["2024-10-01", "2025-01-01", "2025-04-01", "2025-07-01", "2026-01-01"]:
    sub = p56.loc[s:END]
    r = p5.run(sub)
    st = stat(r["equity"], r["trades"])
    print("  %s 起：年化 %+7.2f%% ｜ 回撤 %7.2f%% ｜ 夏普 %.2f ｜ 平仓 %3d"
          % (s, st["cagr"], st["dd"], st["sh"], st["n"]))
sub = p56.loc["2024-10-01":END]
print("  基准 2024-10 起：")
for kw, tag in [({}, "完整"), ({"use_stop": False}, "关双止损"),
                ({"use_bank": False}, "关银行腿")]:
    try:
        r = p5.run(sub, **kw)
        st = stat(r["equity"], r["trades"])
        print("     %-10s 年化 %+7.2f%% ｜ 回撤 %7.2f%%" % (tag, st["cagr"], st["dd"]))
    except TypeError:
        print("     %-10s 参数不支持，跳过" % tag)
main56 = sub["main"] / sub["main"].iloc[0] * CASH0
st = stat(main56, None)
print("     159552 买入持有 年化 %+7.2f%% ｜ 回撤 %7.2f%%" % (st["cagr"], st["dd"]))

print("\n" + "=" * 96)
print("【5】基准")
print("=" * 96)
for c, n in [("510300", "沪深300"), ("510500", "中证500"), ("510880", "红利低波")]:
    s = p_all[c].loc["2021-01-04":END].dropna()
    st = stat(s / s.iloc[0] * CASH0, None)
    print("  %s %-8s 2021 起：年化 %+6.2f%% ｜ 回撤 %7.2f%%" % (c, n, st["cagr"], st["dd"]))
