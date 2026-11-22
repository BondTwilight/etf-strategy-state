# -*- coding: utf-8 -*-
"""_probe_prem_live.py —— 溢价率实测（次方日线第 9 列 iopv，无滞后/不受折算影响）

为什么不用 tushare fund_nav：会算出 513100 极差 523% 的假值（份额折算干扰）。
为什么不用腾讯 f[78]：跨境标的返回的是滞后净值，159509 会算出 +36.8% 的假溢价。
次方 iopv 是交易所发布的盘中净值估算，收盘后即定型，是唯一可信口径。

回答：今天如果要买，我面对的溢价是多少？
  A. momo 12 池（12 只里 10 只是跨境/商品）
  B. 线C 当前候选 159100
  C. 线C 持仓 515880
  D. 96864 的 159552 / 银行腿
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import cifang_api

MOMO = ["518880", "159509", "588000", "501225", "513100", "513310",
        "159915", "162719", "159985", "513030", "513290", "513520"]
MOMO_N = {"518880": "黄金", "159509": "纳指科技", "588000": "科创50",
          "501225": "全球芯片", "513100": "纳指100", "513310": "中韩半导体",
          "159915": "创业板", "162719": "石油LOF", "159985": "豆粕",
          "513030": "德国", "513290": "纳指生物", "513520": "日经"}
EXTRA = ["159100", "515880", "510300", "511880", "512800", "515020", "159552",
         "162411", "161128", "162415", "515450", "159967"]
codes = list(dict.fromkeys(MOMO + EXTRA))

print("拉取 %d 只（含 iopv 第 9 列）..." % len(codes))
raw = {}
for i in range(0, len(codes), 50):
    batch = codes[i:i + 50]
    data = cifang_api._get("/fund/hist_em", {
        "symbol": ",".join(batch),
        "start_date": "2026-08-01",
        "end_date": "2026-11-21",
        "adjust": "qfq",
    }) or {}
    for code, rows in data.items():
        if rows:
            raw[str(code)] = pd.DataFrame(rows, columns=cifang_api.COLS[:len(rows[0])])

print("返回 %d 只" % len(raw))

rows = []
for c in codes:
    df = raw.get(c)
    if df is None or len(df) == 0:
        rows.append({"code": c, "name": MOMO_N.get(c, ""), "date": "—",
                     "close": np.nan, "iopv": np.nan, "prem": np.nan, "med20": np.nan})
        continue
    d = df.copy()
    d["date"] = d["date"].astype(str).str[:10]
    for k in ("close", "iopv"):
        if k in d.columns:
            d[k] = pd.to_numeric(d[k], errors="coerce")
    d = d.sort_values("date")
    last = d.iloc[-1]
    prem = (last["close"] / last["iopv"] - 1) * 100 if last.get("iopv") else np.nan
    p20 = (d["close"] / d["iopv"] - 1).tail(20) * 100
    rows.append({"code": c, "name": MOMO_N.get(c, ""), "date": last["date"],
                 "close": last["close"], "iopv": last.get("iopv", np.nan),
                 "prem": prem, "med20": p20.median()})

r = pd.DataFrame(rows)

print("\n【A】momo 12 池 —— 11-20 收盘溢价率（close/iopv−1）")
m = r[r.code.isin(MOMO)].copy()
m["nm"] = m.code.map(MOMO_N)
print(m[["code", "nm", "date", "close", "iopv", "prem", "med20"]].to_string(
    index=False, float_format=lambda x: "%8.3f" % x))
v = m["prem"].dropna()
print("  中位 %.2f%% ｜ >2%% 的 %d 只 ｜ >5%% 的 %d 只 ｜ 最大 %.2f%%"
      % (v.median(), (v > 2).sum(), (v > 5).sum(), v.max()))

print("\n【B/C/D】其他关注标的")
o = r[~r.code.isin(MOMO)]
print(o[["code", "name", "date", "close", "iopv", "prem", "med20"]].to_string(
    index=False, float_format=lambda x: "%8.3f" % x))

print("\n【分级】按 11-20 溢价")
r2 = r.dropna(subset=["prem"]).sort_values("prem", ascending=False)
for _, x in r2.iterrows():
    tag = ("[!!] >5%" if x.prem > 5 else
           "[! ] 2-5%" if x.prem > 2 else
           "[~ ] 1-2%" if x.prem > 1 else
           "[ok] <1%" if x.prem > -1 else "[dc] 折价")
    print("  %-8s %-10s %+7.2f%%  %s (20日中位 %+.2f%%)"
          % (x.code, str(x.get("name", ""))[:10], x.prem, tag, x.med20))

r.to_csv("data/_premium_1120.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/_premium_1120.csv")
