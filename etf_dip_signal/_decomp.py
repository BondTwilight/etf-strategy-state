# -*- coding: utf-8 -*-
"""归因：按阈值档 / 按标的聚合交易贡献，并对比 V1 vs V2 的止损行为。"""
import os, json
import pandas as pd

pool = json.load(open("data/fixed_pool.json", encoding="utf-8"))
bmap = {str(k): int(v) for k, v in pool["bmap"].items()}
cmap = {str(k): v for k, v in pool["cmap"].items()}

for tag, label in (("main", "主窗口2021+"), ("long", "长窗口2016+")):
    print("=" * 88)
    print(label)
    for v in ("V1", "V2"):
        d = pd.read_csv(os.path.join("回测输出", "trades_%s_%s.csv" % (tag, v)))
        s = d[d.action == "sell"].copy()
        s["ret"] = pd.to_numeric(s["ret"], errors="coerce")
        s["th"] = s["code"].astype(str).map(bmap)
        s["cls"] = s["code"].astype(str).map(cmap)
        print("\n-- %s 按阈值档 --" % v)
        g = s.groupby("th")["ret"].agg(笔数="count", 均值="mean", 合计="sum", 最差="min")
        g["均值"] = (g["均值"] * 100).round(2)
        g["合计"] = (g["合计"] * 100).round(1)
        g["最差"] = (g["最差"] * 100).round(2)
        print(g.to_string())
        print("-- %s 按大类 --" % v)
        g2 = s.groupby("cls")["ret"].agg(笔数="count", 均值="mean", 合计="sum")
        g2["均值"] = (g2["均值"] * 100).round(2)
        g2["合计"] = (g2["合计"] * 100).round(1)
        print(g2.sort_values("合计", ascending=False).to_string())
        if v == "V2":
            print("-- 卖出原因分布 --")
            print(s.groupby("reason")["ret"].agg(笔数="count", 均值="mean").assign(
                均值=lambda x: (x["均值"] * 100).round(2)).to_string())
            st = s[s.reason.str.contains("止损")]
            if len(st):
                print("   止损笔数=%d 止损年份分布=%s" % (
                    len(st), st["date"].str[:4].value_counts().sort_index().to_dict()))
        else:
            print("-- 卖出原因分布 --")
            print(s.groupby("reason")["ret"].agg(笔数="count", 均值="mean").assign(
                均值=lambda x: (x["均值"] * 100).round(2)).to_string())
        print()
