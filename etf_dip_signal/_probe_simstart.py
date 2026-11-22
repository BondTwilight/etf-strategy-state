# -*- coding: utf-8 -*-
"""_probe_simstart.py —— 模拟段起点检查：从冻结日起跑，持仓能否对上线上记录

线上（positions.json）：515880，成本 0.429429，建仓 2026-11-05
如果从 2026-10-14（池子冻结日）起跑，回测应产出同一个持仓 —— 否则说明
「回测路径」与「线上路径」有偏差，看板必须展示两个，不能混。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import _sim as S

hist, px, names, fixed, codes, bmap = S.load_all()
p381 = px[[c for c in codes if c in px.columns]]

for start in ["2026-10-14", "2026-10-21", "2026-11-01"]:
    h = {c: hist[c] for c in codes if c in hist and hist[c]["date"].min() < start}
    m = S.bt.build_matrices(h, start=start, end=S.END)
    r = S.bm.run(m, bmap, max_hold=1, intraday_stop=True, exec_mode="close", timeout_live=True)
    tr = S.std_trades(r["trades"])
    hold = S.positions_from_trades(tr, px, names)
    eq = pd.Series(r["equity"]).dropna()
    print("\n起点 %s ｜ 净值 %.1f → %.1f（%+.2f%%）｜ 交易 %d 笔"
          % (start, eq.iloc[0], eq.iloc[-1], (eq.iloc[-1] / eq.iloc[0] - 1) * 100, len(tr)))
    for t in tr:
        print("   %s %-4s %-8s @ %.4f  %s" %
              (t["date"], t["action"], t["code"], t["price"], t["reason"][:40]))
    print("   期末持仓：", [(x["code"], x["name"], x["shares"], x["cost"], x["pnl"], x["held_days"])
                          for x in hold])

print("\n线上记录：")
pos = json.load(open("data/positions.json", encoding="utf-8"))
print("  ", pos)
