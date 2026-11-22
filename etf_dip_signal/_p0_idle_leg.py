# -*- coding: utf-8 -*-
"""
P0 防守腿实验：线C空仓时持 现金 / 511880货币 / 银行ETF
- 同一策略、同一池、同一成本，只改“闲置资金去哪”
- 窗口A 2020-01-01~2026-11-19：515020 华夏中证银行ETF（2019-12 起）
- 窗口B 2018-01-01~2026-11-19：512800 华宝中证银行ETF（2017-08 起，覆盖2018弱年）
"""
import os, sys, json
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import bt_etf_dip as bt
import bt_multi as bm
import data_quality

DATA = os.path.join(BASE, "data", "all_etf_1119.parquet")
POOL = os.path.join(BASE, "data", "fixed_pool.json")
CASH0 = 100000.0
IDLE_COST = 0.0002   # 单边 2bp 切换成本


def load_hist():
    df = pd.read_parquet(DATA)
    df["code"] = df["code"].astype(str)
    return df


def build_pool_hist(df, codes):
    hist = {}
    for c in codes:
        s = df[df["code"] == c][["date", "open", "close", "high", "low"]].copy()
        if len(s) >= 80:
            hist[c] = s
    return hist


def idle_returns(df, code, dates):
    s = df[df["code"] == code][["date", "close"]].copy()
    s["date"] = s["date"].astype(str).str[:10]
    s = s.drop_duplicates("date").reset_index(drop=True)
    s, _ = data_quality.repair_prices(s)          # ★ 防守腿也要清洗
    s = s.set_index("date")["close"].astype(float)
    s = s.reindex([str(d)[:10] for d in dates]).ffill()
    r = s.pct_change().fillna(0.0).to_numpy()
    return r, s


def metrics(eq, trades, label):
    eq = eq.dropna()
    ret = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    mdd = (eq / eq.cummax() - 1).min()
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    sells = trades[trades["action"] == "sell"] if len(trades) else pd.DataFrame()
    win = (sells["ret"] > 0).mean() if len(sells) else np.nan
    avg = sells["ret"].mean() if len(sells) else np.nan
    return dict(label=label, cagr=cagr, mdd=mdd, sharpe=sharpe, calmar=calmar,
                trades=len(sells), win=win, avg=avg,
                total=eq.iloc[-1] / eq.iloc[0] - 1)


def run_one(m, bmap, idle_ret, label):
    r = bm.run(m, bmap, max_hold=1, intraday_stop=True, exec_mode="close",
               cash0=CASH0, idle_ret=idle_ret, idle_cost=(IDLE_COST if idle_ret is not None else 0.0))
    return r, metrics(r["equity"], r["trades"], label)


def yearly(eq):
    ret = eq.dropna().pct_change().fillna(0)
    return (1 + ret).groupby(ret.index.year).prod() - 1


def main():
    df = load_hist()
    pool = json.load(open(POOL, encoding="utf-8"))
    codes = [str(c) for c in pool["codes"]]
    bmap = {str(k): int(v) for k, v in pool["bmap"].items()}

    hist = build_pool_hist(df, codes)
    hist, dq = data_quality.audit(hist, verbose=True)
    print("pool codes:", len(codes), "| with data:", len(hist))

    for tag, start, end, bank in [
        ("窗口A 2020起 · 515020", "2020-01-01", "2026-11-19", "515020"),
        ("窗口B 2018起 · 512800", "2018-01-01", "2026-11-19", "512800"),
    ]:
        m = bt.build_matrices(hist, start=start, end=end)
        print("\n" + "=" * 92)
        print("%s | %s~%s | 交易日 %d | 起点在世 %d | 期内出现 %d" % (
            tag, start, end, len(m["dates"]),
            int(np.isfinite(m["close"][0]).sum()),
            int(np.isfinite(m["close"]).any(axis=0).sum())))
        print("=" * 92)

        rows = []
        # 1) 纯现金
        r0, p0 = run_one(m, bmap, None, "现金 0%")
        rows.append((p0, r0))
        # 2) 货币ETF
        r_m, _ = idle_returns(df, "511880", m["dates"])
        r1, p1 = run_one(m, bmap, r_m, "511880 货币")
        rows.append((p1, r1))
        # 3) 银行ETF
        r_b, px_b = idle_returns(df, bank, m["dates"])
        r2, p2 = run_one(m, bmap, r_b, "%s 银行" % bank)
        rows.append((p2, r2))
        # 4) 银行腿自身
        eq_b = px_b.ffill().dropna()
        eq_b.index = pd.to_datetime(eq_b.index)
        bm_ret = eq_b.pct_change().dropna()
        byrs = (eq_b.index[-1] - eq_b.index[0]).days / 365.25 if len(eq_b) else np.nan
        b_cagr = (eq_b.iloc[-1] / eq_b.iloc[0]) ** (1 / byrs) - 1 if byrs and byrs > 0 else np.nan
        b_mdd = (eq_b / eq_b.cummax() - 1).min()
        b_sharpe = bm_ret.mean() / bm_ret.std() * np.sqrt(252) if bm_ret.std() > 0 else np.nan

        print("%-16s %9s %9s %8s %8s %7s %7s %8s" % (
            "方案", "年化", "最大回撤", "夏普", "卡玛", "交易", "胜率", "单笔均值"))
        for p, _ in rows:
            print("%-16s %+8.2f%% %8.2f%% %8.2f %8.2f %7d %6.1f%% %+7.2f%%" % (
                p["label"], p["cagr"] * 100, p["mdd"] * 100, p["sharpe"], p["calmar"],
                p["trades"], (p["win"] * 100 if p["win"] == p["win"] else 0),
                (p["avg"] * 100 if p["avg"] == p["avg"] else 0)))
        print("银行腿自身      %+8.2f%% %8.2f%% %8.2f" % (b_cagr * 100, b_mdd * 100, b_sharpe))

        # 分年
        print("\n分年收益：")
        print("%-6s %10s %10s %10s" % ("年份", "现金", "货币", "银行腿"))
        ys = sorted(set(yearly(r0["equity"]).index) | set(yearly(r2["equity"]).index))
        for y in ys:
            def g(r):
                v = yearly(r["equity"]).get(y, np.nan)
                return "%.1f%%" % (v * 100) if pd.notna(v) else "-"
            print("%-6d %10s %10s %10s" % (y, g(r0), g(r1), g(r2)))

        # 与基线差值
        print("\n边际贡献（相对现金）：")
        for p, _ in rows[1:]:
            print("  %-16s 年化 %+.2fpp | 回撤 %+.2fpp | 卡玛 %+.2f | 交易 %+d" % (
                p["label"], (p["cagr"] - p0["cagr"]) * 100,
                (p["mdd"] - p0["mdd"]) * 100,
                p["calmar"] - p0["calmar"], p["trades"] - p0["trades"]))


if __name__ == "__main__":
    main()
