# -*- coding: utf-8 -*-
"""_probe_live.py —— 实盘链路三源核查

Q1 次方 hist_em 对 381 池的返回率是多少？缺的是哪些？
Q2 腾讯 qt 实时价覆盖 381 池多少？
Q3 pytdx 覆盖多少？
"""
import json
import os
import sys
import time

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import cifang_api
import tdx_api

pool = json.load(open("data/fixed_pool.json", encoding="utf-8"))
codes = [str(c) for c in pool["codes"]]
print("池子 %d 只" % len(codes))

# ---------- Q1 次方 ----------
print("\n[Q1] 次方 hist_em 全池返回率")
t0 = time.time()
try:
    raw = cifang_api.hist_em(codes, "2026-07-01", "2026-11-21", adjust="qfq")
except Exception as e:
    raw = {}
    print("  失败:", e)
got = [c for c in codes if c in raw and raw[c] is not None and len(raw[c])]
print("  返回 %d/%d（%.1f%%）耗时 %.1fs"
      % (len(got), len(codes), 100.0 * len(got) / len(codes), time.time() - t0))
miss = [c for c in codes if c not in got]
print("  缺失 %d 只：%s" % (len(miss), " ".join(miss[:40])))
if got:
    last = {}
    for c in got:
        d = raw[c]
        try:
            last[c] = str(d["date"].astype(str).str[:10].iloc[-1])
        except Exception:
            pass
    vc = pd.Series(last).value_counts().head(5)
    print("  最新日分布：", dict(vc))

# ---------- Q2 腾讯 qt ----------
print("\n[Q2] 腾讯 qt 实时价覆盖")
t0 = time.time()
rt = tdx_api.get_realtime(codes)
print("  返回 %d/%d 行 ｜ 非停牌 %d ｜ 耗时 %.1fs"
      % (len(rt), len(codes), int((rt["price"] > 0).sum()) if len(rt) else 0, time.time() - t0))
if len(rt):
    print("  列：", list(rt.columns))
    sub = rt[rt.code.isin(["515880", "510300", "159915", "511880", "512800"])]
    print(sub[["code", "name", "price", "last_close", "amount"]].to_string(index=False))
