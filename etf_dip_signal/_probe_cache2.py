# -*- coding: utf-8 -*-
"""_probe_cache2.py —— 为什么 11-20 缓存里只有 231 只有当日行？"""
import json
import os

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)

pool = json.load(open("data/fixed_pool.json", encoding="utf-8"))
codes = [str(c) for c in pool["codes"]]

d = pd.read_parquet("data/kline_cache_cifang_2026-11-20.parquet")
d["code"] = d["code"].astype(str)
d["date"] = d["date"].astype(str).str[:10]
print("总行 %d ｜ 只数 %d" % (len(d), d.code.nunique()))
last = d.groupby("code")["date"].max()
print("\n每只最新日分布：")
print(last.value_counts().sort_index().to_string())
print("\n行数统计：min %d / median %d / max %d"
      % (d.groupby("code").size().min(), d.groupby("code").size().median(),
         d.groupby("code").size().max()))

miss = last[last < "2026-11-20"]
print("\n最新日 < 11-20 的 %d 只，示例：" % len(miss))
print(miss.head(20).to_string())

# 这些标的是不是停牌？用腾讯查 3 只
import tdx_api
sample = list(miss.index[:5])
if sample:
    rt = tdx_api.get_realtime(sample)
    print("\n抽 5 只查实时：")
    print(rt[["code", "name", "price", "last_close", "paused"]].to_string(index=False))

# 对照 11-19 缓存
d2 = pd.read_parquet("data/kline_cache_cifang_2026-11-19.parquet")
d2["code"] = d2["code"].astype(str)
d2["date"] = d2["date"].astype(str).str[:10]
last2 = d2.groupby("code")["date"].max()
print("\n11-19 缓存最新日分布：")
print(last2.value_counts().sort_index().to_string())
