# -*- coding: utf-8 -*-
"""
按资产类别检验阈值错配 + 跳空型过滤。

★ 必须复用 bt_etf_dip.build_matrices 与标准参数组合
  (max_hold=1, intraday_stop=True, exec_mode='close', timeout_live=True,
   trail=0.08, be_stop=0.03, cash_yield=0.025, slippage=0.002)
  否则基线对不上（自建矩阵会漏掉在世标的判定，跑出 13.96% 而非 38.46%）。
"""
import os
import sys
import json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

START, END = "2021-01-01", "2026-10-20"
SLIP = 0.002
TRAIL, BE, CY = 0.08, 0.03, 0.025

STD = dict(max_hold=1, intraday_stop=True, exec_mode="close", timeout_live=True,
           trail=TRAIL, be_stop=BE, cash_yield=CY, slippage=SLIP)


def group_of(sub, cls6):
    if sub in ('美股', '日本', '欧股'):
        return 'A_远洋'
    if sub in ('贵金属', '能化', '农产品', '其他'):
        return 'B_商品'
    if sub in ('港股', '中概', '新兴市场', '中东'):
        return 'C_近岸'
    if cls6 == '股票-股息红利':
        return 'D_红利'
    return 'E_A股'


def load():
    d = json.load(open("data/fixed_pool.json", encoding="utf-8"))
    bmap = {str(k): int(v) for k, v in d["bmap"].items()}
    cmap = d.get("cmap", {}); sc = d.get("subclass", {})
    gmap = {c: group_of(sc.get(c, ''), cmap.get(c, '')) for c in d["codes"]}

    raw = pd.read_parquet("data/etf_qfq_cifang.parquet",
                          columns=["code", "date", "open", "close", "low"])
    raw["date"] = raw["date"].astype(str).str[:10]
    hist = {}
    nb = 0
    for code, g in raw.groupby("code", sort=False):
        f, hits = data_quality.repair_prices(g[["date", "open", "close", "low"]])
        nb += len(hits)
        hist[code] = f.reset_index(drop=True)
    del raw
    print("[数据体检] 修正 %d 根跳变" % nb)
    m = bt1.build_matrices(hist, start=START, end=END)
    return m, bmap, gmap


def add_gap(m):
    """在矩阵上追加「近 5 日是否有跳空型大跌」掩码。
    跳空型大跌 = 当日跌幅 <= -2%，且开盘跳空占该日总跌幅 >= 60%。
    """
    C = m["close"]; O = m["open"]
    n, mm = C.shape
    prev = np.vstack([np.full((1, mm), np.nan), C[:-1]])
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = C / prev - 1.0
        gap = O / prev - 1.0
    hit = (dr <= -0.02) & (gap < 0) & (np.abs(gap) >= 0.6 * np.abs(dr))
    hit[~np.isfinite(dr) | ~np.isfinite(gap)] = False
    g5 = pd.DataFrame(hit.astype(float)).rolling(5, min_periods=1).max().to_numpy() > 0
    m["gap5"] = g5
    m["gap_hit"] = hit
    return m


def go(m, bmap, **kw):
    args = dict(STD); args.update(kw)
    r = bt.run(m, bmap, **args)
    p = bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])
    return r, p


def line(name, p, nbuy):
    wr = p["win_rate"] * 100 if np.isfinite(p["win_rate"]) else float("nan")
    print("%-26s %+8.2f%% %+8.2f%% %8.2f%% %7.2f %6.2f %5.1f%% %4d"
          % (name, p["total_return"] * 100, p["cagr"] * 100, p["max_dd"] * 100,
             p["calmar"], p["sharpe"], wr, nbuy))


