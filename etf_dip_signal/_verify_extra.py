# -*- coding: utf-8 -*-
"""_verify_extra.py —— 补测 96864 关银行腿 / 96863 成本阶梯"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import _p4_band as pb
import _p5_bank as p5

DATA = os.path.join(BASE, "data", "all_etf_1120.parquet")
END = "2026-11-20"
CASH0 = 100000.0
pb.DATA = DATA
p5.DATA = DATA
CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]


def stat(eq):
    eq = pd.Series(eq).dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    return cagr * 100, dd * 100


print("【96864】2024-10 起，拆件")
p56 = p5.load_pair("2024-06-28", END)
sub = p56.loc["2024-10-01":END]
for kw, tag in [({}, "完整"),
                ({"use_stop": False}, "关双止损"),
                ({"use_default": False}, "关银行腿"),
                ({"use_ma": False}, "关MA过滤"),
                ({"min4": 1}, "斜率下限降到0")]:
    try:
        r = p5.run(sub, **kw)
        c, d = stat(r["equity"])
        print("  %-14s 年化 %+7.2f%% ｜ 回撤 %7.2f%%" % (tag, c, d))
    except Exception as e:
        print("  %-14s ERR %r" % (tag, e))

print("\n【96863】6 只池，成本阶梯（2021 起）")
codes, bmap = pb.load_pool_codes()
hist, p_all, _ = pb.load_all(set(codes) | set(CONSUME))
px = p_all[CONSUME].loc["2021-01-04":END]
for cm, sl, tag in [(0.0, 0.0, "零成本"), (0.00025, 0.001, "现行 万2.5+0.1%"),
                    (0.00025, 0.002, "2tick 0.2%"), (0.00025, 0.003, "3tick 0.3%"),
                    (0.00025, 0.005, "5tick 0.5%")]:
    r = pb.run_band(px, comm=cm, slip=sl)
    c, d = stat(r["equity"])
    print("  %-18s 年化 %+7.2f%% ｜ 回撤 %7.2f%%" % (tag, c, d))

print("\n【96863】2020 起（平台对照口径）")
px2 = p_all[CONSUME].loc["2020-01-01":END]
r = pb.run_band(px2)
c, d = stat(r["equity"])
print("  年化 %+7.2f%% ｜ 回撤 %7.2f%%" % (c, d))
