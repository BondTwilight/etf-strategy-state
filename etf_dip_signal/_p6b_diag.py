# -*- coding: utf-8 -*-
"""_p6b_diag.py —— 定位 2018 年 -99.88% 的来源"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import _p6_momo as m

lines = []
def say(s=""):
    lines.append(str(s)); print(s)

p = m.load_px()
say("=" * 96)
say("1) 各标的 2018 年价格区间与年度收益（qfq 已修跳变）")
say("=" * 96)
say("  %-8s %-10s %8s %8s %8s   %s" % ("代码", "名称", "首", "末", "年度", "min/max"))
for c in m.CODES:
    s = p[c].dropna()
    s18 = s.loc["2018-01-01":"2018-12-31"]
    if len(s18) < 2:
        say("  %-8s %-10s   （2018 无数据，起始 %s）" % (c, m.NAMES[c],
                                                    s.index[0].date() if len(s) else "-"))
        continue
    say("  %-8s %-10s %8.3f %8.3f %+7.1f%%   %.3f / %.3f"
        % (c, m.NAMES[c], s18.iloc[0], s18.iloc[-1],
           (s18.iloc[-1] / s18.iloc[0] - 1) * 100, s18.min(), s18.max()))

say()
say("=" * 96)
say("2) 2018 年 5 只在世标的的日收益极值（找异常）")
say("=" * 96)
for c in m.CODES:
    s = p[c].dropna().loc["2018-01-01":"2018-12-31"]
    if len(s) < 30:
        continue
    r = s.pct_change().dropna()
    worst = r.min()
    wd = r.idxmin()
    say("  %-8s %-10s 最大单日 %+7.2f%%（%s）｜最小单日 %+7.2f%%（%s）｜年化波动 %.1f%%"
        % (c, m.NAMES[c], r.max() * 100, r.idxmax().date(),
           worst * 100, wd.date(), r.std() * np.sqrt(252) * 100))

say()
say("=" * 96)
say("3) 逐笔交易（2018-01-01 ~ 2019-06-30）")
say("=" * 96)
p18 = p.loc["2018-01-01":"2026-11-19"]
V1, V2 = m.build_signals(p, 20, 26)
i0 = np.where(p.index >= "2018-01-01")[0][0]
r = m.run(p18, V1[i0:], V2[i0:])
for t in r["trades"]:
    if pd.Timestamp(t["date"]) <= pd.Timestamp("2019-06-30"):
        if t["action"] == "buy":
            say("  %s 买入 %-8s %8d 份 @ %.3f"
                % (pd.Timestamp(t["date"]).date(), m.NAMES.get(t["code"], t["code"]),
                   t["amount"], t["price"]))
        else:
            say("  %s 卖出 %-8s %8d 份 @ %.3f  ret=%+.2f%%"
                % (pd.Timestamp(t["date"]).date(), m.NAMES.get(t["code"], t["code"]),
                   t["amount"], t["price"], t["ret"] * 100))

say()
say("=" * 96)
say("4) 净值曲线（2018 年每月末）")
say("=" * 96)
eq = r["equity"]
for d in pd.date_range("2018-01-31", "2019-06-30", freq="ME"):
    sub = eq.loc[:d]
    if len(sub):
        say("  %s  %10.0f 元" % (d.date(), sub.iloc[-1]))

say()
say("=" * 96)
say("5) 2018-10 ~ 2018-12 明细（石油LOF 暴跌区间）")
say("=" * 96)
for c in ["162719", "159915", "518880", "513100", "513030"]:
    s = p[c].loc["2018-09-25":"2019-01-10"].dropna()
    if len(s) < 2:
        continue
    say("  %-8s %-8s %s" % (c, m.NAMES[c],
                            "  ".join("%s:%.3f" % (d.strftime("%m-%d"), v)
                                      for d, v in s.iloc[::5].items())))

out = os.path.join(BASE, "_p6b_diag.log")
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n[已保存] " + out)
