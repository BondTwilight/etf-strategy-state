# -*- coding: utf-8 -*-
"""_probe_extra.py —— 补查池外标的的成交额/溢价，并抓恒方最新信号"""
import json
import os
import sys

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import tdx_api

EXTRA = ["518880", "501225", "159915", "162719", "515020", "512800",
         "162411", "161128", "162415", "511880", "563300", "510500"]
rt = tdx_api.get_realtime(EXTRA)
print("[池外标的 11-20]")
for _, r in rt.iterrows():
    a = float(r["amount"]) / 1e8
    print("  %-8s %-22s 价 %8.3f 额 %7.2f 亿  10万占比 %.3f%%"
          % (r["code"], r["name"][:22], float(r["price"]), a,
             (0.001 / a * 100) if a else float("nan")))

# 恒方
import urllib.request
print("\n[恒方 signals.json]")
try:
    req = urllib.request.Request(
        "https://gitee.com/bolanggu1031/signal/raw/master/signals.json",
        headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
    print("  key 数：%d" % len(d))
    tds = set()
    n_leg = 0
    for k, v in d.items():
        pl = (v or {}).get("payload") or (v if isinstance(v, dict) else {})
        if pl.get("trade_date"):
            tds.add(str(pl["trade_date"])[:10])
        cals = pl.get("calibers") or []
        n_leg += len(cals)
        print("  %-22s trade_date=%-12s calibers=%d"
              % (k[:22], str(pl.get("trade_date"))[:10], len(cals)))
    print("  交易日集合：%s ｜ 总口径 %d 条" % (sorted(tds), n_leg))
except Exception as e:
    print("  抓取失败：%r" % (e,))
