# -*- coding: utf-8 -*-
"""_probe_cache.py —— 每日缓存覆盖率 + 乖离率口径污染量化

1. 每个 kline_cache_cifang_*.parquet 覆盖多少只（暴露「次方抓取部分失败」的频率）
2. 用次方今天全量重算 11-20 的 20/50 日乖离，与 latest.txt 的 TOP10 逐一对比
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

pool = json.load(open("data/fixed_pool.json", encoding="utf-8"))
codes = [str(c) for c in pool["codes"]]
bmap = {str(k): int(v) for k, v in pool["bmap"].items()}
names = {str(k): v for k, v in (pool.get("name") or {}).items()}
print("[1] 每日缓存覆盖只数（池子 %d 只）" % len(codes))
for f in sorted(glob.glob("data/kline_cache_cifang_*.parquet")):
    try:
        d = pd.read_parquet(f, columns=["code"])
        n = d["code"].astype(str).nunique()
        inpool = len(set(d["code"].astype(str)) & set(codes))
        print("   %-46s %4d 只（池内 %3d，%5.1f%%）"
              % (os.path.basename(f), n, inpool, 100.0 * inpool / len(codes)))
    except Exception as e:
        print("   %-46s ERR %s" % (os.path.basename(f), e))

# ---------- 2. 用次方全量重算 11-20 乖离 ----------
print("\n[2] 次方全量重算 11-20 乖离 vs latest.txt")
import cifang_quote
cache = "data/kline_cache_cifang_2026-11-20.parquet"
d = pd.read_parquet(cache)
d["code"] = d["code"].astype(str)
d["date"] = d["date"].astype(str).str[:10]
cached_codes = set(d["code"])
print("   缓存内 %d 只；池内 %d 只"
      % (len(cached_codes), len(cached_codes & set(codes))))

# 全量缓存（今天已实测 381/381 可取；为了不重复打接口，直接用 cifang_quote 单只补拉）
import cifang_api
raw = cifang_api.hist_em(codes, "2026-03-01", "2026-11-21", adjust="qfq")
rows = []
for c in codes:
    df = raw.get(c)
    if df is None or len(df) < 51:
        continue
    x = df.copy()
    x["date"] = x["date"].astype(str).str[:10]
    x = x.sort_values("date")
    close = x["close"].astype(float).values
    dates = x["date"].values
    if dates[-1] != "2026-11-20":
        continue
    # 20日乖离 = close/MA20-1；50日乖离 = close/MA50-1（与 indicators 口径一致：含当日）
    ma20 = close[-20:].mean()
    ma50 = close[-50:].mean()
    rows.append({"code": c, "b20": (close[-1] / ma20 - 1) * 100,
                 "b50": (close[-1] / ma50 - 1) * 100, "close": close[-1]})
b = pd.DataFrame(rows).sort_values("b50")
print("   算出 %d 只（要求 11-20 有数据且 ≥51 根）" % len(b))

# latest.txt TOP10（11-20 输出）
lit = [("515880", -32.33, -13.92), ("159967", -29.50, -11.26), ("588020", -28.51, -11.62),
       ("159243", -28.30, -13.74), ("159259", -28.29, -11.47), ("159597", -25.47, -10.45),
       ("588850", -25.24, -14.89), ("159367", -24.15, -10.24), ("563210", -24.00, -11.37),
       ("588030", -22.39, -11.62)]
print("\n   代码     名称              线上b50   重算b50   差(pp)   线上b20   重算b20   差(pp)")
bmap_idx = b.set_index("code")
diffs50, diffs20 = [], []
for c, o50, o20 in lit:
    if c not in bmap_idx.index:
        print("   %s 重算缺失" % c)
        continue
    n50 = bmap_idx.loc[c, "b50"]
    n20 = bmap_idx.loc[c, "b20"]
    diffs50.append(n50 - o50)
    diffs20.append(n20 - o20)
    print("   %-8s %-16s %8.2f %9.2f %8.2f %8.2f %9.2f %8.2f"
          % (c, names.get(c, "")[:16], o50, n50, n50 - o50, o20, n20, n20 - o20))
if diffs50:
    print("   |Δb50| 中位 %.2fpp / 最大 %.2fpp ｜ |Δb20| 中位 %.2fpp / 最大 %.2fpp"
          % (np.median(np.abs(diffs50)), np.max(np.abs(diffs50)),
             np.median(np.abs(diffs20)), np.max(np.abs(diffs20))))

# ---------- 3. 候选 159100 ----------
print("\n[3] 候选 159100 巴西ETF")
if "159100" in bmap_idx.index:
    r = bmap_idx.loc["159100"]
    print("   重算 b50=%.2f b20=%.2f ｜ 线上 b50=-21.33 b20=-10.52 ｜ 阈值 %s"
          % (r["b50"], r["b20"], bmap.get("159100")))
else:
    print("   重算缺失（次方未返回或不足 51 根）")

b.to_csv("data/_recalc_bias_1120.csv", index=False, encoding="utf-8-sig")
print("\n   已存 data/_recalc_bias_1120.csv")
