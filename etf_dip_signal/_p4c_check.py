# -*- coding: utf-8 -*-
"""_p4c_check.py —— 决定性检验：新引擎能否复现 5-28 锚点后的逐笔（该段已与平台日收益对上）"""
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

say("=" * 100)
say("决定性检验 A：新引擎 vs 平台日收益（2026-11-02 ~ 2026-11-20）")
say("=" * 100)
# 用新引擎从 2025-10 起跑，让动量窗口预热，然后看 11 月
sub = p.loc["2025-09-01":"2026-11-19"]
r = pb.run_band(sub, lo=0.02, hi=0.10, look=19, min_hold=5)
eq = r["equity"]
nov = eq.loc["2026-11-02":"2026-11-20"]
rets = nov.pct_change().fillna(0.0) * 100
plat = [("11-02", -0.14), ("11-03", 1.07), ("11-04", -0.63), ("11-05", 4.06),
        ("11-06", -3.43), ("11-09", 0.39), ("11-10", 2.31), ("11-11", 0.48),
        ("11-12", -0.27), ("11-13", -0.17), ("11-16", -1.62), ("11-17", 0.67),
        ("11-18", 0.40), ("11-19", 0.13)]
say("  %-6s %10s %10s %8s" % ("日期", "本地%", "平台%", "差pp"))
tot_l = tot_p = 0.0
for i, (d, v) in enumerate(plat):
    key = "2026-" + d
    if i == 0:
        # 11-02 的日收益需 10-30 收盘为基准
        prev = eq.loc[:pd.Timestamp("2026-10-30")]
        local = (eq.loc[pd.Timestamp(key)] / prev.iloc[-1] - 1) * 100 if len(prev) else np.nan
    else:
        local = rets.get(pd.Timestamp(key), np.nan)
    say("  %-6s %+9.2f%% %+9.2f%% %+8.2f" % (d, local, v, local - v))
    tot_l += local; tot_p += v
say("  %-6s %+9.2f%% %+9.2f%% %+8.2f" % ("累计", tot_l, tot_p, tot_l - tot_p))

say()
say("=" * 100)
say("决定性检验 B：同段交易明细")
say("=" * 100)
for t in r["trades"]:
    if pd.Timestamp(t["date"]) >= pd.Timestamp("2026-10-20"):
        say("  %s %-4s %s %-8s %6d 份 @ %.3f  ret=%s"
            % (pd.Timestamp(t["date"]).date(),
               "买入" if t["action"] == "buy" else ("卖出" if t["action"] == "sell" else "止损"),
               t["code"], NAMES.get(t["code"], ""), t["shares"], t["price"],
               ("%+.2f%%" % (t["ret"] * 100)) if np.isfinite(t["ret"]) else "-"))

say()
say("=" * 100)
say("决定性检验 C：2020 起逐年（本地新引擎 vs 平台隐含）")
say("=" * 100)
sub2 = p.loc["2020-01-01":"2026-11-19"]
r2 = pb.run_band(sub2)
e2 = r2["equity"]
rr = e2.pct_change().fillna(0.0)
yb = rr.groupby(rr.index.year).apply(lambda s: (1 + s).prod() - 1)
s2 = pb.stats(e2, r2["trades"])
say("  本地：年化 %+.2f%% 回撤 %.2f%% 夏普 %.2f 交易 %d 笔 胜率 %.1f%% 盈亏比 %.2f"
    % (s2["cagr"] * 100, s2["max_dd"] * 100, s2["sharpe"], s2["trades"],
       s2["win"] * 100, s2["pl"]))
say("  逐年：" + "  ".join("%d:%+.1f%%" % (y, v * 100) for y, v in yb.items()))
say("  平台总收益 +1630.01%% ⇒ 期末应为 17.3 倍；本地期末 %.2f 倍" % (e2.iloc[-1] / 100000.0))

say()
say("=" * 100)
say("决定性检验 D：把 min_hold 放宽到 1（=每日可换）与 10/20 做参数平台检查")
say("=" * 100)
for mh in [1, 3, 5, 10, 20, 40]:
    rr2 = pb.run_band(sub2, min_hold=mh)
    s3 = pb.stats(rr2["equity"], rr2["trades"], exposure=rr2["exposure"])
    say("  min_hold=%-3d 年化 %+7.2f%%  回撤 %7.2f%%  夏普 %5.2f  交易 %4d  胜率 %5.1f%%  盈亏比 %.2f"
        % (mh, s3["cagr"] * 100, s3["max_dd"] * 100, s3["sharpe"], s3["trades"],
           s3["win"] * 100, s3["pl"]))

say()
say("=" * 100)
say("决定性检验 E：带上下限扫描（look=19, min_hold=5, 2020 起）")
say("=" * 100)
for lo, hi in [(0.0, 999), (0.0, 0.10), (0.02, 0.10), (0.05, 0.10), (0.02, 0.20), (0.0, 0.05)]:
    rr3 = pb.run_band(sub2, lo=lo, hi=hi)
    s4 = pb.stats(rr3["equity"], rr3["trades"], exposure=rr3["exposure"])
    say("  带 [%.0f%%, %.0f%%]  年化 %+7.2f%%  回撤 %7.2f%%  夏普 %5.2f  交易 %4d  持仓 %5.1f%%"
        % (lo * 100, min(hi, 9.99) * 100, s4["cagr"] * 100, s4["max_dd"] * 100,
           s4["sharpe"], s4["trades"], s4["exposure"] * 100))

out = os.path.join(BASE, "_p4c_check.log")
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n[已保存] " + out)
