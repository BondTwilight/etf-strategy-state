# -*- coding: utf-8 -*-
"""唯一还没试过的结构性改进：把固定 8% 移动止盈换成「按波动率归一化」

trail_i = clip(k × σ20_i, 4%, 20%)，σ20 = 近 20 日对数收益标准差。
先验：固定 8% 对高波动标的太紧（油气日波动 2% ⇒ 只有 4 个日波动，易误杀），
      对低波动标的太松（宽基日波动 0.5% ⇒ 16 个日波动，形同虚设）。
判据：不只看主窗口，还要在长窗口(2016起)同向，且 k 有平台而非尖峰。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

BASE = dict(be_stop=0.03, cash_yield=0.025, slippage=0.002)

d = json.load(open("data/fixed_pool.json", encoding="utf-8"))
BMAP = {str(k): int(v) for k, v in d["bmap"].items()}

raw = pd.read_parquet("data/etf_qfq_cifang.parquet",
                      columns=["code", "date", "open", "close", "low"])
raw["date"] = raw["date"].astype(str).str[:10]
hist = {}
for code, g in raw.groupby("code", sort=False):
    f, _ = data_quality.repair_prices(g[["date", "open", "close", "low"]])
    hist[code] = f.reset_index(drop=True)
del raw
print("载入 %d 只" % len(hist), flush=True)

M = {
    "主窗口 2021起": bt1.build_matrices(hist, start="2021-01-01", end="2026-10-20"),
    "长窗口 2016起": bt1.build_matrices(hist, start="2016-01-01", end="2026-10-20"),
}


def show(tag, **kw):
    out = []
    for wname, m in M.items():
        r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode="close",
                   timeout_live=True, **BASE, **kw)
        p = bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])
        wr = p["win_rate"] * 100 if np.isfinite(p["win_rate"]) else float("nan")
        out.append((p["cagr"] * 100, p["max_dd"] * 100, p["calmar"], p["trades"], wr))
    print("  %-22s 主 %6.2f%% / %6.2f%% / %4.2f / %2d 笔 ｜ 长 %6.2f%% / %6.2f%% / %4.2f / %2d 笔"
          % (tag, out[0][0], out[0][1], out[0][2], out[0][3],
             out[1][0], out[1][1], out[1][2], out[1][3]), flush=True)
    return out


print("\n" + "=" * 118)
print("移动止盈：固定 8% vs 波动率归一化（k×σ20，clamp 4%~20%）")
print("=" * 118)
print("  %-22s %s" % ("", "年化 / 回撤 / Calmar / 笔数"))
show("固定 8%（现状）", trail=0.08)
for k in (2.5, 3.0, 3.5, 4.0, 4.5, 5.0):
    show("归一化 k=%.1f" % k, trail=0.08, trail_k=k)
