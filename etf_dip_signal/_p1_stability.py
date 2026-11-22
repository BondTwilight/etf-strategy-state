# -*- coding: utf-8 -*-
"""
P1 第一 pass：线C 的“信号深度/领先度”是否预测单笔胜负
- 深度 depth = 阈值 - 近5日20日乖离最小值（越大=跌得越透）
- 领先 lead = 第二名50日乖离 - 第一名50日乖离（越大=第一名越“独”）
- 候选数 n_cand
对每笔买入计算特征，按分位分组看胜率/均值；并做 Spearman 相关。
"""
import os, sys, json
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

BASE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, BASE)
import bt_etf_dip as bt, bt_multi as bm, data_quality

df = pd.read_parquet(os.path.join(BASE, "data", "all_etf_1119.parquet"))
df["code"] = df["code"].astype(str)
pool = json.load(open(os.path.join(BASE, "data", "fixed_pool.json"), encoding="utf-8"))
codes = [str(c) for c in pool["codes"]]
bmap = {str(k): int(v) for k, v in pool["bmap"].items()}
hist = {}
for c in codes:
    s = df[df.code == c][["date", "open", "close", "high", "low"]].copy()
    if len(s) >= 80: hist[c] = s
hist, _ = data_quality.audit(hist, verbose=False)

m = bt.build_matrices(hist, start="2018-01-01", end="2026-11-19")
th = np.array([bmap.get(c, -16) for c in m["codes"]], dtype=float)
dates = [str(d)[:10] for d in m["dates"]]
code_idx = {c: i for i, c in enumerate(m["codes"])}

r = bm.run(m, bmap, max_hold=1, intraday_stop=True, exec_mode="close", cash0=100000.0)
trades = r["trades"].copy()
trades["date"] = trades["date"].astype(str).str[:10]

rows = []
cur = None
for _, tr in trades.iterrows():
    if tr["action"] == "buy":
        cur = tr
    elif tr["action"] == "sell" and cur is not None and tr["code"] == cur["code"]:
        t = dates.index(cur["date"])
        j = code_idx[cur["code"]]
        bmin = m["bmin5"][t, j]
        depth = th[j] - bmin if np.isfinite(bmin) else np.nan
        # 当日候选与排序
        mask = (m["bmin5"][t] < th) & m["valid"][t]
        cands = np.where(mask)[0]
        key = m["bias50"][t]
        cands = cands[np.isfinite(key[cands])]
        order = cands[np.argsort(key[cands])] if len(cands) else np.array([], dtype=int)
        lead = np.nan
        if len(order) >= 2 and order[0] == j:
            lead = key[order[1]] - key[order[0]]
        rows.append(dict(date=cur["date"], code=cur["code"], ret=tr["ret"],
                         depth=depth, lead=lead, n_cand=len(order),
                         hold_days=(pd.Timestamp(tr["date"]) - pd.Timestamp(cur["date"])).days))
        cur = None

x = pd.DataFrame(rows)
print("trades:", len(x))
print(x.describe().round(2).to_string())
print("\nSpearman:")
for col in ["depth", "lead", "n_cand"]:
    s = x[[col, "ret"]].dropna()
    if len(s) >= 8:
        rho, p = spearmanr(s[col], s["ret"])
        print("  %-8s rho=%+.3f p=%.3f n=%d" % (col, rho, p, len(s)))

def bucket(col, q=3):
    s = x[[col, "ret"]].dropna().copy()
    if len(s) < 9:
        print("  %s 样本不足" % col); return
    s["bucket"] = pd.qcut(s[col], q, labels=False, duplicates="drop")
    g = s.groupby("bucket").agg(n=("ret", "size"), win=("ret", lambda v: (v > 0).mean()),
                                avg=("ret", "mean"), med=("ret", "median"),
                                lo=(col, "min"), hi=(col, "max"))
    print("\n== %s 分位分组 ==" % col)
    print(g.round(3).to_string())

for col in ["depth", "lead", "n_cand"]:
    bucket(col)

# 过滤组合：深度>中位 且 领先>中位
s = x.dropna(subset=["depth", "lead"]).copy()
if len(s) >= 12:
    md, ml = s["depth"].median(), s["lead"].median()
    f = s[(s["depth"] > md) & (s["lead"] > ml)]
    print("\n组合过滤: depth>%.2f 且 lead>%.2f -> %d 笔 | 胜率 %.1f%% | 均值 %+.2f%%"
          % (md, ml, len(f), (f.ret > 0).mean() * 100, f.ret.mean() * 100))
    print("全样本: %d 笔 | 胜率 %.1f%% | 均值 %+.2f%%"
          % (len(s), (s.ret > 0).mean() * 100, s.ret.mean() * 100))
