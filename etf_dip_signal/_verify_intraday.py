# -*- coding: utf-8 -*-
"""用「执行时点价」重跑三条平台策略，量化复现误差是否收敛

对照三组：
  A 收盘价口径（旧）
  B 执行时点价口径（14:30 momo/96864、14:50 96863）
  C 平台官方口径
"""
import json
import os

import numpy as np
import pandas as pd

import _p4_band as pb
import _p5_bank as p5
import _p6_momo as m6
import cf_api

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
END = "2026-11-20"
CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]


# ---------------------------------------------------------------- 指标
def stat(eq):
    s = pd.Series(eq).dropna().astype(float)
    if len(s) < 30:
        return {"cagr": None, "mdd": None, "sharpe": None, "n_days": len(s)}
    yrs = len(s) / 244.0
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    dd = (s / s.cummax() - 1).min()
    r = s.pct_change().dropna()
    sharpe = r.mean() / r.std() * np.sqrt(244) if r.std() > 0 else 0
    return {"cagr": round(cagr * 100, 2), "mdd": round(dd * 100, 2),
            "sharpe": round(float(sharpe), 2), "n_days": len(s),
            "final": round(float(s.iloc[-1] / s.iloc[0]), 3)}


def n_closed(trades):
    if isinstance(trades, pd.DataFrame):
        return int((trades["action"] != "buy").sum()) if "action" in trades else len(trades)
    return int(sum(1 for t in (trades or []) if t.get("action") in ("sell", "stop")))


# ---------------------------------------------------------------- 价库
def px_intraday(tag):
    p = os.path.join(DATA, "intraday_%s.parquet" % tag)
    df = pd.read_parquet(p)
    df["code"] = df["code"].astype(str)
    return df.pivot(index="date", columns="code", values="close").sort_index()


def px_close(codes, start="2015-01-05"):
    d = pd.read_parquet(os.path.join(DATA, "all_etf_1120.parquet"))
    d["code"] = d["code"].astype(str)
    d["date"] = pd.to_datetime(d["date"].astype(str).str[:10])
    w = d[d.code.isin(codes)].pivot(index="date", columns="code", values="close")
    return w.sort_index().loc[start:]


def warm(tag, hhmm, codes):
    """补 2017-06~2017-12 预热段（momo 需要 26 日历史）"""
    p = os.path.join(DATA, "intraday_%s_warm.parquet" % tag)
    if os.path.exists(p):
        return pd.read_parquet(p)
    d = cf_api.get("/fund/hist_intraday", symbol=",".join(codes),
                   start_date="2017-06-01", end_date="2017-12-31",
                   time=hhmm, adjust="none")
    rows = []
    for c, rr in (d or {}).items():
        for x in rr:
            rows.append([x[0], str(c), x[2]])
    df = pd.DataFrame(rows, columns=["date", "code", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df.to_parquet(p, index=False)
    print("   预热段 %d 行 → %s" % (len(df), os.path.basename(p)))
    return df


def merge_warm(base, wdf):
    w = wdf.pivot(index="date", columns="code", values="close").sort_index()
    out = pd.concat([w, base])
    return out[~out.index.duplicated(keep="last")].sort_index()


# ---------------------------------------------------------------- 三条
def run_momo(p, label):
    V1, V2 = m6.build_signals(p, 20, 26)
    i0 = int(np.where(p.index >= "2018-01-01")[0][0])
    r = m6.run(p.iloc[i0:], V1[i0:], V2[i0:])
    st = stat(r["equity"])
    st["trades"] = n_closed(r["trades"])
    print("   %-14s 年化 %+7.2f%%  回撤 %7.2f%%  夏普 %5.2f  平仓 %3d 笔  (%d 天)"
          % (label, st["cagr"], st["mdd"], st["sharpe"], st["trades"], st["n_days"]))
    return st


def run_band(p, label):
    r = pb.run_band(p.loc["2021-01-04":END])
    st = stat(r["equity"])
    st["trades"] = n_closed(r["trades"])
    print("   %-14s 年化 %+7.2f%%  回撤 %7.2f%%  夏普 %5.2f  平仓 %3d 笔  (%d 天)"
          % (label, st["cagr"], st["mdd"], st["sharpe"], st["trades"], st["n_days"]))
    return st


def run_bank(p2, label):
    r = p5.run(p2.loc["2024-10-01":END])
    st = stat(r["equity"])
    st["trades"] = n_closed(r["trades"])
    print("   %-14s 年化 %+7.2f%%  回撤 %7.2f%%  夏普 %5.2f  平仓 %3d 笔  (%d 天)"
          % (label, st["cagr"], st["mdd"], st["sharpe"], st["trades"], st["n_days"]))
    return st


print("=" * 78)
print("momo 96865（平台 56.69% / 22.76% / 1.99 / 883 笔）")
p1430 = px_intraday("1430")
p1430 = merge_warm(p1430, warm("1430", "14:30", m6.CODES))
pc = px_close(sorted(set(m6.CODES) | set(CONSUME) | {"159552", "515020"}))
A = run_momo(pc[m6.CODES], "A 收盘价")
B = run_momo(p1430[m6.CODES], "B 14:30 时点价")

print()
print("=" * 78)
print("96863 消费轮动（平台 53.87% / 20.34% / 1.85 / 475 笔）")
p1450 = px_intraday("1450")
A2 = run_band(pc[CONSUME], "A 收盘价")
B2 = run_band(p1450[CONSUME], "B 14:50 时点价")

print()
print("=" * 78)
print("96864 等股灾（平台 73.07% / 8.59% / 3.84 / 121 笔）")
pair_c = pd.DataFrame({"main": pc["159552"], "bank": pc["515020"]}).dropna()
pair_i = pd.DataFrame({"main": p1430["159552"], "bank": p1430["515020"]}).dropna()
A3 = run_bank(pair_c, "A 收盘价")
B3 = run_bank(pair_i, "B 14:30 时点价")

print()
print("=" * 78)
print("误差收敛汇总（|本地 − 平台|，年化 pp）")
OFF = {"momo": 56.69, "band": 53.87, "bank": 73.07}
rows = []
for nm, a, b, off in (("momo 96865", A, B, OFF["momo"]),
                      ("96863", A2, B2, OFF["band"]),
                      ("96864", A3, B3, OFF["bank"])):
    rows.append([nm, off, a["cagr"], round(a["cagr"] - off, 2),
                 b["cagr"], round(b["cagr"] - off, 2)])
print("   %-12s %9s %9s %9s %9s %9s" % ("策略", "平台", "收盘价", "误差", "时点价", "误差"))
for r in rows:
    print("   %-12s %8.2f%% %8.2f%% %8.2f %8.2f%% %8.2f" % tuple(r))

with open(os.path.join(DATA, "_intraday_verify.json"), "w", encoding="utf-8") as f:
    json.dump({"momo": {"close": A, "intraday": B, "platform": OFF["momo"]},
               "band": {"close": A2, "intraday": B2, "platform": OFF["band"]},
               "bank": {"close": A3, "intraday": B3, "platform": OFF["bank"]}},
              f, ensure_ascii=False, indent=1)
