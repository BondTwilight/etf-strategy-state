# -*- coding: utf-8 -*-
"""
按原始阈值严格分组，重做类别阈值检验。

★ 铁律：分组必须同时满足「同一 cmap」+「同一原始阈值」，
  否则变体会改到组外标的（上一版就栽在这：把 5 只宽基 + 2 只黄金股
  误当商品、把 27 只 -16 档红利误当 -5 档）。

分组（必须与原 bmap 完全一致）：
  商品  = cmap=='商品'                 → 5 只，原 -11
  远洋  = subclass in (美股,日本,欧股)   → 25 只，原 -11（需校验）
  近岸  = cmap=='跨境' & 原 -16         → 57 只
  红利  = 原 -5                         → 10 只
  A股   = 原 -16 & cmap!='跨境'         → 其余
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
STD = dict(max_hold=1, intraday_stop=True, exec_mode="close", timeout_live=True,
           trail=0.08, be_stop=0.03, cash_yield=0.025, slippage=SLIP)


def load():
    d = json.load(open("data/fixed_pool.json", encoding="utf-8"))
    bmap = {str(k): int(v) for k, v in d["bmap"].items()}
    cmap = d.get("cmap", {}); sc = d.get("subclass", {}); nm = d.get("name", {})

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
    return m, bmap, cmap, sc, nm


def groups(bmap, cmap, sc):
    """严格分组：返回 {组名: [codes]}，每组内原始阈值一致。"""
    g = {"商品": [], "远洋": [], "近岸": [], "红利": [], "A股": []}
    for c, th in bmap.items():
        s = sc.get(c, "")
        if cmap.get(c) == "商品":
            g["商品"].append(c)
        elif s in ("美股", "日本", "欧股"):
            g["远洋"].append(c)
        elif cmap.get(c) == "跨境" and th == -16:
            g["近岸"].append(c)
        elif th == -5:
            g["红利"].append(c)
        elif th == -16:
            g["A股"].append(c)
        else:
            g.setdefault("未归类", []).append(c)
    return g


def go(m, bmap, **kw):
    a = dict(STD); a.update(kw)
    r = bt.run(m, bmap, **a)
    return r, bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])


def nb_of(r):
    t = r["trades"]
    return int((t["action"] == "buy").sum()) if len(t) else 0


HDR = "%-28s %9s %9s %9s %7s %6s %6s %4s" % ("", "总收益", "年化", "回撤",
                                             "Calmar", "夏普", "胜率", "笔数")


def line(name, p, n):
    wr = p["win_rate"] * 100 if np.isfinite(p["win_rate"]) else float("nan")
    print("%-28s %+8.2f%% %+8.2f%% %8.2f%% %7.2f %6.2f %5.1f%% %4d"
          % (name, p["total_return"] * 100, p["cagr"] * 100, p["max_dd"] * 100,
             p["calmar"], p["sharpe"], wr, n))


def slice_m(m, lo, hi):
    """按日期切片（指标已用全历史算好，切行不引入未来数据）。"""
    d = pd.to_datetime(m["dates"])
    mask = (d >= pd.Timestamp(lo)) & (d <= pd.Timestamp(hi))
    idx = np.where(mask)[0]
    out = {}
    for k in ("open", "close", "low", "close_raw", "bias20", "bias50", "bmin5",
              "valid", "amount", "gap5", "gap_hit"):
        if k in m:
            v = m[k]
            out[k] = v[idx] if hasattr(v, "shape") and v.shape[0] == len(d) else v
    out["dates"] = np.array(m["dates"])[idx]
    out["codes"] = m["codes"]
    return out


def main():
    m, bmap, cmap, sc, nm = load()
    g = groups(bmap, cmap, sc)

    print()
    print("=" * 104)
    print("【分组校验】每组必须同 cmap 同原始阈值")
    print("=" * 104)
    for k in ("商品", "远洋", "近岸", "红利", "A股", "未归类"):
        v = g.get(k, [])
        if not v:
            continue
        ths = sorted({bmap[c] for c in v})
        cms = sorted({cmap.get(c, '?') for c in v})
        print("  %-6s %3d 只  阈值 %s  cmap %s" % (k, len(v), ths, cms))
        if len(ths) > 1:
            print("    ⚠️ 阈值不统一，变体会污染！")
    print()
    print("  商品明细:", ", ".join("%s(%s)" % (c, nm.get(c, '')) for c in g["商品"]))
    print("  红利明细:", ", ".join("%s(%s)" % (c, nm.get(c, '')) for c in g["红利"]))
    print()

    # ---------- 基线 ----------
    r0, p0 = go(m, bmap)
    print("=" * 104)
    print("【0】基线")
    print("=" * 104)
    print(HDR); print("-" * 104)
    line("基准（现状）", p0, nb_of(r0))
    tr = r0["trades"]
    buys = tr[tr["action"] == "buy"].copy()
    buys["code"] = buys["code"].astype(str).str.zfill(6)
    rev = {c: k for k, v in g.items() for c in v}
    buys["grp"] = buys["code"].map(rev)
    print()
    print("  买入分布:", dict(buys["grp"].value_counts()))
    print()

    # ---------- 1. 单组变体 ----------
    print("=" * 104)
    print("【1】单组阈值变体（每次只改一组，组内原阈值统一）")
    print("=" * 104)
    print(HDR); print("-" * 104)
    line("基准（现状）", p0, nb_of(r0))

    def th_only(grp, newth):
        out = dict(bmap)
        for c in g[grp]:
            out[c] = newth
        return out

    def th_drop(grp):
        out = dict(bmap)
        for c in g[grp]:
            out[c] = -999          # 永不可买（不能用 +999：负乖离永远 < 999）
        return out

    store = {}
    plans = []
    for th in (-14, -16, -18, -20, -25):
        plans.append(("商品 →%d" % th, th_only("商品", th)))
    plans.append(("剔除商品(5只)", th_drop("商品")))
    for th in (-11, -13, -18, -20):
        plans.append(("近岸(港股57) →%d" % th, th_only("近岸", th)))
    for th in (-8, -13, -14, -16):
        plans.append(("远洋(25) →%d" % th, th_only("远洋", th)))
    for th in (-3, -8, -11):
        plans.append(("红利(10) →%d" % th, th_only("红利", th)))
    for th in (-13, -20):
        plans.append(("A股(其余) →%d" % th, th_only("A股", th)))

    for name, th in plans:
        r, p = go(m, th)
        store[name] = (r, p, th)
        line(name, p, nb_of(r))
    print()

    # ---------- 2. walk-forward：商品阈值 ----------
    print("=" * 104)
    print("【2】walk-forward：商品阈值（拟合 2021-2023 / 检验 2024-2026）")
    print("=" * 104)
    mf = slice_m(m, "2021-01-01", "2023-12-31")
    mh = slice_m(m, "2024-01-01", "2026-10-20")
    cands = [-11, -16, -18, -20, -25]
    print("%-12s %14s %14s %14s" % ("商品阈值", "拟合段年化", "检验段年化", "全段年化"))
    print("-" * 104)
    base_f = go(mf, bmap)[1]["cagr"] * 100
    base_h = go(mh, bmap)[1]["cagr"] * 100
    print("%-12s %13.2f%% %13.2f%% %13.2f%%"
          % ("-11 (现状)", base_f, base_h, p0["cagr"] * 100))
    wf = []
    for th in cands:
        if th == -11:
            continue
        t = th_only("商品", th)
        cf = go(mf, t)[1]["cagr"] * 100
        ch = go(mh, t)[1]["cagr"] * 100
        ca = go(m, t)[1]["cagr"] * 100
        print("%-12s %13.2f%% %13.2f%% %13.2f%%"
              % (str(th), cf, ch, ca))
        wf.append((th, cf - base_f, ch - base_h, ca - p0["cagr"] * 100))
    print()
    print("  相对基准的增量：")
    for th, df, dh, da in wf:
        flag = "✅ 两段同向" if (df > 0 and dh > 0) else (
            "⚠️ 方向不一致" if (df > 0) != (dh > 0) else "❌ 两段同负")
        print("    商品%-5s 拟合 %+6.2fpp  检验 %+6.2fpp  全段 %+6.2fpp  %s"
              % (th, df, dh, da, flag))
    print()

    # ---------- 3. 稳健性：剔最强年 ----------
    print("=" * 104)
    print("【3】稳健性：剔除最强年后重算")
    print("=" * 104)

    def drop_best(eq):
        r = eq.pct_change().dropna()
        yr = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
        best = yr.idxmax()
        keep = r[r.index.year != best]
        tot = (1 + keep).prod() - 1
        cg = (1 + tot) ** (244.0 / len(keep)) - 1 if len(keep) > 0 else np.nan
        return cg * 100, best

    for name in ["基准（现状）", "商品 →-16", "商品 →-20", "近岸(港股57) →-18"]:
        if name == "基准（现状）":
            r, p = r0, p0
        else:
            r, p, _ = store[name]
        cg, best = drop_best(r["equity"])
        print("  %-22s 剔 %s 后 %+7.2f%%（原 %+7.2f%%，落差 %5.2fpp）"
              % (name, best, cg, p["cagr"] * 100, p["cagr"] * 100 - cg))
    print()

    # ---------- 4. 落盘 ----------
    os.makedirs("回测输出", exist_ok=True)
    rows = [{"variant": "基准", "cagr": p0["cagr"], "max_dd": p0["max_dd"],
             "calmar": p0["calmar"], "sharpe": p0["sharpe"],
             "total": p0["total_return"], "trades": nb_of(r0)}]
    for k, v in store.items():
        rows.append({"variant": k, "cagr": v[1]["cagr"], "max_dd": v[1]["max_dd"],
                     "calmar": v[1]["calmar"], "sharpe": v[1]["sharpe"],
                     "total": v[1]["total_return"], "trades": nb_of(v[0])})
    pd.DataFrame(rows).to_csv("回测输出/diag_byclass_variants.csv",
                              index=False, encoding="utf-8-sig")
    print("已写出 回测输出/diag_byclass_variants.csv")


if __name__ == "__main__":
    main()
