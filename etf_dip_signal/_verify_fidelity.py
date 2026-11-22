# -*- coding: utf-8 -*-
"""
移植保真校验（按项目铁律：跨引擎先做保真，再谈结论）

用回测同一套 qfq 数据，在 2026-10-20 这一天重算候选池，
与线上脚本当天实际输出的候选池逐只比对。
"""
import os
import re
import sys
import json

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import cifang_api
import bt_etf_dip as bt
import data_quality

TARGET = "2026-10-20"
pool = json.load(open(os.path.join(BASE, "data", "fixed_pool.json"), encoding="utf-8"))
codes, bmap = [str(c) for c in pool["codes"]], {str(k): int(v) for k, v in pool["bmap"].items()}

hist = cifang_api.fetch_pool_history(codes, cache_path=os.path.join(BASE, "data", "etf_qfq_cifang.parquet"))
hist, _ = data_quality.audit(hist, verbose=False)
m = bt.build_matrices(hist, start="2026-05-01", end=TARGET)

i = m["dates"].index(TARGET)
th = np.array([bmap.get(c, -16) for c in m["codes"]], dtype=float)
mask = (m["bmin5"][i] < th) & np.isfinite(m["close"][i])
cands = np.where(mask)[0]
order = cands[np.argsort(m["bias50"][i, cands])]

print("=== 回测引擎在 %s 的候选池（qfq，前复权）===" % TARGET)
print("候选 %d 只：" % len(order))
for r, j in enumerate(order, 1):
    print("  %d. %s  50日乖离%+.2f%%  20日乖离%+.2f%%  阈值%d  收盘%.4f" % (
        r, m["codes"][j], m["bias50"][i, j], m["bias20"][i, j],
        bmap.get(m["codes"][j], -16), m["close"][i, j]))

print("\n=== 线上脚本当天实际输出（信号输出/latest.txt）===")
p = os.path.join(BASE, "信号输出", "latest.txt")
txt = open(p, encoding="utf-8").read()
seg = txt.split("【抄底候选池】")[1].split("【")[0]
live = re.findall(r"(\d{6})\s+(\S+)\s+50日乖离(-?\d+\.\d+)%\s*/\s*20日乖离(-?\d+\.\d+)%", seg)
for k, (code, name, b50, b20) in enumerate(live, 1):
    print("  %d. %s %s  50日乖离%s%%  20日乖离%s%%" % (k, code, name, b50, b20))

live_codes = [x[0] for x in live]
bt_codes = [m["codes"][j] for j in order]
print("\n=== 比对 ===")
print("线上 ", live_codes)
print("回测 ", bt_codes)
print("完全一致：%s" % (live_codes == bt_codes))
print("交集：%s" % sorted(set(live_codes) & set(bt_codes)))
print("线上独有：%s" % sorted(set(live_codes) - set(bt_codes)))
print("回测独有：%s" % sorted(set(bt_codes) - set(live_codes)))

# 逐只对比乖离率数值（同一只、两个数据源）
print("\n同一标的乖离率数值对比（线上=新浪不复权 / 回测=次方qfq）：")
live_map = {c: (float(b50), float(b20)) for c, _, b50, b20 in live}
for code in sorted(set(live_codes) | set(bt_codes)):
    if code in m["codes"] and code in live_map:
        j = m["codes"].index(code)
        lb50, lb20 = live_map[code]
        print("  %s  qfq: 50日%+.2f%% 20日%+.2f%%  ｜ 新浪: 50日%+.2f%% 20日%+.2f%%  ｜ 差 %+.2fpp / %+.2fpp"
              % (code, m["bias50"][i, j], m["bias20"][i, j], lb50, lb20,
                 m["bias50"][i, j] - lb50, m["bias20"][i, j] - lb20))
