# -*- coding: utf-8 -*-
"""_verify_lineC.py —— 线C 数字变动归因（39.76% → 34.50% 到底是谁造成的）

三个变量必须分离：
  V1 窗口：2021-01-04~2026-11-04（旧）vs 2021-01-04~2026-11-20（新，多 16 天）
  V2 数据：all_etf_1119（旧库）vs all_etf_1120（新库，修复算法改进 + 多一天）
  V3 成本：0.2% / 0.3% / 0.5% 三档，用新库新窗口重算

不分离清楚，任何「策略变好了/变坏了」的结论都是错的。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import bt_etf_dip as bt
import bt_multi as bm
import data_quality
import _p4_band as pb

codes, bmap = pb.load_pool_codes()


def load(path):
    df = pd.read_parquet(path)
    df["code"] = df["code"].astype(str)
    df["date"] = df["date"].astype(str).str[:10]
    sub = df[df.code.isin(set(codes))]
    hist, fixed = {}, 0
    for c, g in sub.groupby("code"):
        s = g[["date", "open", "high", "low", "close", "volume"]].copy()
        s = s.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        s2, hits = data_quality.repair_prices(s)
        fixed += len(hits)
        hist[c] = s2
    return hist, fixed


def run(hist, start, end, slip=None, comm=None):
    m = bt.build_matrices(hist, start=start, end=end)
    kw = dict(max_hold=1, intraday_stop=True, exec_mode="close", timeout_live=True)
    if slip is not None:
        kw["slippage"] = slip
    if comm is not None:
        kw["commission"] = comm
    r = bm.run(m, bmap, **kw)
    eq = pd.Series(r["equity"]).dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    t = r["trades"]
    ntr = int((t["action"] != "buy").sum()) if isinstance(t, pd.DataFrame) and len(t) else 0
    win = float((t.loc[t["action"] != "buy", "ret"] > 0).mean()) if ntr else np.nan
    return dict(cagr=cagr * 100, dd=dd * 100, n=ntr, win=win, eq=eq)


print("=" * 92)
print("线C 数字归因")
print("=" * 92)

h_old, f_old = load("data/all_etf_1119.parquet")
h_new, f_new = load("data/all_etf_1120.parquet")
print("旧库 %d 只 / 修复 %d 根 ｜ 新库 %d 只 / 修复 %d 根"
      % (len(h_old), f_old, len(h_new), f_new))

rows = []
for tag, h, s, e in [
    ("旧库 · 旧窗口 2021~2026-11-04", h_old, "2021-01-04", "2026-11-04"),
    ("旧库 · 新窗口 2021~2026-11-20", h_old, "2021-01-04", "2026-11-20"),
    ("新库 · 旧窗口 2021~2026-11-04", h_new, "2021-01-04", "2026-11-04"),
    ("新库 · 新窗口 2021~2026-11-20", h_new, "2021-01-04", "2026-11-20"),
    ("新库 · 新窗口 2022~2026-11-20", h_new, "2022-01-01", "2026-11-20"),
    ("新库 · 新窗口 2023~2026-11-20", h_new, "2023-01-01", "2026-11-20"),
]:
    r = run(h, s, e)
    print("  %-32s 年化 %+7.2f%% ｜ 回撤 %7.2f%% ｜ 平仓 %3d ｜ 胜率 %5.1f%%"
          % (tag, r["cagr"], r["dd"], r["n"], (r["win"] or 0) * 100))
    rows.append((tag, r))

print("\n【拆解】")
a = rows[0][1]
b = rows[3][1]
print("  旧库旧窗口 → 新库新窗口：%+.2f%% → %+.2f%%（合计 %+.2fpp）"
      % (a["cagr"], b["cagr"], b["cagr"] - a["cagr"]))
print("  其中窗口延长贡献：%+.2fpp"
      % (rows[1][1]["cagr"] - a["cagr"]))
print("  其中数据修复贡献：%+.2fpp"
      % (rows[2][1]["cagr"] - a["cagr"]))
print("  两者交互：%+.2fpp"
      % (b["cagr"] - a["cagr"] - (rows[1][1]["cagr"] - a["cagr"])
         - (rows[2][1]["cagr"] - a["cagr"])))

print("\n【成本阶梯】新库 · 2021~2026-11-20")
base = rows[3][1]
for slip, comm, tag in [(0.0, 0.0, "零成本"),
                        (0.0, 0.0001, "仅佣金万1"),
                        (0.001, 0.0002, "现行：万2 + 滑点0.1%"),
                        (0.002, 0.0002, "2tick：万2 + 滑点0.2%"),
                        (0.003, 0.0002, "3tick：万2 + 滑点0.3%"),
                        (0.005, 0.0002, "5tick：万2 + 滑点0.5%")]:
    r = run(h_new, "2021-01-04", "2026-11-20", slip=slip, comm=comm)
    print("  %-26s 年化 %+7.2f%%（%+6.2fpp）｜ 回撤 %7.2f%% ｜ 平仓 %3d"
          % (tag, r["cagr"], r["cagr"] - base["cagr"], r["dd"], r["n"]))

print("\n【胜率敏感性】新库 · 2021~2026-11-20 · 剔除最好的 k 笔")
eq = base["eq"]
m = bt.build_matrices(h_new, start="2021-01-04", end="2026-11-20")
r = bm.run(m, bmap, max_hold=1, intraday_stop=True, exec_mode="close", timeout_live=True)
t = r["trades"]
closed = t[t["action"] != "buy"].copy() if isinstance(t, pd.DataFrame) else pd.DataFrame()
if len(closed):
    closed = closed.sort_values("ret", ascending=False)
    print("  %-18s %8s %8s %8s" % ("剔除最好 k 笔", "年化", "胜率", "回撤"))
    for k in [0, 1, 2, 3, 5]:
        keep = closed.iloc[k:]
        n = len(keep)
        w = float((keep["ret"] > 0).mean()) if n else np.nan
        # 用「等比缩放每笔收益」的近似：把被剔除的收益从最终净值里扣掉
        # 更严谨：直接重跑并屏蔽这些交易不可行，这里只报胜率与收益集中度
        tot = float((1 + closed["ret"]).prod())
        kept = float((1 + keep["ret"]).prod())
        print("  %-18d 收益占比 %5.1f%% ｜ 胜率 %5.1f%% ｜ 剩余笔数 %d"
              % (k, (1 - kept / tot) * 100, w * 100, n))
