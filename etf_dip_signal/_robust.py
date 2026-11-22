# -*- coding: utf-8 -*-
"""_robust.py —— 一次算清「成本阶梯 / 五起点 / 开关拆件」，落 data/_robust.json

存在的意义：文案层（_strategies.py）里所有百分比必须来自这里，不许手写。
手写就会过期，过期就是口径错误 —— 上一版"五起点"还是收盘价口径的数字。

口径：执行时点价（线C 14:45 / momo 14:30 / 96863 14:50 / 96864 14:30），带动预热。
"""
import json
import os

import numpy as np
import pandas as pd

import _p4_band as pb
import _p5_bank as p5
import _p6_momo as m6
import _px
import bt_etf_dip as bt
import bt_multi as bm

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
END = "2026-11-20"
CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]


def cagr(eq, start=None):
    s = pd.Series(eq).dropna().astype(float)
    if start:
        s = s.loc[start:]
    if len(s) < 30:
        return None
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    return round(((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100, 2)


def mdd(eq, start=None):
    s = pd.Series(eq).dropna().astype(float)
    if start:
        s = s.loc[start:]
    return round(float((s / s.cummax() - 1).min()) * 100, 2)


out = {}

# ============================================================ 线C
print("[1/4] 线C（14:45 执行口径）…")
codes, bmap = pb.load_pool_codes()
h45 = _px.hist_1445()
use = {c: h45[c] for c in codes if c in h45}
m = bt.build_matrices(use, start="2020-06-01", end=END)

variants = {}
for tag, kw in (("zero", dict(commission=0.0, slippage=0.0)),
                ("now", dict(commission=0.0002, slippage=0.001)),
                ("t2", dict(commission=0.0002, slippage=0.002)),
                ("t3", dict(commission=0.0002, slippage=0.003)),
                ("h5", dict(commission=0.0002, slippage=0.005))):
    r = bm.run(m, bmap, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True, **kw)
    variants[tag] = cagr(r["equity"], "2021-01-04")
    print("   成本 %-5s 年化 %s%%" % (tag, variants[tag]))

starts = {}
for st in ("2021-01-04", "2022-01-04", "2023-01-03"):
    starts[st[:4]] = cagr(bm.run(m, bmap, max_hold=1, intraday_stop=True,
                                 exec_mode="close", timeout_live=True)["equity"], st)
    print("   起点 %s 年化 %s%%" % (st, starts[st[:4]]))

stop = {}
for tag, fl in (("on", True), ("off", False)):
    r = bm.run(m, bmap, max_hold=1, intraday_stop=fl, exec_mode="close",
               timeout_live=True)
    stop[tag] = cagr(r["equity"], "2021-01-04")
    print("   盘中止损 %-3s 年化 %s%% ｜ 回撤 %s%%" % (tag, stop[tag], mdd(r["equity"], "2021-01-04")))

out["lineC"] = {"cost": variants, "starts": starts, "stop": stop,
                "note": "成本档 zero/now(万2+0.1%)/t2(0.2%)/t3(0.3%)/h5(0.5%)"}

# ============================================================ momo
print("\n[2/4] momo 96865（14:30）…")
p = _px.wide("1430")[m6.CODES]
V1, V2 = m6.build_signals(p, 20, 26)
i0 = int(np.where(p.index >= "2018-01-01")[0][0])
ps, V1s, V2s = p.iloc[i0:], V1[i0:], V2[i0:]

v = {}
for tag, kw in (("zero", dict(comm5=0, slip4=0)),
                ("now", dict(comm5=10, slip4=10)),
                ("t2", dict(comm5=10, slip4=20)),
                ("t3", dict(comm5=10, slip4=30)),
                ("h5", dict(comm5=10, slip4=50))):
    v[tag] = cagr(m6.run(ps, V1s, V2s, **kw)["equity"])
    print("   成本 %-5s 年化 %s%%" % (tag, v[tag]))
st = {}
for y in (2018, 2020, 2022, 2023, 2024):
    k = int(np.where(ps.index >= "%d-01-01" % y)[0][0])
    st[str(y)] = cagr(m6.run(ps.iloc[k:], V1s[k:], V2s[k:])["equity"])
    print("   起点 %d 年化 %s%%" % (y, st[str(y)]))
out["momo96865"] = {"cost": v, "starts": st}

# ============================================================ 96863
print("\n[3/4] 96863（14:50）…")
pb_ = _px.wide("1450")[CONSUME]
v = {}
for tag, kw in (("zero", dict(comm=0.0, slip=0.0)),
                ("now", dict(comm=0.00025, slip=0.001)),
                ("t2", dict(comm=0.00025, slip=0.002)),
                ("t3", dict(comm=0.00025, slip=0.003)),
                ("h5", dict(comm=0.00025, slip=0.005))):
    v[tag] = cagr(pb.run_band(pb_.loc["2019-06-03":END], **kw)["equity"], "2020-01-01")
    print("   成本 %-5s 年化 %s%%" % (tag, v[tag]))
st = {}
for y in (2020, 2022, 2023, 2024):
    st[str(y)] = cagr(pb.run_band(pb_.loc["2019-06-03":END])["equity"], "%d-01-01" % y)
    print("   起点 %d 年化 %s%%" % (y, st[str(y)]))
out["band96863"] = {"cost": v, "starts": st}

# ============================================================ 96864
print("\n[4/4] 96864（14:30）…")
pair = _px.pair("1430")
v = {}
for tag, kw in (("zero", dict(comm5=0, slip4=0)),
                ("now", dict(comm5=5, slip4=10)),
                ("t2", dict(comm5=5, slip4=20)),
                ("t3", dict(comm5=5, slip4=30)),
                ("h5", dict(comm5=5, slip4=50))):
    v[tag] = cagr(p5.run(pair.loc["2024-06-28":END], **kw)["equity"], "2024-10-01")
    print("   成本 %-5s 年化 %s%%" % (tag, v[tag]))
st = {}
for s0 in ("2024-10-01", "2025-01-02", "2025-04-01", "2025-07-01", "2026-01-05"):
    st[s0[:7]] = cagr(p5.run(pair.loc["2024-06-28":END])["equity"], s0)
    print("   起点 %s 年化 %s%%" % (s0, st[s0[:7]]))
out["bank96864"] = {"cost": v, "starts": st}

with open(os.path.join(DATA, "_robust.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("\n写出 data/_robust.json")
