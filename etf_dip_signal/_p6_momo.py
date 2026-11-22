# -*- coding: utf-8 -*-
"""
_p6_momo.py —— 96865「momo 原版」复现与压力测试（2026-11-22）

这是线B 的真身。与平台「hf_etf_12」不是一回事：
它用「加权斜率 V2（分时）」双窗口，不是区间涨幅。

参数（Ptrade 导出）
------------------
池        ：12 只（518880/159509/588000/501225/513100/513310/159915/162719/159985/513030/513290/513520）
信号      ：method=2（加权斜率，分时）+ version=1（SlopeV2）
            filter1: 20 日，value4 ∈ [1, 29999]  → 年化×R² ∈ [0.01%, 299.99%]
            filter2: 26 日，value4 ∈ [1, 99999]  → 年化×R² ∈ [0.01%, 999.99%]
            **两个 filter 都要满足**；排序用 filter1（20 日）降序
筛选      ：当日涨停/跌停不买（filter_out_up/down_limit=True）
仓位      ：hold_max=1，单票满仓，**无止损、无止盈、无默认腿**
换仓      ：hold_cool_days=2（最小持有 2 个交易日）
成本      ：佣金万1（commission5=10）+ 滑点 0.1%
执行      ：14:30

⚠️ 口径
------
method=2 的 push 用的是 tick.adjusted_price3（**14:30 分时价**），不是收盘价。
本地无分钟数据 ⇒ 用收盘价代理，另做 lag=1 稳健性。

⚠️ 池子回填偏差（必须披露）
------------------------
2018-01-01 在世 5 只（黄金/纳指100/创业板/德国/石油），2020-01 六只，
2023-01 九只，现在十二只。平台「2018 年起」的回测，实际是「池子从 5 只长到 12 只」，
今天是 2026 年选出来的赢家池。**这不构成未来函数**（无数据的标的不参与），
但会系统性高估早期收益的「可选性」。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import data_quality

DATA = os.path.join(BASE, "data", "all_etf_1119.parquet")
CODES = ["518880", "159509", "588000", "501225", "513100", "513310",
         "159915", "162719", "159985", "513030", "513290", "513520"]
NAMES = {"518880": "黄金", "159509": "纳指科技", "588000": "科创50",
         "501225": "全球芯片", "513100": "纳指100", "513310": "中韩半导体",
         "159915": "创业板", "162719": "石油LOF", "159985": "豆粕",
         "513030": "德国", "513290": "纳指生物", "513520": "日经"}
CASH0 = 100000.0
COMM5 = 10      # 万1
SLIP4 = 10      # 0.1%

lines = []
def say(s=""):
    lines.append(str(s))
    print(s)


def _rha(x):
    t = np.trunc(x)
    if abs(x - t) >= 0.5:
        t += 1 if x > 0 else -1
    return int(t)


def _tdiv(a, b):
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def load_px(start="2015-01-05", end="2026-11-19"):
    df = pd.read_parquet(DATA)
    df["code"] = df["code"].astype(str)
    cols = {}
    for c in CODES:
        s = df[df.code == c][["date", "close", "volume"]].copy()
        s["date"] = s["date"].astype(str).str[:10]
        s = s.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        s2, _ = data_quality.repair_prices(s)
        s2["date"] = pd.to_datetime(s2["date"])
        cols[c] = s2.set_index("date")["close"]
    p = pd.DataFrame(cols).sort_index().loc[start:end]
    return p


def slope_v2(hist_log, today_log):
    """SlopeV2（weighted=True, exclude_today=False）→ int(年化 × 加权R² × 10000)"""
    lp = list(hist_log) + [today_log]
    n = len(lp)
    if n < 2:
        return None
    w = [1.0] * n
    d = float(n - 1)
    for i in range(n):
        w[i] = (1.0 + i / d) ** 2
    sw = sx = sy = sxx = sxy = 0.0
    for i, y in enumerate(lp):
        x = float(i)
        sw += w[i]; sx += w[i] * x; sy += w[i] * y
        sxx += w[i] * x * x; sxy += w[i] * x * y
    den = sw * sxx - sx * sx
    if den == 0:
        return None
    k = (sw * sxy - sx * sy) / den
    b = (sy - k * sx) / sw
    try:
        ann = np.exp(k * 250) - 1
    except OverflowError:
        return None
    my = sy / sw
    ssr = sst = 0.0
    for i, pr in enumerate(lp):
        yp = k * float(i) + b
        ssr += w[i] * (pr - yp) ** 2
        sst += w[i] * (pr - my) ** 2
    r2 = 0.0 if sst == 0 else 1 - ssr / sst
    v = ann * r2 * 10000
    if not np.isfinite(v):
        return None
    return int(v)


def build_signals(p, days1=20, days2=26, lag=0):
    n = len(p)
    k = len(p.columns)
    V1 = np.full((n, k), np.nan)
    V2 = np.full((n, k), np.nan)
    logs = {c: np.log(p[c].to_numpy(dtype=float)) for c in p.columns}
    for j, c in enumerate(p.columns):
        lp = logs[c]
        s1 = days1 - 1
        s2 = days2 - 1
        for i in range(n):
            if not np.isfinite(lp[i]):
                continue
            if i >= s1 and np.isfinite(lp[i - s1:i]).all():
                v = slope_v2(lp[i - s1:i], lp[i])
                if v is not None:
                    V1[i, j] = v
            if i >= s2 and np.isfinite(lp[i - s2:i]).all():
                v = slope_v2(lp[i - s2:i], lp[i])
                if v is not None:
                    V2[i, j] = v
    if lag:
        V1 = np.vstack([np.full((lag, k), np.nan), V1[:-lag]])
        V2 = np.vstack([np.full((lag, k), np.nan), V2[:-lag]])
    return V1, V2


def run(p, V1, V2, *, min1=1, max1=29999, min2=1, max2=99999,
        hold_cool=2, cash0=CASH0, comm5=COMM5, slip4=SLIP4,
        filter_limit=True, cap19=None, use_v2=True, dump_from=None):
    """cap19: 额外要求「19 日区间涨幅 ≤ cap19」（默认 None = 不加）"""
    dates = p.index
    n = len(dates)
    codes = list(p.columns)
    k = len(codes)
    px3 = np.array([[_rha(v * 1000) if np.isfinite(v) else 0 for v in p[c].to_numpy()]
                    for c in codes]).T   # (n, k)
    # 估值专用 ffill（停牌/缺数据日不能把市值算成 0，否则会「以 0 元卖出」——
    # 首版就栽在这里：2018-08-14 石油LOF 无数据 → 净值从 10 万直接归零）
    px3f = np.zeros_like(px3)
    for j in range(k):
        last = 0
        for i in range(n):
            if px3[i, j] > 0:
                last = px3[i, j]
            px3f[i, j] = last

    if cap19 is not None:
        ret19 = p / p.shift(19) - 1.0
        R19 = ret19.to_numpy(dtype=float)
    else:
        R19 = None

    cash3 = int(round(cash0 * 1000))
    hold_j = None
    buy_i = None
    entry = None
    amt = 0
    eq = np.full(n, np.nan)
    trades = []
    closed = []

    for i in range(n):
        # ---------- 1. 判定 nominal ----------
        nom = []
        for j in range(k):
            v1, v2 = V1[i, j], V2[i, j]
            if not np.isfinite(v1):
                continue
            if not (min1 <= v1 <= max1):
                continue
            if use_v2 and (not np.isfinite(v2) or not (min2 <= v2 <= max2)):
                continue
            if R19 is not None:
                r = R19[i, j]
                if not np.isfinite(r) or r > cap19:
                    continue
            if filter_limit and i > 0:
                prev = px3[i - 1, j]
                cur = px3[i, j]
                if prev > 0 and cur > 0:
                    pct4 = _rha((cur - prev) / prev * 10000)
                    if pct4 >= 1000 - 10 or pct4 <= -1000 + 10:
                        continue
            nom.append(j)
        nom.sort(key=lambda j: -V1[i, j])
        top = nom[0] if nom else None

        # ---------- 2. 卖出（停牌/无价日不交易，与原脚本 trading() 判定一致）----------
        if hold_j is not None and (i - buy_i) >= hold_cool:
            if top != hold_j and px3[i, hold_j] > 0:
                sp3 = _tdiv(px3[i, hold_j] * (10000 - slip4) - 1, 10000)
                cash3 += _tdiv(amt * sp3 * (100000 - comm5), 100000)
                r = (sp3 / 1000.0) / entry - 1
                trades.append({"date": dates[i], "action": "sell", "code": codes[hold_j],
                               "price": sp3 / 1000.0, "amount": amt, "ret": r})
                closed.append(r)
                hold_j, buy_i, entry, amt = None, None, None, 0

        # ---------- 3. 买入 ----------
        if hold_j is None and top is not None:
            j = top
            p3 = int(px3[i, j])
            if p3 > 0:
                bp3 = _tdiv(p3 * (10000 + slip4) + 9999, 10000)
                a = _tdiv(_tdiv(cash3 * (100000 - comm5), 100000), bp3 * 100) * 100
                if a > 0 and bp3 * a >= 1000000:
                    used = _tdiv(bp3 * a * (100000 + comm5), 100000)
                    cash3 -= used
                    hold_j, buy_i, entry, amt = j, i, bp3 / 1000.0, int(a)
                    trades.append({"date": dates[i], "action": "buy", "code": codes[j],
                                   "price": bp3 / 1000.0, "amount": int(a), "ret": np.nan})

        mv = int(px3f[i, hold_j] * amt) if hold_j is not None else 0
        eq[i] = (cash3 + mv) / 1000.0

        if dump_from is not None and dates[i] >= pd.Timestamp(dump_from):
            say("    %s 持 %-8s 净值 %8.0f  v20=%s v26=%s"
                % (dates[i].date(),
                   NAMES.get(codes[hold_j], codes[hold_j]) if hold_j is not None else "空仓",
                   eq[i],
                   ("%.3f" % (V1[i, hold_j] / 10000)) if hold_j is not None else "-",
                   ("%.3f" % (V2[i, hold_j] / 10000)) if hold_j is not None else "-"))

    eqs = pd.Series(eq, index=dates).dropna()
    return {"equity": eqs, "trades": trades, "closed": closed}


def main():
    say("=" * 112)
    say("96865「momo 原版」复现与压力测试")
    say("12 只池 ｜ 20日+26日 加权斜率V2 双滤 ｜ min_hold=2 ｜ 无止损/止盈/默认腿 ｜ 佣金万1+滑点0.1% ｜ 14:30（收盘代理）")
    say("=" * 112)

    p = load_px()
    say("\n数据：%d 个交易日（%s ~ %s），12 只标的" % (len(p), p.index[0].date(), p.index[-1].date()))
    alive = p.notna().sum(axis=1)
    for y in (2018, 2020, 2022, 2024, 2026):
        s = alive[alive.index.year == y]
        if len(s):
            say("  %d 年：年初在世 %d 只 → 年末 %d 只" % (y, s.iloc[0], s.iloc[-1]))

    say("\n[信号计算] 20日 + 26日 加权斜率 V2 ...")
    V1, V2 = build_signals(p, 20, 26)
    say("  有效信号覆盖率：20日 %.1f%%｜26日 %.1f%%"
        % (np.isfinite(V1).mean() * 100, np.isfinite(V2).mean() * 100))

    sub_idx = (p.index >= "2018-01-01") & (p.index <= "2026-11-19")
    p18 = p.loc[sub_idx]
    i0 = np.where(sub_idx)[0][0]
    V1s, V2s = V1[i0:], V2[i0:]

    say("\n" + "=" * 112)
    say("A. 主复现 vs 平台（2018-01-01 ~ 2026-11-19，本金 10 万）")
    say("=" * 112)
    r = run(p18, V1s, V2s)
    s = _stats(r)
    say("  本地：总收益 %+.2f%% ｜ 年化 %+.2f%% ｜ 回撤 %.2f%% ｜ 夏普 %.2f ｜ 卡玛 %.2f ｜ 交易 %d 笔 ｜ 胜率 %.1f%% ｜ 盈亏比 %.2f"
        % (s["tot"], s["cagr"], s["mdd"], s["sharpe"], s["calmar"], s["trades"],
           s["win"], s["pl"]))
    say("  平台：总收益 +4546.73%% ｜ 年化 56.69%% ｜ 回撤 22.76%% ｜ 夏普 1.99 ｜ 卡玛 2.49 ｜ 胜率 53.29%% ｜ 盈亏比 1.82 ｜ 月均 4 次")
    say("  差异：总收益 %+.1fpp ｜ 年化 %+.2fpp ｜ 回撤 %+.2fpp ｜ 夏普 %+.2f"
        % (s["tot"] - 4546.73, s["cagr"] - 56.69, s["mdd"] + 22.76, s["sharpe"] - 1.99))

    say("\n  分年收益：")
    rr = r["equity"].pct_change().fillna(0.0)
    yb = rr.groupby(rr.index.year).apply(lambda x: (1 + x).prod() - 1)
    for y, v in yb.items():
        a = alive[alive.index.year == y]
        na = int(a.median()) if len(a) else 0
        say("    %d  %+8.2f%%   （当年在世标的 %d 只）" % (y, v * 100, na))

    say("\n" + "=" * 112)
    say("B. 外部校验：2026 年 11 月逐日（平台公布，当月 -16.50%）")
    say("=" * 112)
    plat = [("11-02", -1.33), ("11-03", -0.51), ("11-04", -3.78), ("11-05", 3.67),
            ("11-06", -5.78), ("11-09", 2.87), ("11-10", 3.01), ("11-11", 0.63),
            ("11-12", 2.13), ("11-13", 0.10), ("11-16", -3.65), ("11-17", -3.12),
            ("11-18", -3.82), ("11-19", -1.45), ("11-20", -6.17)]
    eq = r["equity"]
    say("  %-6s %10s %10s %8s" % ("日期", "本地%", "平台%", "差pp"))
    tot_l = tot_p = 0.0
    errs = []
    for d, v in plat:
        ts = pd.Timestamp("2026-" + d)
        prev = eq.loc[:ts]
        if len(prev) < 2:
            say("  %-6s %10s %+9.2f%%    （本地无数据）" % (d, "-", v))
            continue
        lv = (prev.iloc[-1] / prev.iloc[-2] - 1) * 100
        say("  %-6s %+9.2f%% %+9.2f%% %+8.2f" % (d, lv, v, lv - v))
        tot_l += lv; tot_p += v; errs.append(abs(lv - v))
    say("  %-6s %+9.2f%% %+9.2f%%" % ("累计", tot_l, tot_p))
    if errs:
        say("  平均绝对误差 %.3fpp（%d 天）" % (np.mean(errs), len(errs)))

    say("\n" + "=" * 112)
    say("C. 拆件（2018 起）：每个部件值多少")
    say("=" * 112)
    say("  %-28s %9s %10s %7s %7s %7s %6s" % ("变体", "年化", "最大回撤", "夏普", "卡玛", "胜率", "交易"))
    say("  " + "-" * 82)
    for lbl, kw in [
        ("原版（20+26 双滤, hold2）", dict()),
        ("只用 20 日单滤", dict(use_v2=False)),
        ("最小持有 1 天", dict(hold_cool=1)),
        ("最小持有 5 天", dict(hold_cool=5)),
        ("最小持有 10 天", dict(hold_cool=10)),
        ("不加涨跌停过滤", dict(filter_limit=False)),
        ("斜率下限放开到 0", dict(min1=0, min2=0)),
        ("斜率上限放开到 10", dict(max1=99999, max2=99999)),
        ("18日涨幅上限 10%", dict(cap19=0.10)),
        ("18日涨幅上限 15%", dict(cap19=0.15)),
        ("18日涨幅上限 20%", dict(cap19=0.20)),
        ("零成本", dict(comm5=0, slip4=0)),
        ("3tick 滑点 0.3%", dict(slip4=30)),
    ]:
        rv = run(p18, V1s, V2s, **kw)
        sv = _stats(rv)
        say("  %-28s %+8.2f%% %9.2f%% %7.2f %7.2f %6.1f%% %6d"
            % (lbl, sv["cagr"], sv["mdd"], sv["sharpe"], sv["calmar"], sv["win"], sv["trades"]))

    say("\n" + "=" * 112)
    say("D. 起点敏感性 + 池子扩张的影响")
    say("=" * 112)
    say("  %-12s %9s %10s %7s %7s %6s   %s" % ("起点", "年化", "最大回撤", "夏普", "卡玛", "交易", "在世标的数（起→末）"))
    say("  " + "-" * 92)
    for st in ["2018-01-01", "2020-01-01", "2022-01-01", "2023-01-01", "2024-01-01"]:
        m = (p.index >= st) & (p.index <= "2026-11-19")
        if m.sum() < 120:
            continue
        j0 = np.where(m)[0][0]
        pp = p.loc[m]
        rv = run(pp, V1[j0:], V2[j0:])
        sv = _stats(rv)
        a = alive.loc[pp.index]
        say("  %-12s %+8.2f%% %9.2f%% %7.2f %7.2f %6d   %d → %d"
            % (st, sv["cagr"], sv["mdd"], sv["sharpe"], sv["calmar"], sv["trades"],
               a.iloc[0], a.iloc[-1]))

    say("\n" + "=" * 112)
    say("E. 关键事实")
    say("=" * 112)
    say("  · 平台「2018 年起 56.69%」是在池子从 5 只长到 12 只的过程中跑出来的：")
    say("    2018 在世 5 只、2020 六只、2023 九只、现在十二只。无未来函数，但早期「可选性」被高估。")
    say("  · 当前状态：2026-10-20 → 11-20 回撤 22.76%，**未修复**；11 月单月 -16.50%。")
    say("  · 这正好验证了我们的判断：线B 在「成长杀估值 + 高波」里会被反复打脸。")
    say("  · 无止损、无默认腿 ⇒ 空仓期就是空仓，不承担任何 beta。这是它和 96864 最大的结构差异。")

    out = os.path.join(BASE, "_p6_momo.log")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n[已保存] " + out)


def _stats(r):
    eq = pd.Series(r["equity"]).dropna()
    n = len(eq)
    if n < 2:
        return {}
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    dr = eq.pct_change().dropna()
    vol = dr.std() * np.sqrt(252)
    sharpe = (dr.mean() * 252) / vol if vol > 0 else np.nan
    closed = [x for x in r["closed"]]
    win = (np.array(closed) > 0).mean() * 100 if closed else np.nan
    aw = np.mean([x for x in closed if x > 0]) if any(x > 0 for x in closed) else np.nan
    al = np.mean([x for x in closed if x < 0]) if any(x < 0 for x in closed) else np.nan
    pl = abs(aw / al) if np.isfinite(al) and al != 0 else np.nan
    return {"tot": (eq.iloc[-1] / CASH0 - 1) * 100, "cagr": cagr * 100,
            "mdd": dd * 100, "sharpe": sharpe,
            "calmar": (cagr / abs(dd)) if dd < 0 else np.nan,
            "trades": len(closed), "win": win, "pl": pl, "n": n}


if __name__ == "__main__":
    main()
