# -*- coding: utf-8 -*-
"""单独验证断档判断的输入"""
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tdx_api

today = _dt.date.today().isoformat()
print("today =", today)

sp = os.path.join("data", "position_snapshots.json")
all_ = json.load(open(sp, encoding="utf-8"))
print("快照 keys =", sorted(all_.keys()))
cand = sorted(k for k in all_ if str(k) < str(today))
print("cand =", cand)
last = cand[-1] if cand else None
print("last =", last)

tds = tdx_api.get_trade_dates(start_date=last, end_date=today)
print("trade_dates(%s ~ %s) = %s  (len=%d)" % (last, today, tds, len(tds)))
print("missed =", max(len(tds) - 2, 0))
