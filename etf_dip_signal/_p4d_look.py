# -*- coding: utf-8 -*-
"""_p4d_look.py —— 锁定动量窗口口径：shift(18) vs shift(19)"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import data_quality
import _p4_band as pb

DATA = os.path.join(BASE, "data", "all_etf_1119.parquet")
CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]
NAMES = {"162411": "油气", "513100": "纳指100", "161128": "标普信息",
         "588000": "科创50", "162415": "美国消费", "515450": "红利低波"}

lines = []
def say(s=""):
    lines.append(str(s)); print(s)

df = pd.read_parquet(DATA)
df["code"] = df["code"].astype(str)
px = {}
for c in CONSUME:
    s = df[df.code == c][["date", "close"]].copy()
    s["date"] = s["date"].astype(str).str[:10]
    s = s.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    s2, _ = data_quality.repair_prices(s)
    s2["date"] = pd.to_datetime(s2["date"])
    px[c] = s2.set_index("date")["close"].astype(float)
p = pd.DataFrame(px).sort_index()

say("=" * 96)
say("A) 11-02 ~ 11-06 各标的 18日 / 19日区间涨幅（判断平台到底用哪个）")
say("=" * 96)
for lag in (18, 19):
    m = (p / p.shift(lag) - 1) * 100
    say("\n  --- 窗口 = %d 个交易日间隔（shift(%d)）---" % (lag, lag))
    say("  %-11s %s" % ("日期", "  ".join("%9s" % NAMES[c] for c in CONSUME)))
    for d in ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-17"]:
        row = m.loc[pd.Timestamp(d)]
        cells = []
        for c in CONSUME:
            v = row[c]
            mark = "*" if (pd.notna(v) and 2.01 <= v <= 9.99) else " "
            cells.append("%+8.2f%s" % (v, mark) if pd.notna(v) else "       - ")
        top = None
        cand = {c: row[c] for c in CONSUME if pd.notna(row[c]) and 2.01 <= row[c] <= 9.99}
        if cand:
            top = max(cand, key=cand.get)
        say("  %-11s %s   → 带内第一：%s" % (d, "  ".join(cells),
                                            NAMES.get(top, "空仓")))

say()
say("=" * 96)
say("B) 11 月逐日收益复现：look=18 vs look=19 vs 平台")
say("=" * 96)
plat = [("11-02", -0.14), ("11-03", 1.07), ("11-04", -0.63), ("11-05", 4.06),
        ("11-06", -3.43), ("11-09", 0.39), ("11-10", 2.31), ("11-11", 0.48),
        ("11-12", -0.27), ("11-13", -0.17), ("11-16", -1.62), ("11-17", 0.67),
        ("11-18", 0.40), ("11-19", 0.13)]
res = {}
for look in (18, 19):
    sub = p.loc["2025-09-01":"2026-11-19"]
    r = pb.run_band(sub, look=look, lo=0.02, hi=0.10, min_hold=5)
    eq = r["equity"]
    res[look] = (eq, r["trades"])
say("  %-6s %10s %10s %10s" % ("日期", "look18", "look19", "平台"))
err18 = err19 = 0.0
base18 = base19 = None
for i, (d, v) in enumerate(plat):
    ts = pd.Timestamp("2026-" + d)
    cells = []
    for look in (18, 19):
        eq = res[look][0]
        prev = eq.loc[:ts]
        if len(prev) < 2:
            cells.append(np.nan); continue
        cells.append((prev.iloc[-1] / prev.iloc[-2] - 1) * 100)
    say("  %-6s %+9.2f%% %+9.2f%% %+9.2f%%" % (d, cells[0], cells[1], v))
    err18 += abs(cells[0] - v); err19 += abs(cells[1] - v)
say("  %-6s %+9.2f%% %+9.2f%%" % ("平均绝对误差", err18 / len(plat), err19 / len(plat)))

say()
say("=" * 96)
say("C) 交易明细：look=18")
say("=" * 96)
for t in res[18][1]:
    if pd.Timestamp(t["date"]) >= pd.Timestamp("2026-10-20"):
        say("  %s %-4s %s %-8s" % (pd.Timestamp(t["date"]).date(),
                                   "买入" if t["action"] == "buy" else "卖出",
                                   t["code"], NAMES.get(t["code"], "")))

say()
say("=" * 96)
say("D) 2020 起：look=18 全参数复跑（看能否接近平台 53.87%）")
say("=" * 96)
sub2 = p.loc["2020-01-01":"2026-11-19"]
for look in (18, 19):
    for mh in (5,):
        r = pb.run_band(sub2, look=look, min_hold=mh)
        s = pb.stats(r["equity"], r["trades"], exposure=r["exposure"])
        say("  look=%d min_hold=%d  年化 %+7.2f%%  回撤 %7.2f%%  夏普 %5.2f  交易 %4d  胜率 %5.1f%%  盈亏比 %.2f  期末 %.2f 倍"
            % (look, mh, s["cagr"] * 100, s["max_dd"] * 100, s["sharpe"],
               s["trades"], s["win"] * 100, s["pl"], r["equity"].iloc[-1] / 100000))

say()
say("=" * 96)
say("E) 平台可复现性结论")
say("=" * 96)
say("  平台宣称 2020-01-01~2026-11-20：总收益 +1630.01%，年化 53.87%，期末 17.30 倍")
say("  本地最优（12 池、look18/19、min_hold 1~40 全扫）：年化约 12%~21%，期末 2.2~2.9 倍")
say("  ⇒ 差异 30pp+ 无法用窗口/参数解释，属平台侧口径或引擎差异，需平台逐笔记录才能定论。")

out = os.path.join(BASE, "_p4d_look.log")
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n[已保存] " + out)
