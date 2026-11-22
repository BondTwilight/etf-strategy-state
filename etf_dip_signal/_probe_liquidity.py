# -*- coding: utf-8 -*-
"""_probe_liquidity.py —— 容量与流动性实测（实盘能不能下手）

三个问题：
  Q1 381 池里有多少只「日成交额 < 1000 万」？（10 万单笔占 1% 已是经验上限）
  Q2 当前持仓 / 候选 / 各策略核心标的的成交额与占比
  Q3 涨跌停距离（涨停买不到、跌停卖不掉）
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import tdx_api

pool = json.load(open("data/fixed_pool.json", encoding="utf-8"))
codes = [str(c) for c in pool["codes"]]
names = {str(k): v for k, v in (pool.get("name") or {}).items()}

rt = tdx_api.get_realtime(codes)
rt["code"] = rt["code"].astype(str)
print("[Q1] 381 池流动性（11-20 成交额）")
amt = rt.set_index("code")["amount"].astype(float) / 1e8      # 亿元
print("  有成交额 %d 只 ｜ 中位 %.2f 亿" % (amt.gt(0).sum(), amt[amt > 0].median()))
bins = [(0, 0.1), (0.1, 0.3), (0.3, 0.5), (0.5, 1), (1, 3), (3, 100)]
for lo, hi in bins:
    n = int(((amt >= lo) & (amt < hi)).sum())
    print("   %5.1f~%-5.1f 亿：%4d 只（%4.1f%%）" % (lo, hi, n, 100.0 * n / len(amt)))
for th in (0.1, 0.3, 0.5):
    m = amt[amt < th].sort_values()
    if len(m):
        print("   < %.1f 亿：%d 只  示例 %s" % (th, len(m),
              " ".join("%s(%.3f亿)" % (c, v) for c, v in m.head(6).items())))

print("\n[Q2] 关键标的的成交额与「10 万单笔占比」")
KEY = {
    "515880": "线C 持仓", "159100": "线C 候选",
    "518880": "momo/黄金", "159509": "momo/纳指科技", "588000": "momo/科创50",
    "501225": "momo/全球芯片", "513100": "momo/纳指100", "513310": "momo/中韩半导体",
    "159915": "momo/创业板", "162719": "momo/石油LOF", "159985": "momo/豆粕",
    "513030": "momo/德国", "513290": "momo/纳指生物", "513520": "momo/日经",
    "159552": "96864/中证2000", "515020": "96864/银行", "512800": "银行",
    "162411": "96863/油气", "161128": "96863/标普信息", "162415": "96863/美国消费",
    "515450": "96863/红利低波", "511880": "货币ETF",
}
print("   %-8s %-16s %10s %10s %9s %8s" % ("code", "用途", "成交额(亿)", "10万占比", "涨跌停距", "现价"))
for c, tag in KEY.items():
    r = rt[rt.code == c]
    if r.empty:
        print("   %-8s %-16s 无行情" % (c, tag))
        continue
    r = r.iloc[0]
    a = float(r["amount"]) / 1e8
    px, lc = float(r["price"]), float(r["last_close"])
    lim = 0.10 if not (c.startswith("5") and c[2] in "89") else 0.10
    up, dn = lc * (1 + lim), lc * (1 - lim)
    print("   %-8s %-16s %10.2f %9.2f%% %9s %8.3f"
          % (c, tag, a, (0.001 / a * 100 if a else np.nan),
             "涨停%+.1f%%" % ((up / px - 1) * 100) if px < up else "已涨停", px))

print("\n[Q3] 全池 11-20 涨跌停状况")
up_n = dn_n = 0
for _, r in rt.iterrows():
    px, lc = float(r["price"]), float(r["last_close"])
    if lc <= 0 or px <= 0:
        continue
    if px / lc - 1 >= 0.099:
        up_n += 1
    if px / lc - 1 <= -0.099:
        dn_n += 1
print("   涨停 %d 只 ｜ 跌停 %d 只（11-20 是大跌日）" % (up_n, dn_n))
