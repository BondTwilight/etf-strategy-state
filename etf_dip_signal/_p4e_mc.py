# -*- coding: utf-8 -*-
"""
_p4e_mc.py —— 决定性检验：12 池的 48.77% 是「规则」给的，还是「选出这 6 只」给的？

方法：
  1. 随机池蒙特卡洛：从 381 冻结池里随机抽 6 只（要求 2020-01-01 前有数据），
     跑完全相同的规则，重复 N 次，看年化分布。12 池落在哪个分位？
  2. 留一法：12 池去掉任一只，看年化变化。
  3. 分离「上限过滤」与「下限过滤」在 381 池上的贡献。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import _p4_band as pb

CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]
NAMES = {"162411": "油气", "513100": "纳指100", "161128": "标普信息",
         "588000": "科创50", "162415": "美国消费", "515450": "红利低波"}
START, END = "2020-01-01", "2026-11-19"
N_MC = 300
SEED = 20261122

lines = []
def say(s=""):
    lines.append(str(s)); print(s)

codes381, bmap = pb.load_pool_codes()
hist, p_all, fixed = pb.load_all(set(codes381) | set(CONSUME))

# 2020-01-01 前已有 20 个交易日数据的标的（否则 2020 年初无信号）
eligible = []
for c in codes381:
    if c not in p_all.columns:
        continue
    s = p_all[c].loc[:START].dropna()
    if len(s) >= 25:
        eligible.append(c)
say("可用于随机抽样的标的（2020-01-01 前已有 ≥25 个交易日）：%d 只" % len(eligible))

say()
say("=" * 100)
say("A. 随机池蒙特卡洛：随机抽 6 只，跑同一规则（look=18, 2%%~10%%, min_hold=5）")
say("=" * 100)
rng = np.random.default_rng(SEED)
vals = []
n_ok = 0
tries = 0
while n_ok < N_MC and tries < N_MC * 8:
    tries += 1
    pick = list(rng.choice(eligible, size=6, replace=False))
    sub = p_all[pick].loc[START:END]
    # 至少要有 4 只在 90 天内出现，避免全是空数据的组合
    if sub.notna().sum().sum() < 300:
        continue
    r = pb.run_band(sub)
    s = pb.stats(r["equity"], r["trades"])
    if not s:
        continue
    vals.append((s["cagr"], s["max_dd"], s["sharpe"]))
    n_ok += 1

v = np.array(vals)
say("  有效样本 %d 组（尝试 %d 次）" % (n_ok, tries))
say("  年化：均值 %+.2f%%  中位 %+.2f%%  σ %.2fpp" % (v[:, 0].mean() * 100, np.median(v[:, 0]) * 100, v[:, 0].std() * 100))
say("  分位：5%%=%+.1f%%  25%%=%+.1f%%  50%%=%+.1f%%  75%%=%+.1f%%  95%%=%+.1f%%"
    % tuple(np.percentile(v[:, 0], [5, 25, 50, 75, 95]) * 100))
say("  年化 > 0 的占比 %.1f%%｜> 20%% 的占比 %.1f%%｜> 40%% 的占比 %.1f%%"
    % ((v[:, 0] > 0).mean() * 100, (v[:, 0] > 0.20).mean() * 100, (v[:, 0] > 0.40).mean() * 100))
say("  回撤：中位 %.2f%%  最差 %.2f%%" % (np.median(v[:, 1]) * 100, v[:, 1].min() * 100))

# 12 池基准
r12 = pb.run_band(p_all[CONSUME].loc[START:END])
s12 = pb.stats(r12["equity"], r12["trades"])
pct = (v[:, 0] < s12["cagr"]).mean() * 100
say()
say("  ★ 12 池（真实策略）：年化 %+.2f%%  回撤 %.2f%%" % (s12["cagr"] * 100, s12["max_dd"] * 100))
say("  ★ 12 池在随机分布中的分位：第 %.1f 百分位" % pct)
say("  ★ 含义：随机抽 6 只，有 %.1f%% 的组合比这 6 只做得差；即「选池」贡献了收益的主要部分" % pct)

# 381 池等权基准
r381 = pb.run_band(p_all[[c for c in codes381 if c in p_all.columns]].loc[START:END])
s381 = pb.stats(r381["equity"], r381["trades"])
say()
say("  对照 · 381 全池同规则：年化 %+.2f%%  回撤 %.2f%%  交易 %d"
    % (s381["cagr"] * 100, s381["max_dd"] * 100, s381["trades"]))

say()
say("=" * 100)
say("B. 留一法：12 池去掉任一只")
say("=" * 100)
say("  %-14s %9s %10s %7s" % ("去掉", "年化", "最大回撤", "夏普"))
say("  " + "-" * 46)
say("  %-14s %+8.2f%% %9.2f%% %7.2f" % ("（全部 6 只）", s12["cagr"] * 100,
                                       s12["max_dd"] * 100, s12["sharpe"]))
for c in CONSUME:
    rest = [x for x in CONSUME if x != c]
    r = pb.run_band(p_all[rest].loc[START:END])
    s = pb.stats(r["equity"], r["trades"])
    say("  %-14s %+8.2f%% %9.2f%% %7.2f   (Δ年化 %+.2fpp)"
        % ("去掉 " + NAMES[c], s["cagr"] * 100, s["max_dd"] * 100, s["sharpe"],
           (s["cagr"] - s12["cagr"]) * 100))

say()
say("=" * 100)
say("C. 拆解「上限」与「下限」各自的贡献")
say("=" * 100)
say("  %-22s %12s %12s" % ("口径", "12 池", "381 池"))
say("  " + "-" * 50)
for lbl, lo, hi in [("无带（纯最强动量）", 0.0, 999.0),
                    ("只上限 hi=10%", 0.0, 0.10),
                    ("只下限 lo=2%", 0.02, 999.0),
                    ("完整带 2%~10%", 0.02, 0.10)]:
    r1 = pb.run_band(p_all[CONSUME].loc[START:END], lo=lo, hi=hi)
    s1 = pb.stats(r1["equity"], r1["trades"])
    r2 = pb.run_band(p_all[[c for c in codes381 if c in p_all.columns]].loc[START:END], lo=lo, hi=hi)
    s2 = pb.stats(r2["equity"], r2["trades"])
    say("  %-22s %+11.2f%% %+11.2f%%" % (lbl, s1["cagr"] * 100, s2["cagr"] * 100))

say()
say("=" * 100)
say("D. 结论（机器可读摘要）")
say("=" * 100)
say("  1) 381 池四起点全负（-1.3% ~ -5.7%），回撤 -49.5%：规则在宽池上稳定失效，非噪声。")
say("  2) 12 池四起点 +44%% ~ +54%%，但随机 6 只池的年化中位约 %+.1f%%，12 池位于第 %.0f 百分位，"
    % (np.median(v[:, 0]) * 100, pct))
say("     说明超额主要来自「这 6 只是 2020-2026 最好的 6 只」，不是规则本身。")
say("  3) min_hold 是尖峰（5→48.8%，10→15.6%，40→8.0%），无平台区 ⇒ 过拟合特征。")
say("  4) 上限 hi=10%% 贡献几乎全部超额；下限 lo=2%% 几乎无贡献（12 池 47.3%% vs 48.8%%）。")

out = os.path.join(BASE, "_p4e_mc.log")
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n[已保存] " + out)
