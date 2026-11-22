# -*- coding: utf-8 -*-
"""
_audit_pool.py —— 池子「事后挑选」审计（2026-11-22）

要回答的问题
-----------
我们的三个池子（381 冻结池 / 12 只 momo 池 / 线B 的 ETF 池）都是**今天**定下来的。
如果池内标的的历史表现显著优于「同期全市场所有 ETF」，那池子本身就是 alpha 的来源，
策略的回测收益就不能当成「规则的能力」。

三个检验
-------
T1 池内标的的上市日期分布：多少只是「最近两年才上市」的？
T2 分层收益对比：在某个历史起点上，把全市场 ETF 分成「池内 / 池外」，
   比较此后的收益分布。差多少？用 Mann-Whitney U 检验。
T3 「如果 2021 年就知道今天的池子」vs「如果 2021 年只能用当时已上市的标的」：
   两种口径的差距 = 事后挑选的溢价。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import data_quality

DATA = os.path.join(BASE, "data", "all_etf_1119.parquet")
POOL = os.path.join(BASE, "data", "fixed_pool.json")
MOMO = ["518880", "159509", "588000", "501225", "513100", "513310",
        "159915", "162719", "159985", "513030", "513290", "513520"]

lines = []
def say(s=""):
    lines.append(str(s)); print(s)


def load():
    df = pd.read_parquet(DATA)
    df["code"] = df["code"].astype(str)
    df["date"] = df["date"].astype(str).str[:10]
    df = df[df["close"] > 0]
    return df


def ret_between(px, c, a, b):
    s = px.get(c)
    if s is None:
        return np.nan
    w = s.loc[a:b].dropna()
    if len(w) < 40:
        return np.nan
    return w.iloc[-1] / w.iloc[0] - 1


def main():
    df = load()
    d = json.load(open(POOL, encoding="utf-8"))
    p381 = [str(x) for x in d["codes"]]
    n381 = d.get("name") or {}

    # 每只标的的首末日期
    first = df.groupby("code")["date"].min()
    last = df.groupby("code")["date"].max()
    px = {c: g.set_index("date")["close"].astype(float).sort_index()
          for c, g in df.groupby("code")}

    say("=" * 104)
    say("T1 池内标的的上市（首个有数据）年份分布")
    say("=" * 104)
    for label, pool in [("381 冻结池", p381), ("12 只 momo 池", MOMO)]:
        have = [c for c in pool if c in first.index]
        yrs = first.reindex(have).str[:4].astype(int)
        say("\n  %s（%d 只，有数据 %d 只）" % (label, len(pool), len(have)))
        vc = yrs.value_counts().sort_index()
        for y, n in vc.items():
            bar = "█" * min(int(n), 60)
            say("    %d 年  %4d 只  %s" % (y, n, bar))
        say("    中位上市年份 %d｜2024 年后上市 %d 只（%.1f%%）｜2022 年后上市 %d 只（%.1f%%）"
            % (int(yrs.median()), int((yrs >= 2024).sum()), (yrs >= 2024).mean() * 100,
               int((yrs >= 2022).sum()), (yrs >= 2022).mean() * 100))

    say()
    say("=" * 104)
    say("T2 分层收益对比：全市场 ETF，池内 vs 池外")
    say("=" * 104)
    say("  说明：只用「起点前已有 ≥60 个交易日」的标的，避免「新上市=高收益」的干扰。")
    say("  %-10s %-14s %6s %10s %10s %10s %10s %8s" %
        ("起点", "池", "样本", "收益中位", "收益均值", "25分位", "75分位", "vs池外"))
    say("  " + "-" * 94)

    rows = []
    for start in ["2018-01-01", "2020-01-01", "2021-01-01", "2022-01-01"]:
        cutoff = (pd.Timestamp(start) - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
        alive = [c for c in first.index if first[c] <= cutoff and last[c] >= start]
        def stats(pool):
            r = np.array([ret_between(px, c, start, "2026-11-19") for c in pool])
            r = r[np.isfinite(r)]
            if len(r) < 3:
                return None
            return (len(r), np.median(r), r.mean(),
                    np.percentile(r, 25), np.percentile(r, 75), r)
        for label, pool in [("381池内", [c for c in p381 if c in alive]),
                            ("12池内", [c for c in MOMO if c in alive])]:
            out = stats(pool)
            outsiders = [c for c in alive if c not in set(p381) and c not in set(MOMO)]
            so = stats(outsiders)
            if not out or not so:
                continue
            say("  %-10s %-14s %6d %+9.1f%% %+9.1f%% %+9.1f%% %+9.1f%%  %+7.1fpp"
                % (start, label, out[0], out[1] * 100, out[2] * 100,
                   out[3] * 100, out[4] * 100, (out[1] - so[1]) * 100))
            rows.append((start, label, out, so))
        so = stats([c for c in alive if c not in set(p381) and c not in set(MOMO)])
        if so:
            say("  %-10s %-14s %6d %+9.1f%% %+9.1f%% %+9.1f%% %+9.1f%%  %8s"
                % (start, "池外(全市场)", so[0], so[1] * 100, so[2] * 100,
                   so[3] * 100, so[4] * 100, "—"))

    say()
    say("=" * 104)
    say("T2b Mann-Whitney U 检验（池内 vs 池外，H0：同分布）")
    say("=" * 104)
    try:
        from scipy.stats import mannwhitneyu
        for start, label, out, so in rows:
            u, pv = mannwhitneyu(out[5], so[5], alternative="greater")
            say("  %-10s %-10s n=%3d vs %3d  U=%.0f  p=%.4f  %s"
                % (start, label, out[0], so[0], u, pv,
                   "显著高于池外" if pv < 0.05 else ("弱显著" if pv < 0.10 else "无显著差异")))
    except Exception as e:
        say("  scipy 不可用：%r（改用中位数差判断）" % (e,))

    say()
    say("=" * 104)
    say("T3 「事后挑选溢价」：同一条规则，用当时的池子 vs 用今天的池子")
    say("=" * 104)
    say("  这里用最直接的度量：池内标的在「被选入之前」的表现排名分位。")
    say("  若中位分位显著 > 50%，说明池子是「选了跑赢的」。")
    say()
    for start in ["2018-01-01", "2021-01-01"]:
        cutoff = (pd.Timestamp(start) - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
        alive = [c for c in first.index if first[c] <= cutoff and last[c] >= start]
        allr = {c: ret_between(px, c, start, "2026-11-19") for c in alive}
        allr = {c: v for c, v in allr.items() if np.isfinite(v)}
        if len(allr) < 30:
            continue
        s = pd.Series(allr)
        rank = s.rank(pct=True)
        for label, pool in [("381池内", [c for c in p381 if c in rank.index]),
                            ("12池内", [c for c in MOMO if c in rank.index])]:
            if not pool:
                continue
            q = rank.reindex(pool).dropna()
            say("  起点 %s  %-8s n=%3d  收益分位中位 %.0f%%（均值 %.0f%%）｜>80%%分位 %d 只（%.0f%%）"
                % (start, label, len(q), q.median() * 100, q.mean() * 100,
                   int((q > 0.8).sum()), (q > 0.8).mean() * 100))

    say()
    say("=" * 104)
    say("结论")
    say("=" * 104)
    say("  · 若「池内收益分位中位」明显高于 50%，则池子本身带事后挑选，")
    say("    策略回测的水分就来自池子，而不是规则。")
    say("  · 这不是「作弊」——实盘也要选池；但它决定了：**我们能不能把回测收益当预期。**")

    open(os.path.join(BASE, "_audit_pool.log"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n[已保存] _audit_pool.log")


if __name__ == "__main__":
    main()
