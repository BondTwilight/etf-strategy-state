# -*- coding: utf-8 -*-
"""深度评估计算：
A. 最终配置（trail8 + be3 + 计息2.5）逐笔导出，供与聚宽对账
B. 移动止盈参数平台扫描（判断 8% 是尖峰还是平台）
C. 保本止损参数平台
D. 交易成本敏感性（滑点 / 佣金）
E. 前后段切分 + 分年
F. 容量测算（按当日成交额）
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_etf_dip as bt1
import bt_multi as bt
import cifang_api
import data_quality

t0 = time.time()
d = json.load(open("data/fixed_pool.json", encoding="utf-8"))
CODES, BMAP = d["codes"], {str(k): int(v) for k, v in d["bmap"].items()}
hist = cifang_api.fetch_pool_history(CODES, cache_path="data/etf_qfq_cifang.parquet")
hist, _ = data_quality.audit(hist, verbose=False)

FINAL = dict(trail=0.08, be_stop=0.03, cash_yield=0.025)


def go(m, **kw):
    r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True, **kw)
    p = bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])
    return r, p


def line(name, p, extra=""):
    wr = p["win_rate"] * 100 if np.isfinite(p["win_rate"]) else float("nan")
    print("  %-26s %8.2f%% %8.2f%% %7.2f %7.2f %7.1f%% %5d %s"
          % (name, p["cagr"] * 100, p["max_dd"] * 100, p["calmar"],
             p["sharpe"], wr, p["trades"], extra))


m = bt1.build_matrices(hist, start="2021-01-01", end="2026-10-20")

print("=" * 118)
print("A. 最终配置逐笔导出")
print("=" * 118)
r, p = go(m, **FINAL)
line("最终配置", p)
tr = pd.DataFrame(r["trades"]).copy()
if "action" not in tr.columns:
    tr = pd.DataFrame(list(r["trades"]))
os.makedirs("回测输出", exist_ok=True)
tr.to_csv("回测输出/trades_main_final.csv", index=False, encoding="utf-8-sig")
print("  已写出 回测输出/trades_main_final.csv（%d 条）" % len(tr))
print("  卖出分布:", dict(tr[tr["action"] == "sell"]["reason"].value_counts()))
r["trades"] = tr.to_dict("records")

eq = p["equity"]
ret = eq.pct_change().fillna(0.0)
print("\n  【分年】")
for y, s in ret.groupby(ret.index.year):
    e = (1 + s).prod() - 1
    dd = ((1 + s).cumprod() / (1 + s).cumprod().cummax() - 1).min()
    print("    %d  %+7.2f%%  年内回撤 %6.2f%%" % (y, e * 100, dd * 100))

print("\n  【前后段】")
for tag, s in [("2021-2023", eq[eq.index < "2024-01-01"]),
               ("2024-2026", eq[eq.index >= "2024-01-01"])]:
    y = (s.index[-1] - s.index[0]).days / 365.25
    c = (s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1
    dd = (s / s.cummax() - 1).min()
    print("    %-10s 年化 %+7.2f%%  回撤 %7.2f%%" % (tag, c * 100, dd * 100))

print("\n" + "=" * 118)
print("B. 移动止盈：参数平台扫描（保本3% 固定）")
print("=" * 118)
print("  %-26s %9s %9s %8s %8s %8s %6s" % ("", "年化", "回撤", "Calmar", "夏普", "胜率", "交易"))
base = dict(be_stop=0.03, cash_yield=0.025)
line("不启用移动止盈", go(m, **base)[1])
for tv in [0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.12, 0.15]:
    kw = dict(base, trail=tv)
    line("trail=%.0f%%" % (tv * 100), go(m, **kw)[1])

print("\n" + "=" * 118)
print("C. 保本止损：参数平台（trail 8% 固定）")
print("=" * 118)
for bv in [None, 0.02, 0.03, 0.05, 0.08]:
    kw = dict(trail=0.08, cash_yield=0.025)
    if bv is not None:
        kw["be_stop"] = bv
    line("be=%s" % ("关闭" if bv is None else "%.0f%%" % (bv * 100)), go(m, **kw)[1])

print("\n" + "=" * 118)
print("D. 成本敏感性（最终配置）")
print("=" * 118)
for sl in [0.0, 0.001, 0.002, 0.003, 0.005, 0.008, 0.010]:
    kw = dict(FINAL, slippage=sl)
    line("滑点 %.1f%%" % (sl * 100), go(m, **kw)[1])
for cm in [0.0002, 0.0005, 0.001]:
    kw = dict(FINAL, commission=cm)
    line("佣金 %.2f%%" % (cm * 100), go(m, **kw)[1])

print("\n" + "=" * 118)
print("F. 容量测算（最终配置的建仓日成交额）")
print("=" * 118)
amt = hist[["code", "date", "amount"]].copy()
amt["date"] = pd.to_datetime(amt["date"])
amt = amt.set_index(["code", "date"])["amount"]
rows = []
for t in r["trades"]:
    if t["action"] != "buy":
        continue
    dt = pd.Timestamp(t["date"])
    try:
        a = float(amt.loc[(t["code"], dt)])
    except Exception:
        continue
    rows.append((t["date"], t["code"], a, t["price"] * t["shares"]))
cap = pd.DataFrame(rows, columns=["date", "code", "amount", "position"])
cap["pct_of_adv"] = cap["position"] / cap["amount"] * 100
print("  建仓笔数 %d" % len(cap))
print("  当日成交额：中位 %.0f 万元 ｜ 最小 %.0f 万元" % (cap["amount"].median() / 1e4,
                                                         cap["amount"].min() / 1e4))
print("  10 万仓位占成交额：中位 %.2f%% ｜ 最大 %.2f%%" % (cap["pct_of_adv"].median(),
                                                          cap["pct_of_adv"].max()))
print("  最拥挤 5 笔：")
print(cap.nlargest(5, "pct_of_adv")[["date", "code", "amount", "position", "pct_of_adv"]]
      .to_string(index=False))
print("  以「不超过当日成交额 1%」为容量上限，本策略可容纳资金：中位 %.0f 万元 ｜ 最小 %.0f 万元"
      % ((cap["amount"] * 0.01).median() / 1e4, (cap["amount"] * 0.01).min() / 1e4))

print("\n总耗时 %.0fs" % (time.time() - t0))