def main():
    m, bmap, gmap = load()
    m = add_gap(m)
    codes = m["codes"]
    print("矩阵 %d 交易日 x %d 只 ｜ 跳空型大跌 %d 次"
          % (len(m["dates"]), len(codes), int(m["gap_hit"].sum())))
    print()

    def nb_of(r):
        t = r["trades"]
        return int((t["action"] == "buy").sum()) if len(t) else 0

    # ---------- 0. 基线 + 各组买入分布 ----------
    r0, p0 = go(m, bmap)
    print("=" * 108)
    print("【0】当前配置：各组历史买入分布（所有变体的前提）")
    print("=" * 108)
    tr = r0["trades"]
    buys = tr[tr["action"] == "buy"].copy()
    buys["grp"] = buys["code"].astype(str).str.zfill(6).map(gmap)
    cnt = buys["grp"].value_counts()
    print("  总买入 %d 笔" % len(buys))
    for g in sorted(set(gmap.values())):
        c = int(cnt.get(g, 0))
        print("    %-8s %3d 笔 (%2.0f%%)" % (g, c, 100.0 * c / max(len(buys), 1)))
    print()
    print("%-26s %9s %9s %9s %7s %6s %6s %4s"
          % ("", "总收益", "年化", "回撤", "Calmar", "夏普", "胜率", "笔数"))
    print("-" * 108)
    line("基准（现状）", p0, nb_of(r0))
    print()

    # ---------- 1. 阈值变体 ----------
    print("=" * 108)
    print("【1】按类别的阈值调整（每个都来自类别统计的先验）")
    print("=" * 108)
    print("%-26s %9s %9s %9s %7s %6s %6s %4s"
          % ("变体", "总收益", "年化", "回撤", "Calmar", "夏普", "胜率", "笔数"))
    print("-" * 108)

    def th_of(fn):
        out = {}
        for c in codes:
            base = bmap.get(c, -16)
            out[c] = fn(c, base)
        return out

    variants = [
        ("a1 剔除商品(5只)", lambda c, b: b if gmap[c] != 'B_商品' else 999),
        ("a2 商品 -11→-16", lambda c, b: -16 if gmap[c] == 'B_商品' else b),
        ("a3 商品 -11→-20", lambda c, b: -20 if gmap[c] == 'B_商品' else b),
        ("b1 港股 -16→-11", lambda c, b: -11 if gmap[c] == 'C_近岸' else b),
        ("b2 港股 -16→-13", lambda c, b: -13 if gmap[c] == 'C_近岸' else b),
        ("b3 港股 -16→-20", lambda c, b: -20 if gmap[c] == 'C_近岸' else b),
        ("c1 远洋 -11→-14", lambda c, b: -14 if gmap[c] == 'A_远洋' else b),
        ("c2 远洋 -11→-8", lambda c, b: -8 if gmap[c] == 'A_远洋' else b),
        ("d1 红利 -5→-8", lambda c, b: -8 if gmap[c] == 'D_红利' else b),
        ("d2 红利 -5→-11", lambda c, b: -11 if gmap[c] == 'D_红利' else b),
        ("e1 远洋+商品→-16", lambda c, b: -16 if gmap[c] in ('A_远洋', 'B_商品') else b),
        ("e2 全部非A股→-11", lambda c, b: -11 if gmap[c] != 'E_A股' else b),
    ]
    store = {}
    for name, fn in variants:
        th = th_of(fn)
        r, p = go(m, th)
        store[name] = (r, p)
        line(name, p, nb_of(r))
    print()

    # ---------- 2. 跳空型过滤 ----------
    print("=" * 108)
    print("【2】跳空型大跌过滤（新维度）")
    print("=" * 108)
    print("%-26s %9s %9s %9s %7s %6s %6s %4s"
          % ("变体", "总收益", "年化", "回撤", "Calmar", "夏普", "胜率", "笔数"))
    print("-" * 108)
    line("基准（不过滤）", p0, nb_of(r0))
    g5 = m["gap5"]
    for name, mask in (("g1 仅跳空型可买", g5),
                       ("g2 仅盘中型可买(反向)", ~g5)):
        r, p = go(m, bmap, liq=mask)
        store[name] = (r, p)
        line(name, p, nb_of(r))
    print()

    # ---------- 3. 跳空过滤 × 最优阈值变体 ----------
    print("=" * 108)
    print("【3】组合：跳空过滤 + 各类最优阈值")
    print("=" * 108)
    print("%-26s %9s %9s %9s %7s %6s %6s %4s"
          % ("变体", "总收益", "年化", "回撤", "Calmar", "夏普", "胜率", "笔数"))
    print("-" * 108)
    for tname in [k for k in store if k.startswith(('a3', 'b3', 'c1', 'd2'))][:4]:
        r, p = go(m, th_of(dict(variants)[tname]), liq=g5)
        line(tname + " + 跳空", p, nb_of(r))
    print()

    # ---------- 4. 稳健性：剔最强年 ----------
    print("=" * 108)
    print("【4】稳健性：剔除最强年后重算（判断是否靠单一年份）")
    print("=" * 108)

    def drop_best(p_eq):
        e = p_eq.copy()
        r = e.pct_change().dropna()
        yr = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
        if len(yr) < 3:
            return float("nan"), None
        best = yr.idxmax()
        keep = r[r.index.year != best]
        tot = (1 + keep).prod() - 1
        days = len(keep)
        cg = (1 + tot) ** (244.0 / days) - 1 if days > 0 else float("nan")
        return cg, best

    for name in ["基准（现状）", "a3 商品 -11→-20", "b3 港股 -16→-20",
                 "c1 远洋 -11→-14", "d2 红利 -5→-11", "g1 仅跳空型可买"]:
        if name == "基准（现状）":
            r, p = r0, p0
        elif name in store:
            r, p = store[name]
        else:
            continue
        cg, best = drop_best(r["equity"])
        print("  %-24s 剔 %s 后年化 %+7.2f%%（原 %+.2f%%，落差 %.2fpp）"
              % (name, best, cg * 100, p["cagr"] * 100, (p["cagr"] - cg) * 100))
    print()

    # 明细落盘
    os.makedirs("回测输出", exist_ok=True)
    pd.DataFrame([
        {"variant": k, "cagr": v[1]["cagr"], "max_dd": v[1]["max_dd"],
         "calmar": v[1]["calmar"], "sharpe": v[1]["sharpe"],
         "total": v[1]["total_return"], "trades": nb_of(v[0])}
        for k, v in store.items()
    ]).to_csv("回测输出/diag_byclass_variants.csv", index=False, encoding="utf-8-sig")
    print("已写出 回测输出/diag_byclass_variants.csv")


if __name__ == "__main__":
    main()
