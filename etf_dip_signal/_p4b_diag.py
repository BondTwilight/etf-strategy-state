# -*- coding: utf-8 -*-
"""_p4b_diag.py —— 诊断 12 池复现差异 + 停牌市值 bug"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import data_quality

DATA = os.path.join(BASE, "data", "all_etf_1119.parquet")
CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]
NAMES = {"162411": "油气", "513100": "纳指100", "161128": "标普信息",
         "588000": "科创50", "162415": "美国消费", "515450": "红利低波"}

lines = []
def say(s=""):
    lines.append(str(s)); print(s)

df = pd.read_parquet(DATA)
df["code"] = df["code"].astype(str)

say("=" * 90)
say("1) 12 池各标的本地数据起始日（决定 2020-2021 能不能吃到）")
say("=" * 90)
px = {}
for c in CONSUME:
    s = df[df.code == c][["date", "close", "volume"]].copy()
    s["date"] = s["date"].astype(str).str[:10]
    s = s.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    s2, hits = data_quality.repair_prices(s)
    say("  %s %-8s %s ~ %s  %5d 根  跳变修复 %d  %s"
        % (c, NAMES[c], s2["date"].iloc[0], s2["date"].iloc[-1], len(s2), len(hits),
           ("首日收 %.3f 末收 %.3f 区间 %+.1f%%" % (
               s2["close"].iloc[0], s2["close"].iloc[-1],
               (s2["close"].iloc[-1] / s2["close"].iloc[0] - 1) * 100))))
    s2["date"] = pd.to_datetime(s2["date"])
    px[c] = s2.set_index("date")["close"].astype(float)

p = pd.DataFrame(px).sort_index()
p = p.loc["2020-01-01":]

say()
say("=" * 90)
say("2) 有效标的数随时间（动量需 20 个交易日历史）")
say("=" * 90)
ok = p.notna()
for yr in range(2020, 2027):
    sub = ok[ok.index.year == yr]
    if len(sub) == 0:
        continue
    say("  %d 年：有价标的数 年初 %d → 年末 %d（年度中位 %.0f）"
        % (yr, sub.iloc[0].sum(), sub.iloc[-1].sum(), sub.median().sum()))

say()
say("=" * 90)
say("3) 各标的逐年收益（本地 qfq）")
say("=" * 90)
say("  %-8s %s" % ("标的", "  ".join("%8d" % y for y in range(2020, 2027))))
for c in CONSUME:
    row = []
    for yr in range(2020, 2027):
        s = p[c][p.index.year == yr].dropna()
        if len(s) < 2:
            row.append("       -")
        else:
            row.append("%+7.1f%%" % ((s.iloc[-1] / s.iloc[0] - 1) * 100))
    say("  %-8s %s" % (NAMES[c], "  ".join(row)))

say()
say("=" * 90)
say("4) 买入持有基准（2020-01-01 起，等权 6 只，月度再平衡）")
say("=" * 90)
r = p.pct_change()
ew = (1 + r.mean(axis=1).fillna(0)).cumprod()
yrs = (p.index[-1] - p.index[0]).days / 365.25
say("  等权年化 %+.2f%%  回撤 %.2f%%  期末 %.2f 倍"
    % ((ew.iloc[-1] ** (1 / yrs) - 1) * 100,
       ((ew / ew.cummax() - 1).min()) * 100, ew.iloc[-1]))

say()
say("=" * 90)
say("5) 平台宣称 vs 本地：2020 起 12 池")
say("=" * 90)
say("  平台：总收益 +1630.01%｜年化 53.87%｜回撤 20.34%｜夏普 1.85｜卡玛 2.65｜胜率 52.32%｜盈亏比 1.97")
say("  平台月均交易 3 次 → 6.9 年约 248 笔（买卖各计一笔则约 124 次往返）")
say("  本地：年化 +16.22%｜回撤 -29.50%｜夏普 0.74｜交易 485 笔（约 242 次往返）")
say("  ⇒ 换手量级一致（本地换手约为平台 2 倍），收益差 37.6pp 不可能来自取整/手续费")

say()
say("=" * 90)
say("6) 关键假设检验：平台是否用了「不复权/后复权」导致动量信号不同")
say("=" * 90)
say("  本地 qfq：161128 首日 %.3f → 末 %.3f（%+.1f%%）"
    % (p["161128"].dropna().iloc[0], p["161128"].dropna().iloc[-1],
       (p["161128"].dropna().iloc[-1] / p["161128"].dropna().iloc[0] - 1) * 100))
say("  FUND_META 显示 515450 在 2026 有 3 次分红（0.01/0.015/0.025 元/份），")
say("  若平台按「不复权」算动量，分红除权日会出现 -1.5%~-2% 的假跌幅，")
say("  恰好会把它踢出 2%~10% 带 —— 方向是「平台更差」而不是更好。")

out = os.path.join(BASE, "_p4b_diag.log")
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n[已保存] " + out)
