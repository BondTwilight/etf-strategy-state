# -*- coding: utf-8 -*-
"""复权口径体检：分时库 vs 日线库 的逐日收益一致性"""
import os
import warnings

import pandas as pd

warnings.filterwarnings("ignore")
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

i45 = pd.read_parquet(os.path.join(DATA, "all_etf_1445.parquet"))
i45["code"] = i45["code"].astype(str)
d = pd.read_parquet(os.path.join(DATA, "all_etf_1120.parquet"))
d["code"] = d["code"].astype(str)
d["date"] = pd.to_datetime(d["date"].astype(str).str[:10])

rows = []
for c in sorted(set(i45["code"]) & set(d["code"])):
    a = i45[i45.code == c].set_index("date")["close"].sort_index()
    b = d[d.code == c].set_index("date")["close"].sort_index()
    if len(a) < 30 or len(b) < 30:
        continue
    j = pd.concat([a.pct_change().rename("i"), b.pct_change().rename("d")],
                  axis=1, sort=True).dropna()
    if not len(j):
        continue
    diff = (j["i"] - j["d"]).abs()
    k = diff.idxmax()
    rows.append([c, len(j), float(diff.max()) * 100,
                 float(j.loc[k, "i"]) * 100, float(j.loc[k, "d"]) * 100,
                 k.strftime("%Y-%m-%d")])

r = pd.DataFrame(rows, columns=["code", "n", "maxdiff_pct", "i_ret", "d_ret", "date"])
r = r.sort_values("maxdiff_pct", ascending=False)
print("逐日收益最大偏差 Top 10（14:45 库 vs 日线 qfq）")
print(r.head(10).to_string(index=False))
print()
print("偏差 >2pp 的标的数：{} / {}".format(int((r["maxdiff_pct"] > 2).sum()), len(r)))
print("偏差 >5pp 的标的数：{}".format(int((r["maxdiff_pct"] > 5).sum())))

bad = 0
worst = None
for c, g in i45.groupby("code"):
    s = g.set_index("date")["close"].sort_index()
    rr = s.pct_change().dropna()
    if not len(rr):
        continue
    if rr.min() < -0.15 or rr.max() > 0.15:
        bad += 1
        if worst is None or rr.min() < worst[2]:
            worst = (c, rr.idxmin().strftime("%Y-%m-%d"), float(rr.min()) * 100)
print("14:45 库内 |单日涨跌| >15% 的标的数：{}".format(bad))
if worst:
    print("   最差：{}  {}  {:+.2f}%".format(*worst))
