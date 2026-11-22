# -*- coding: utf-8 -*-
"""
run_backtest.py —— ETF 乖离率抄底 v4.1 回测主程序

输出：
  1. 三个执行口径 V1/V2/V3（收盘 / 盘中止损 / 次日开盘）
  2. 基准：510300 买入持有 + 池内等权
  3. 分年收益
  4. 稳健性：剔除最强单年、样本内外切分
  5. 参数敏感性：止损 / 止盈 / 持有期 / 阈值档 / 滑点
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import cifang_api
import bt_etf_dip as bt
import data_quality

CACHE = os.path.join(BASE, "data", "etf_qfq_cifang.parquet")
OUT = os.path.join(BASE, "回测输出")
CASH0 = 100000.0


def load_pool():
    d = json.load(open(os.path.join(BASE, "data", "fixed_pool.json"), encoding="utf-8"))
    return d["codes"], {str(k): int(v) for k, v in d["bmap"].items()}


def bench(hist, code, start, end, cash0=CASH0):
    df = hist[code]
    s = df[(df.date >= start) & (df.date <= end)]
    s = s.set_index(pd.to_datetime(s["date"]))["close"].astype(float)
    return s / s.iloc[0] * cash0


def eqw(hist, start, end, cash0=CASH0, min_bars=60):
    """池内等权（每日对当日有数据的标的等权持有）。"""
    px = {}
    for c, df in hist.items():
        s = df[(df.date >= start) & (df.date <= end)]
        if len(s) < min_bars:
            continue
        px[c] = s.set_index(pd.to_datetime(s["date"]))["close"].astype(float)
    if not px:
        return None
    close = pd.DataFrame(px).sort_index()
    ret = close.pct_change()
    port = (1 + ret.mean(axis=1).fillna(0)).cumprod() * cash0
    return port


def run_case(m, th_map, name, **kw):
    r = bt.run(m, th_map, **kw)
    p = bt.perf(r["equity"], r["trades"], CASH0, r["exposure"])
    p["name"] = name
    p["raw"] = r
    return p


def main():
    codes, bmap = load_pool()
    hist = cifang_api.fetch_pool_history(codes, cache_path=CACHE)
    hist, dq = data_quality.audit(hist)      # ★ 必须先清洗，否则假暴跌会伪造买点
    os.makedirs(OUT, exist_ok=True)

    windows = [("主窗口 2021-01-01起", "2021-01-01", "2026-10-20"),
               ("长窗口 2016-01-01起", "2016-01-01", "2026-10-20")]
    all_res = {}

    for wname, start, end in windows:
        m = bt.build_matrices(hist, start=start, end=end)
        alive_start = int(np.isfinite(m["close"][0]).sum())
        alive_max = int(np.isfinite(m["close"]).any(axis=0).sum())
        print("\n" + "=" * 100)
        print("%s ｜ %s ~ %s ｜ 交易日 %d ｜ 起点在世 %d 只 ｜ 期内曾出现 %d 只" % (
            wname, start, end, len(m["dates"]), alive_start, alive_max))
        if alive_start < 100:
            print("  ⚠️ 起点在世标的仅 %d 只，池子是 2026-10-14 冻结的，回测早期存在严重选择偏差"
                  % alive_start)
        print("=" * 100)

        res = {}
        res["V1_收盘成交"] = run_case(m, bmap, "V1 收盘成交(无盘中止损)",
                                     intraday_stop=False, exec_mode="close")
        res["V2_盘中止损"] = run_case(m, bmap, "V2 盘中止损(low触发)",
                                     intraday_stop=True, exec_mode="close")
        res["V3_次日开盘"] = run_case(m, bmap, "V3 次日开盘成交",
                                     intraday_stop=True, exec_mode="next_open")
        for k, v in res.items():
            print("  " + bt.fmt(v, v["name"]))

        bm = bench(hist, "510300", start, end)
        bmp = bt.perf(bm, pd.DataFrame(columns=["action"]), CASH0)
        ew = eqw(hist, start, end)
        ewp = bt.perf(ew, pd.DataFrame(columns=["action"]), CASH0) if ew is not None else None
        print("  基准 " + bt.fmt(bmp, "510300 买入持有"))
        if ewp:
            print("  基准 " + bt.fmt(ewp, "池内等权"))

        # 分年
        print("\n  【分年收益】")
        yrs = sorted(set(res["V1_收盘成交"]["by_year"].index) |
                     set(bmp["by_year"].index))
        print("    %-6s %10s %10s %10s %10s" % ("年份", "V1收盘", "V2盘中", "V3次开", "510300"))
        for y in yrs:
            def g(p):
                v = p["by_year"].get(y, np.nan)
                return "%.1f%%" % (v * 100) if pd.notna(v) else "-"
            print("    %-6d %10s %10s %10s %10s" % (
                y, g(res["V1_收盘成交"]), g(res["V2_盘中止损"]),
                g(res["V3_次日开盘"]), g(bmp)))

        # 稳健性
        print("\n  【稳健性】")
        for k, p in res.items():
            eq = p["raw"]["equity"]
            ret = eq.pct_change().fillna(0.0)
            by_real = ret.groupby(ret.index.year).apply(lambda s: (1 + s).prod() - 1)
            best_y = by_real.idxmax()
            ret2 = ret[ret.index.year != best_y]
            eq2 = (1 + ret2).cumprod()
            cagr2 = eq2.iloc[-1] ** (252.0 / max(len(ret2), 1)) - 1
            sells = p["raw"]["trades"]
            sells = sells[sells.action == "sell"] if len(sells) else pd.DataFrame()
            worst = float(sells["ret"].min()) if len(sells) else np.nan
            avg = float(sells["ret"].mean()) if len(sells) else np.nan
            print("    %-16s 剔除最强年(%d)后年化 %+.2f%%（原 %+.2f%%，差 %+.2fpp）"
                  " ｜ 单笔最好%+.1f%% 最差%+.1f%% 均值%+.1f%%" % (
                      k, best_y, cagr2 * 100, p["cagr"] * 100, (cagr2 - p["cagr"]) * 100,
                      sells["ret"].max() * 100, worst * 100, avg * 100))
        # 样本切分
        split = pd.Timestamp("2024-01-01")
        for k, p in res.items():
            eq = p["raw"]["equity"]
            a, b = eq[eq.index < split], eq[eq.index >= split]
            def st(s):
                if len(s) < 2:
                    return np.nan, np.nan
                y = (s.index[-1] - s.index[0]).days / 365.25
                return (s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1, (s / s.cummax() - 1).min()
            ca, da = st(a)
            cb, db = st(b)
            print("    %-16s 2021~2023 年化%+.1f%% 回撤%.1f%% ｜ 2024~2026 年化%+.1f%% 回撤%.1f%%" % (
                k, ca * 100, da * 100, cb * 100, db * 100))

        # 参数敏感性
        print("\n  【参数敏感性（V2 口径，单变量）】")
        base = res["V2_盘中止损"]
        print("    基准: 年化%+.2f%% 回撤%.2f%% 交易%d次" % (
            base["cagr"] * 100, base["max_dd"] * 100, base["trades"]))
        for lbl, kw in [
            ("止损 -12%", dict(stop_loss=0.12)), ("止损 -18%", dict(stop_loss=0.18)),
            ("止盈 +5%", dict(sell_profit=0.05)), ("止盈 +8%", dict(sell_profit=0.08)),
            ("持有 20日", dict(hold_max=20)), ("持有 60日", dict(hold_max=60)),
            ("不冷却", dict(cooldown=0)),
        ]:
            p = run_case(m, bmap, lbl, intraday_stop=True, exec_mode="close", **kw)
            print("    %-12s 年化%+.2f%% (%+.2fpp) 回撤%.2f%% 交易%d次" % (
                lbl, p["cagr"] * 100, (p["cagr"] - base["cagr"]) * 100,
                p["max_dd"] * 100, p["trades"]))
        th_all16 = {c: -16 for c in codes}
        p = run_case(m, th_all16, "统一-16%", intraday_stop=True, exec_mode="close")
        print("    %-12s 年化%+.2f%% (%+.2fpp) 回撤%.2f%% 交易%d次" % (
            "阈值全-16", p["cagr"] * 100, (p["cagr"] - base["cagr"]) * 100,
            p["max_dd"] * 100, p["trades"]))
        p = run_case(m, bmap, "滑点0.2%", intraday_stop=True, exec_mode="close", slippage=0.002)
        print("    %-12s 年化%+.2f%% (%+.2fpp) 回撤%.2f%% 交易%d次" % (
            "滑点0.2%", p["cagr"] * 100, (p["cagr"] - base["cagr"]) * 100,
            p["max_dd"] * 100, p["trades"]))
        p = run_case(m, bmap, "零成本", intraday_stop=True, exec_mode="close",
                     commission=0.0, slippage=0.0)
        print("    %-12s 年化%+.2f%% (%+.2fpp) 回撤%.2f%% 交易%d次" % (
            "零成本", p["cagr"] * 100, (p["cagr"] - base["cagr"]) * 100,
            p["max_dd"] * 100, p["trades"]))

        all_res[wname] = {"res": res, "bmp": bmp, "ewp": ewp,
                          "n_codes": alive_max, "alive_start": alive_start,
                          "start": start, "end": end}

    # 导出净值与交易
    for wname, d in all_res.items():
        tag = "main" if "主窗口" in wname else "long"
        eqdf = pd.DataFrame({k: v["raw"]["equity"] for k, v in d["res"].items()})
        eqdf["510300"] = d["bmp"]["equity"]
        if d["ewp"] is not None:
            eqdf["equal_weight"] = d["ewp"]
        eqdf.to_csv(os.path.join(OUT, "equity_%s.csv" % tag), encoding="utf-8-sig")
        for k, v in d["res"].items():
            fn = os.path.join(OUT, "trades_%s_%s.csv" % (tag, k.split("_")[0]))
            v["raw"]["trades"].to_csv(fn, index=False, encoding="utf-8-sig")
    print("\n[已保存] 净值与交易明细 -> %s" % OUT)


if __name__ == "__main__":
    main()
