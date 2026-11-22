# -*- coding: utf-8 -*-
"""容量测算：建仓日成交额 vs 单笔仓位"""
import pandas as pd
import numpy as np

tr = pd.read_csv("回测输出/trades_main_final.csv")
tr["code"] = tr["code"].astype(str).str.zfill(6)
buys = tr[tr["action"] == "buy"].copy()

amt = pd.read_parquet("data/etf_qfq_cifang.parquet",
                      columns=["code", "date", "amount"])
amt["code"] = amt["code"].astype(str).str.zfill(6)
amt["date"] = amt["date"].astype(str).str[:10]
am = amt.set_index(["code", "date"])["amount"]

rows = []
for r in buys.itertuples():
    d = str(r.date)[:10]
    try:
        a = float(am.loc[(r.code, d)])
    except Exception:
        continue
    rows.append((d, r.code, a, r.price * r.shares))
cap = pd.DataFrame(rows, columns=["date", "code", "amount", "pos"])
cap["pct"] = cap["pos"] / cap["amount"] * 100

print("建仓 %d 笔（有效 %d）" % (len(buys), len(cap)))
print("建仓日成交额：最小 %.0f 万 ｜ 中位 %.0f 万 ｜ 最大 %.0f 万"
      % (cap["amount"].min() / 1e4, cap["amount"].median() / 1e4,
         cap["amount"].max() / 1e4))
print("单笔仓位占当日成交额：中位 %.3f%% ｜ 最大 %.3f%%"
      % (cap["pct"].median(), cap["pct"].max()))
print("\n最拥挤 6 笔：")
print(cap.nlargest(6, "pct").to_string(index=False))
print("\n以「不超过当日成交额 1%」为约束，可容纳的单笔资金：")
print("  中位 %.0f 万元 ｜ 最小 %.0f 万元 ｜ 10%% 分位 %.0f 万元"
      % ((cap["amount"] * 0.01).median() / 1e4, (cap["amount"] * 0.01).min() / 1e4,
         (cap["amount"] * 0.01).quantile(0.1) / 1e4))
