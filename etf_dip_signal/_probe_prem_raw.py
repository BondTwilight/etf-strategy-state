# -*- coding: utf-8 -*-
"""_probe_prem_raw.py —— 溢价率必须用「不复权价 / iopv」

上一版用 qfq 价除以 iopv，算出 159509 +36.84%、513100 +16.98% —— 这是假的：
前复权会把历史价格等比缩放，与「当日真实净值」不可直接相除。

正确口径：不复权收盘价 / 当日 iopv − 1。
本脚本先确认次方接口的 adjust 取值，再重算。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import cifang_api

CODES = ["159509", "513100", "513310", "513520", "159985", "513290",
         "518880", "159915", "588000", "513030", "515880", "510300"]

print("[1] 试探 adjust 取值")
for adj in ["none", "", "raw", "no"]:
    try:
        d = cifang_api._get("/fund/hist_em", {
            "symbol": "159509,515880", "start_date": "2026-11-13",
            "end_date": "2026-11-21", "adjust": adj}) or {}
        ok = list(d.keys())
        sample = ""
        if "159509" in d and d["159509"]:
            r = d["159509"][-1]
            sample = "159509 last close=%s iopv=%s" % (r[2], r[8] if len(r) > 8 else "?")
        print("   adjust=%-6r 返回 %d 只 ｜ %s" % (adj, len(ok), sample))
    except Exception as e:
        print("   adjust=%-6r ERR %s" % (adj, e))

print("\n[2] 用不复权价重算溢价（11-20）")
raw = {}
for i in range(0, len(CODES), 50):
    b = CODES[i:i + 50]
    for adj in ["none"]:
        data = cifang_api._get("/fund/hist_em", {
            "symbol": ",".join(b), "start_date": "2026-08-01",
            "end_date": "2026-11-21", "adjust": adj}) or {}
        for c, rows in data.items():
            if rows:
                raw[str(c)] = pd.DataFrame(rows, columns=cifang_api.COLS[:len(rows[0])])

rows = []
for c in CODES:
    df = raw.get(c)
    if df is None or len(df) == 0:
        rows.append({"code": c, "date": "—", "close_raw": np.nan,
                     "iopv": np.nan, "prem": np.nan, "med20": np.nan})
        continue
    d = df.copy()
    d["date"] = d["date"].astype(str).str[:10]
    for k in ("close", "iopv"):
        d[k] = pd.to_numeric(d[k], errors="coerce")
    d = d.sort_values("date")
    last = d.iloc[-1]
    prem = (last["close"] / last["iopv"] - 1) * 100 if last["iopv"] > 0 else np.nan
    p = (d["close"] / d["iopv"] - 1) * 100
    rows.append({"code": c, "date": last["date"], "close_raw": last["close"],
                 "iopv": last["iopv"], "prem": prem, "med20": p.tail(20).median()})

r = pd.DataFrame(rows)
print(r.to_string(index=False, float_format=lambda x: "%9.4f" % x))

# 对照 qfq
print("\n[3] 同口径下 qfq 价 / iopv（应为假值，用于证明必须用不复权）")
rawq = cifang_api._get("/fund/hist_em", {
    "symbol": "159509,513100", "start_date": "2026-11-13",
    "end_date": "2026-11-21", "adjust": "qfq"}) or {}
for c, rows_ in rawq.items():
    d = pd.DataFrame(rows_, columns=cifang_api.COLS[:len(rows_[0])])
    d = d.sort_values("date")
    last = d.iloc[-1]
    print("   %s qfq close=%s iopv=%s ⇒ px/nav-1=%+.2f%%"
          % (c, last.iloc[2], last.iloc[8] if len(last) > 8 else "?",
             (float(last.iloc[2]) / float(last.iloc[8]) - 1) * 100))
