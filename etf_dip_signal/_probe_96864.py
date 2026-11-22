# -*- coding: utf-8 -*-
"""96864 复现差距溯源：预热段 / 止损 / 冷却期 / 复权"""
import os

import numpy as np
import pandas as pd

import _p5_bank as p5

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
END = "2026-11-20"
PLAT = 73.07


def px_intraday(tag):
    df = pd.read_parquet(os.path.join(DATA, "intraday_%s.parquet" % tag))
    df["code"] = df["code"].astype(str)
    return df.pivot(index="date", columns="code", values="close").sort_index()


def px_close(codes, start="2015-01-05"):
    d = pd.read_parquet(os.path.join(DATA, "all_etf_1120.parquet"))
    d["code"] = d["code"].astype(str)
    d["date"] = pd.to_datetime(d["date"].astype(str).str[:10])
    return d[d.code.isin(codes)].pivot(index="date", columns="code",
                                       values="close").sort_index().loc[start:]


def pair(px):
    return pd.DataFrame({"main": px["159552"], "bank": px["515020"]}).dropna()


def stat(eq, start):
    s = pd.Series(eq).dropna().astype(float).loc[start:]
    if len(s) < 30:
        return None
    yrs = len(s) / 244.0
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    dd = (s / s.cummax() - 1).min()
    r = s.pct_change().dropna()
    sh = r.mean() / r.std() * np.sqrt(244) if r.std() > 0 else 0
    return dict(cagr=round(cagr * 100, 2), mdd=round(dd * 100, 2),
                sharpe=round(float(sh), 2), days=len(s))


def show(tag, r, start="2024-10-01"):
    st = stat(r["equity"], start)
    n = int(sum(1 for t in r["trades"] if t["action"] in ("sell", "stop")))
    print("   %-30s 年化 %+7.2f%%  回撤 %7.2f%%  夏普 %5.2f  平仓 %d 笔  (差 %+6.2fpp)"
          % (tag, st["cagr"], st["mdd"], st["sharpe"], n, st["cagr"] - PLAT))
    return st


pc = pair(px_close(["159552", "515020"]))
pi = pair(px_intraday("1430"))

print("96864 等股灾 ｜ 平台 73.07% / 8.59% / 夏普 3.84")
print("=" * 88)
print("A 组：起点截断（无预热）")
show("收盘价  loc[2024-10-01:]", p5.run(pc.loc["2024-10-01":END]))
show("14:30  loc[2024-10-01:]", p5.run(pi.loc["2024-10-01":END]))

print("\nB 组：从 2024-06-28 起跑（有预热），只统计 2024-10-01 之后")
show("收盘价  2024-06-28 起跑", p5.run(pc.loc["2024-06-28":END]))
show("14:30  2024-06-28 起跑", p5.run(pi.loc["2024-06-28":END]))

print("\nC 组：14:30 + 预热，逐项拆件（看哪个部件影响最大）")
base = p5.run(pi.loc["2024-06-28":END])
for kw, nm in (({"use_stop": False}, "关双止损"),
               ({"stop_cool": 3}, "止损冷却 3 天"),
               ({"stop_cool": 10}, "止损冷却 10 天"),
               ({"hold_cool": 1}, "最小持有 1 天"),
               ({"use_ma": False}, "不要 MA10 过滤"),
               ({"use_default": False}, "关银行默认腿")):
    show(nm + "  " + str(kw), p5.run(pi.loc["2024-06-28":END], **kw))

print("\nD 组：首笔交易对比（14:30 + 预热）")
for kw, nm in (({}, "基准"),):
    r = p5.run(pi.loc["2024-06-28":END], **kw)
    for t in r["trades"][:8]:
        print("   %s  %-4s %-6s  %.4f"
              % (str(t["date"])[:10], t["action"], t["code"], t["price"]))
