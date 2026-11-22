# -*- coding: utf-8 -*-
"""阈值该不该细分？—— 诊断而非调参

做法：把每只 ETF 的历史按「20日乖离率」分桶，统计每个桶之后 10 个交易日的平均收益。
      再按该标的的波动率分成低/中/高三组，看「收益由负转正的临界乖离」是否随波动率单调移动。
若单调移动 ⇒ 分档有理论依据，可以细分；
若不移动 / 乱序 ⇒ 现在的 -16/-11/-5 只是运气，细分没有意义。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data_quality

FWD = 10          # 未来 10 个交易日
BINS = [-99, -30, -25, -20, -16, -12, -8, -4, 0, 99]
LABELS = ["<-30", "-30~-25", "-25~-20", "-20~-16", "-16~-12",
          "-12~-8", "-8~-4", "-4~0", ">0"]

d = json.load(open("data/fixed_pool.json", encoding="utf-8"))
codes = set(d["codes"])

raw = pd.read_parquet("data/etf_qfq_cifang.parquet",
                      columns=["code", "date", "open", "close", "low"])
raw["code"] = raw["code"].astype(str).str.zfill(6)
raw["date"] = raw["date"].astype(str).str[:10]
raw = raw[raw["code"].isin(codes)]

recs = []
for code, g in raw.groupby("code", sort=False):
    g = g.sort_values("date").reset_index(drop=True)
    if len(g) < 120:
        continue
    f, _ = data_quality.repair_prices(g[["date", "open", "close", "low"]])
    c = f["close"].astype(float)
    if (c <= 0).any():
        continue
    bias20 = (c / c.rolling(20).mean() - 1) * 100
    vol60 = c.pct_change().rolling(60).std() * 100
    fwd = c.shift(-FWD) / c - 1
    sub = pd.DataFrame({"bias20": bias20, "vol60": vol60, "fwd": fwd}).dropna()
    if len(sub) < 60:
        continue
    sub["code"] = code
    sub["v60"] = float(np.nanmedian(sub["vol60"]))
    recs.append(sub)

D = pd.concat(recs, ignore_index=True)
print("样本：%d 只 ｜ %d 个「股票-日」观测" % (D.code.nunique(), len(D)))

# 按每只标的自身波动率分位，划成低/中/高三组
q = D.groupby("code")["v60"].first().quantile([1 / 3, 2 / 3])
D["vgrp"] = np.where(D["v60"] <= q.iloc[0], "低波动",
                     np.where(D["v60"] <= q.iloc[1], "中波动", "高波动"))
print("分组阈值：低 ≤ %.2f%% ｜ 中 ≤ %.2f%% ｜ 高 > %.2f%%（日波动）"
      % (q.iloc[0], q.iloc[1], q.iloc[1]))

D["bucket"] = pd.cut(D["bias20"], bins=BINS, labels=LABELS)
tab = D.pivot_table(index="bucket", columns="vgrp", values="fwd",
                    aggfunc=["mean", "size"], observed=False)
mean_tab = tab["mean"] * 100
size_tab = tab["size"]

print("\n" + "=" * 92)
print("各乖离桶之后 %d 个交易日的平均收益（%%）" % FWD)
print("=" * 92)
print("%-10s %10s %10s %10s   %s" % ("乖离区间", "低波动", "中波动", "高波动", "样本量(低/中/高)"))
for lab in LABELS:
    r = mean_tab.loc[lab]
    n = size_tab.loc[lab]
    print("%-10s %9.3f%% %9.3f%% %9.3f%%   %d/%d/%d"
          % (lab, r["低波动"], r["中波动"], r["高波动"],
             n["低波动"], n["中波动"], n["高波动"]))

print("\n" + "=" * 92)
print("诊断：收益由负转正的「临界乖离」在哪？")
print("=" * 92)
for g in ("低波动", "中波动", "高波动"):
    s = mean_tab[g].dropna()
    pos = s[s > 0]
    if len(pos) == 0:
        print("  %-6s 全部区间为负" % g)
        continue
    first_pos = None
    for lab in LABELS:
        if lab in s.index and s[lab] > 0:
            first_pos = lab
            break
    print("  %-6s 首个正收益区间：%-10s （该区间 %+.3f%%）"
          % (g, first_pos, s[first_pos]))

print("\n说明：若三组的「首个正收益区间」几乎相同，说明临界点不随波动率移动，")
print("      则当前 -16/-11/-5 的分档缺乏统计支撑，细分更无意义。")
