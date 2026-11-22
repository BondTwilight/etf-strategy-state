# -*- coding: utf-8 -*-
"""
_p5_bank.py —— 96864「等股灾」复现与压力测试（2026-11-22）

策略原件（Ptrade 导出）拆解
--------------------------
进攻腿    ：159552 中证2000增强ETF招商（唯一，fund_codes=[159552]）
默认腿    ：515020 银行ETF华夏（空仓时持有，最小持有 1 天）
信号      ：10 日「加权斜率 V2」，method=6（收盘价）+ version=1（SlopeV2）
            value4 = int(年化斜率 × 加权R² × 10000)，落在 [4001, 24999] 即 40%~250%
条件过滤  ：当前价 > MA10（含今日）
止损      ：跌幅 5% 或 高点回撤 5%，触发后冷却 6 个交易日
换仓      ：进攻腿最小持有 5 个交易日
涨跌停    ：进攻腿当日涨/跌停不买；默认腿只过滤涨停（原实现如此）
成本      ：佣金万0.5（commission5=5）+ 滑点 0.1%
执行      ：14:30（本地用收盘价代理，另做 lag 稳健性）

口径坑（与 96863 同一类）
------------------------
导出脚本 `td=(0, date)` 与 `is_available_at` 冲突：`available_at=(0+5,"")` 而判定是
`5 <= 0` 恒 False ⇒ 照抄会「买入后永不卖出」。平台真实引擎用的是递增日序号。
本脚本按 i + cool 实现，并用平台公布的 11 月逐日收益做外部校验。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import data_quality
import _p4_band as pb

DATA = os.path.join(BASE, "data", "all_etf_1119.parquet")
MAIN = "159552"
BANK = "515020"
CASH0 = 100000.0
COMM5 = 5          # 万0.5
SLIP4 = 10         # 0.1%

lines = []
def say(s=""):
    lines.append(str(s))
    print(s)


# ------------------------------------------------ 原脚本的整数运算复刻
def _rha(x):
    """round half away from zero"""
    t = np.trunc(x)
    if abs(x - t) >= 0.5:
        t += 1 if x > 0 else -1
    return int(t)


def _tdiv(a, b):
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _tmod(a, b):
    return a - b * _tdiv(a, b)


# ------------------------------------------------ 数据
def load_pair(start, end):
    df = pd.read_parquet(DATA)
    df["code"] = df["code"].astype(str)
    out = {}
    for c in (MAIN, BANK):
        s = df[df.code == c][["date", "open", "high", "low", "close", "volume"]].copy()
        s["date"] = s["date"].astype(str).str[:10]
        s = s.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        s2, _ = data_quality.repair_prices(s)
        s2["date"] = pd.to_datetime(s2["date"])
        out[c] = s2.set_index("date")
    p = pd.DataFrame({"main": out[MAIN]["close"], "bank": out[BANK]["close"]}).loc[start:end]
    return p.dropna()


# ------------------------------------------------ SlopeV2（加权斜率×R²）
def slope_v2_value4(hist_log, today_log, weighted=True):
    lp = list(hist_log[-9:]) + [today_log]
    n = len(lp)
    if n < 10:
        return None
    w = [1.0] * n
    if weighted:
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
        ann = float("inf")
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


def ma_round(total, size):
    """复刻 MA.value3：ma4 = total*10/size，再按个位四舍五入回来"""
    ma4 = _tdiv(total * 10, size)
    if _tmod(ma4, 10) >= 5:
        return _tdiv(ma4, 10) + 1
    return _tdiv(ma4, 10)


# ------------------------------------------------ 回测主体
def run(p, *, min4=4001, max4=24999, slope_days=10, ma_slow=10,
        hold_cool=5, default_cool=1, use_stop=True,
        stop_pct=500, back_pct=500, stop_cool=6,
        use_ma=True, use_default=True, cash0=CASH0,
        comm5=COMM5, slip4=SLIP4, limit_main=True, limit_bank=True, lag=0):
    dates = p.index
    n = len(dates)
    px3 = {c: np.array([_rha(v * 1000) for v in p[c].to_numpy()], dtype=np.int64)
           for c in ("main", "bank")}
    logm = np.log(p["main"].to_numpy(dtype=float))
    if lag:
        logm = np.concatenate([np.full(lag, np.nan), logm[:-lag]])
        for c in ("main", "bank"):
            px3[c] = np.concatenate([np.full(lag, 0, dtype=np.int64), px3[c][:-lag]])

    cash3 = int(round(cash0 * 1000))
    hold = None
    stop_cool_until = -1
    eq = np.full(n, np.nan)
    trades = []
    closed = []

    def limit_state(i, c):
        if i <= 0:
            return False, False
        prev = px3[c][i - 1]
        if prev <= 0 or px3[c][i] <= 0:
            return False, False
        pct4 = _rha((px3[c][i] - prev) / prev * 10000)
        return (pct4 >= 1000 - 10), (pct4 <= -1000 + 10)

    def try_buy(i, c, money3, filt_down):
        p3 = int(px3[c][i])
        if p3 <= 0:
            return None
        up, dn = limit_state(i, c)
        if up:
            return None
        if filt_down and dn:
            return None
        bp3 = _tdiv(p3 * (10000 + slip4) + 9999, 10000)
        amt = _tdiv(_tdiv(money3 * (100000 - comm5), 100000), bp3 * 100) * 100
        if amt <= 0 or bp3 * amt < 1000000:
            return None
        used = _tdiv(bp3 * amt * (100000 + comm5), 100000)
        trades.append({"date": dates[i], "action": "buy", "code": c,
                       "price": bp3 / 1000.0, "amount": int(amt), "reason": ""})
        return {"code": c, "amount": int(amt), "buy_mv3": int(bp3 * amt),
                "max_mv3": int(bp3 * amt), "buy_i": i, "used3": int(used),
                "entry": bp3 / 1000.0}

    for i in range(n):
        # ---------- 1. 止损（独立且优先） ----------
        if hold is not None:
            c = hold["code"]
            mv3 = int(px3[c][i] * hold["amount"])
            lim = limit_main if c == "main" else limit_bank
            up, dn = limit_state(i, c)
            if not (lim and dn):
                hold["max_mv3"] = max(hold["max_mv3"], mv3)
            if use_stop and not (lim and dn):
                hit = ""
                if hold["buy_mv3"] > mv3 and _tdiv((hold["buy_mv3"] - mv3) * 10000,
                                                   hold["buy_mv3"]) >= stop_pct:
                    hit = "跌幅止损"
                elif hold["max_mv3"] > mv3 and _tdiv((hold["max_mv3"] - mv3) * 10000,
                                                     hold["max_mv3"]) >= back_pct:
                    hit = "回撤止损"
                if hit:
                    sp3 = _tdiv(px3[c][i] * (10000 - slip4) - 1, 10000)
                    cash3 += _tdiv(hold["amount"] * sp3 * (100000 - comm5), 100000)
                    r = (sp3 / 1000.0) / hold["entry"] - 1
                    trades.append({"date": dates[i], "action": "sell", "code": c,
                                   "price": sp3 / 1000.0, "amount": hold["amount"],
                                   "ret": r, "reason": hit})
                    closed.append(r)
                    hold = None
                    stop_cool_until = i + stop_cool

        # ---------- 2. 进攻信号 ----------
        main_ok = False
        v4 = None
        if i >= slope_days - 1 and np.isfinite(logm[i]):
            v4 = slope_v2_value4(logm[max(0, i - 9):i], logm[i])
            if v4 is not None and min4 <= v4 <= max4:
                main_ok = True
        if use_ma:
            if i < ma_slow - 1:
                main_ok = False
            else:
                hist3 = [int(x) for x in px3["main"][i - (ma_slow - 1):i]]
                ma_b = ma_round(sum(hist3) + int(px3["main"][i]), ma_slow)
                if int(px3["main"][i]) <= ma_b:
                    main_ok = False

        # ---------- 3. 目标：有信号就进攻，否则默认腿 ----------
        # 注意：原策略允许「持有银行时信号出现就切换」，不是「只有空仓才买」。
        # 而「目标 == 当前持仓」时即使满期也不动 —— 对应原实现的
        # `if default.code in sells: del sells[default.code]`（卖出后必空仓则取消卖出）。
        target = None
        if main_ok and i >= stop_cool_until:
            target = "main"
        elif use_default:
            target = "bank"

        # ---------- 4. 换仓（满最小持有期才允许卖） ----------
        if hold is not None and target is not None and target != hold["code"]:
            c = hold["code"]
            cool = default_cool if c == "bank" else hold_cool
            if i - hold["buy_i"] >= cool:
                sp3 = _tdiv(px3[c][i] * (10000 - slip4) - 1, 10000)
                cash3 += _tdiv(hold["amount"] * sp3 * (100000 - comm5), 100000)
                r = (sp3 / 1000.0) / hold["entry"] - 1
                trades.append({"date": dates[i], "action": "sell", "code": c,
                               "price": sp3 / 1000.0, "amount": hold["amount"],
                               "ret": r,
                               "reason": "默认腿让位" if c == "bank" else "信号消失/换仓"})
                closed.append(r)
                hold = None

        # ---------- 5. 买入 ----------
        if hold is None and target is not None:
            h = try_buy(i, target, cash3, target == "main")
            if h:
                cash3 -= h["used3"]
                hold = h

        mv = int(px3[hold["code"]][i] * hold["amount"]) if hold else 0
        eq[i] = (cash3 + mv) / 1000.0

    eqs = pd.Series(eq, index=dates).dropna()
    return {"equity": eqs, "trades": trades, "closed": closed}


def main():
    say("=" * 108)
    say("96864「等股灾」复现与压力测试")
    say("进攻腿 159552 中证2000增强 ｜ 默认腿 515020 银行 ｜ 佣金万0.5 + 滑点 0.1% ｜ 14:30（用收盘代理）")
    say("=" * 108)

    p_all = load_pair("2024-06-28", "2026-11-19")
    say("\n数据：159552 + 515020 共同交易日 %d 个（%s ~ %s）"
        % (len(p_all), p_all.index[0].date(), p_all.index[-1].date()))
    say("平台回测窗口 2024-10-01 ~ 2026-11-20（本地数据到 11-19）")

    sub = p_all.loc["2024-10-01":"2026-11-19"]

    say("\n" + "=" * 108)
    say("A. 主复现 vs 平台")
    say("=" * 108)
    r = run(sub)
    s = pb.stats(r["equity"], r["trades"])
    tot = (r["equity"].iloc[-1] / CASH0 - 1) * 100
    say("  本地：总收益 %+.2f%% ｜ 年化 %+.2f%% ｜ 回撤 %.2f%% ｜ 夏普 %.2f ｜ 卡玛 %.2f ｜ 交易 %d 笔 ｜ 胜率 %.1f%% ｜ 盈亏比 %.2f"
        % (tot, s["cagr"] * 100, s["max_dd"] * 100, s["sharpe"], s["calmar"],
           s["trades"], s["win"] * 100, s["pl"]))
    say("  平台：总收益 +207.45%% ｜ 年化 +73.07%% ｜ 回撤 -8.59%% ｜ 夏普 3.84 ｜ 卡玛 8.51 ｜ 胜率 71.67%% ｜ 盈亏比 1.71")
    say("  差异：总收益 %+.2fpp ｜ 年化 %+.2fpp ｜ 回撤 %+.2fpp ｜ 夏普 %+.2f ｜ 卡玛 %+.2f"
        % (tot - 207.45, s["cagr"] * 100 - 73.07, s["max_dd"] * 100 + 8.59,
           s["sharpe"] - 3.84, s["calmar"] - 8.51))

    say("\n  交易明细：")
    for t in r["trades"]:
        if t["action"] == "buy":
            say("    %s 买入 %s %7d 份 @ %.3f"
                % (pd.Timestamp(t["date"]).date(), t["code"], t["amount"], t["price"]))
        else:
            say("    %s 卖出 %s %7d 份 @ %.3f  ret=%+.2f%%  %s"
                % (pd.Timestamp(t["date"]).date(), t["code"], t["amount"], t["price"],
                   t["ret"] * 100, t["reason"]))

    say("\n" + "=" * 108)
    say("B. 外部校验：11 月逐日收益（平台公布）")
    say("=" * 108)
    plat = [("11-02", -1.04), ("11-03", -0.42), ("11-04", -0.74), ("11-05", -0.59),
            ("11-06", 1.02), ("11-09", 1.06), ("11-10", 0.16), ("11-11", -0.73),
            ("11-12", 0.32), ("11-13", 1.53), ("11-16", 1.71), ("11-17", 0.36),
            ("11-18", -0.20), ("11-19", -0.05)]
    eq = r["equity"]
    say("  %-6s %10s %10s %8s" % ("日期", "本地%", "平台%", "差pp"))
    tot_l = tot_p = 0.0
    errs = []
    for d, v in plat:
        ts = pd.Timestamp("2026-" + d)
        prev = eq.loc[:ts]
        if len(prev) < 2:
            continue
        lv = (prev.iloc[-1] / prev.iloc[-2] - 1) * 100
        say("  %-6s %+9.2f%% %+9.2f%% %+8.2f" % (d, lv, v, lv - v))
        tot_l += lv; tot_p += v; errs.append(abs(lv - v))
    say("  %-6s %+9.2f%% %+9.2f%%" % ("累计", tot_l, tot_p))
    say("  平均绝对误差 %.3fpp（11-20 的 +1.17%% 本地无数据，未计入）" % np.mean(errs))

    say("\n" + "=" * 108)
    say("C. 分年 / 分季度")
    say("=" * 108)
    rr = eq.pct_change().fillna(0.0)
    yb = rr.groupby(rr.index.year).apply(lambda x: (1 + x).prod() - 1)
    say("  年度：" + "   ".join("%d %+.2f%%" % (y, v * 100) for y, v in yb.items()))
    qb = rr.groupby([rr.index.year, rr.index.quarter]).apply(lambda x: (1 + x).prod() - 1)
    say("  最强 3 季：" + "  ".join("%dQ%d %+.1f%%" % (k[0], k[1], v * 100)
                                  for k, v in qb.nlargest(3).items()))
    say("  最弱 3 季：" + "  ".join("%dQ%d %+.1f%%" % (k[0], k[1], v * 100)
                                  for k, v in qb.nsmallest(3).items()))

    say("\n" + "=" * 108)
    say("D. 拆件：每个部件贡献多少（2024-10 起）")
    say("=" * 108)
    say("  %-26s %9s %10s %7s %7s %6s" % ("变体", "年化", "最大回撤", "夏普", "卡玛", "交易"))
    say("  " + "-" * 76)
    for lbl, kw in [
        ("完整版（平台口径）", dict()),
        ("关掉双止损", dict(use_stop=False)),
        ("关掉 MA10 过滤", dict(use_ma=False)),
        ("关掉止损 + MA", dict(use_stop=False, use_ma=False)),
        ("关掉默认腿（空仓就空仓）", dict(use_default=False)),
        ("不加涨跌停过滤", dict(limit_main=False, limit_bank=False)),
        ("零成本", dict(comm5=0, slip4=0)),
        ("佣金千1 + 滑点0.3%", dict(comm5=100, slip4=30)),
        ("信号滞后 1 日成交", dict(lag=1)),
    ]:
        rv = run(sub, **kw)
        sv = pb.stats(rv["equity"], rv["trades"])
        say("  %-26s %+8.2f%% %9.2f%% %7.2f %7.2f %6d"
            % (lbl, sv["cagr"] * 100, sv["max_dd"] * 100, sv["sharpe"],
               sv["calmar"], sv["trades"]))

    say("\n" + "=" * 108)
    say("E. 参数敏感性（找平台区，还是尖峰）")
    say("=" * 108)
    say("  %-24s %9s %10s %7s %7s %6s" % ("参数", "年化", "最大回撤", "夏普", "卡玛", "交易"))
    say("  " + "-" * 74)
    for lbl, kw in [
        ("止损3% / 回撤3%", dict(stop_pct=300, back_pct=300)),
        ("止损5% / 回撤5%（原版）", dict()),
        ("止损8% / 回撤8%", dict(stop_pct=800, back_pct=800)),
        ("止损10% / 回撤10%", dict(stop_pct=1000, back_pct=1000)),
        ("只跌幅止损5%", dict(back_pct=999999)),
        ("只回撤止损5%", dict(stop_pct=999999)),
        ("斜率下限 0", dict(min4=1)),
        ("斜率上限 5.0", dict(max4=50000)),
        ("斜率上限 1.5", dict(max4=15000)),
        ("最小持有 1 天", dict(hold_cool=1)),
        ("最小持有 10 天", dict(hold_cool=10)),
        ("止损冷却 1 天", dict(stop_cool=1)),
        ("止损冷却 20 天", dict(stop_cool=20)),
    ]:
        rv = run(sub, **kw)
        sv = pb.stats(rv["equity"], rv["trades"])
        say("  %-24s %+8.2f%% %9.2f%% %7.2f %7.2f %6d"
            % (lbl, sv["cagr"] * 100, sv["max_dd"] * 100, sv["sharpe"],
               sv["calmar"], sv["trades"]))

    say("\n" + "=" * 108)
    say("F. 起点敏感性（检查是不是「靠 924 那一波」）")
    say("=" * 108)
    say("  %-12s %9s %10s %7s %7s %5s   %s" % ("起点", "年化", "最大回撤", "夏普", "卡玛", "交易",
                                              "同期 159552 买入持有"))
    say("  " + "-" * 100)
    for st in ["2024-10-01", "2025-01-01", "2025-04-01", "2025-07-01", "2026-01-01"]:
        sb = p_all.loc[st:"2026-11-19"]
        if len(sb) < 60:
            continue
        rv = run(sb)
        sv = pb.stats(rv["equity"], rv["trades"])
        bh = (sb["main"].iloc[-1] / sb["main"].iloc[0] - 1) * 100
        bha = ((sb["main"].iloc[-1] / sb["main"].iloc[0]) ** (252.0 / len(sb)) - 1) * 100
        say("  %-12s %+8.2f%% %9.2f%% %7.2f %7.2f %5d   区间 %+.1f%%（年化 %+.1f%%）"
            % (st, sv["cagr"] * 100, sv["max_dd"] * 100, sv["sharpe"],
               sv["calmar"], sv["trades"], bh, bha))

    say("\n" + "=" * 108)
    say("G. 事实与判断")
    say("=" * 108)
    say("  · 159552 上市 2024-06-28，平台回测起点 2024-10-01 —— 上市后仅 3 个月，没有更长历史。")
    say("  · 2024-09-24 是一轮大反弹起点，中证2000 是弹性最大的宽基之一。")
    say("  · 只有 1 只标的 ⇒ 不存在「选池偏差」；但存在「标的择时」+「窗口选择」偏差。")
    say("  · 2.1 年、%d 笔交易 —— 夏普 3.84 的 95%% 区间会非常宽，不能当预期。" % s["trades"])
    say("  · 真正的看点是「双 5%% 止损 + 银行默认腿」这套风控：它在 2026-06-12~06-30 那波")
    say("    只回撤 8.59%%（平台口径），这是可迁移的部分；收益数字不可迁移。")

    out = os.path.join(BASE, "_p5_bank.log")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n[已保存] " + out)


if __name__ == "__main__":
    main()
