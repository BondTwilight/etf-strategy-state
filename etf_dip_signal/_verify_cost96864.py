# -*- coding: utf-8 -*-
"""_verify_cost96864.py"""
import os
import sys

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)
import _p5_bank as p5

p5.DATA = os.path.join(BASE, "data", "all_etf_1120.parquet")
END = "2026-11-20"


def stat(eq):
    eq = pd.Series(eq).dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100, (eq / eq.cummax() - 1).min() * 100


p56 = p5.load_pair("2024-06-28", END)
sub = p56.loc["2024-10-01":END]
print("96864 成本阶梯（2024-10 起）")
for c5, s4, tag in [(0, 0, "零成本"), (5, 10, "现行 万0.5+0.1%"),
                    (10, 20, "万1+0.2%"), (10, 30, "万1+0.3%（3tick）"),
                    (10, 50, "万1+0.5%")]:
    r = p5.run(sub, comm5=c5, slip4=s4)
    c, d = stat(r["equity"])
    print("  %-20s 年化 %+7.2f%% ｜ 回撤 %7.2f%%" % (tag, c, d))
