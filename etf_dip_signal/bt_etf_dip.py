# -*- coding: utf-8 -*-
"""
bt_etf_dip.py —— ETF 乖离率抄底策略 v4.1 独立回测（本地复刻 + 交叉验证）

复刻对象：etf_dip_signal/engine.py 的 execute_trades / should_sell / intraday_stop_scan
数据：次方量化 hist_em（qfq 前复权）
约束：PAPER_ONLY，不接实盘

与线上脚本的差异（必须知道）：
  1. 线上每次运行 Portfolio 现金恒为 10 万（不灌历史盈亏）；本回测用**真实复利现金**。
     这是更诚实的口径，也是与线上数值不可直接相减的原因之一。
  2. 线上「决策价」= 14:45 实时价；回测用当日收盘价（V1/V2）或次日开盘价（V3）。
  3. 线上「盘中止损」只在脚本运行那一刻判一次（intraday_guard.py 缺失）；
     本回测用当日 low 模拟真实盘中止损（V2），比线上更严格。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import config as cfg

# ---------------- 策略参数（与 config.py 对齐） ----------------
STOP_LOSS = cfg.STOP_LOSS_PCT          # 0.15
SELL_PROFIT = cfg.SELL_PROFIT_PCT      # 0.03
SELL_BIAS_TH = cfg.SELL_BIAS_TH        # 0
HOLD_MAX_DAYS = cfg.HOLD_MAX_DAYS      # 30
COOLDOWN = cfg.STOP_COOLDOWN_DAYS      # 3
BIAS_SORT_DAYS = cfg.BIAS_SORT_DAYS    # 50
BIAS_BUY_DAYS = cfg.BIAS_BUY_DAYS      # 20
OVERSOLD_LOOKBACK = cfg.OVERSOLD_LOOKBACK  # 5
COMMISSION = cfg.COMMISSION            # 0.0002
MIN_COMMISSION = cfg.MIN_COMMISSION    # 5
SLIPPAGE = cfg.SLIPPAGE                # 0.001
LOT = cfg.LOT_SIZE                     # 100


# ---------------- 数据准备 ----------------
def build_matrices(hist, start=None, end=None):
    """把 {code: df} 转成按日期对齐的宽表矩阵。"""
    closes, lows, opens = {}, {}, {}
    for code, df in hist.items():
        d = df.copy()
        d["date"] = d["date"].astype(str).str[:10]
        d = d.drop_duplicates("date").set_index("date").sort_index()
        closes[code] = pd.to_numeric(d["close"], errors="coerce")
        lows[code] = pd.to_numeric(d["low"], errors="coerce")
        opens[code] = pd.to_numeric(d["open"], errors="coerce")

    close = pd.DataFrame(closes).sort_index()
    low = pd.DataFrame(lows).reindex(close.index)
    open_ = pd.DataFrame(opens).reindex(close.index)

    if start:
        close = close[close.index >= start]
    if end:
        close = close[close.index <= end]
    low = low.reindex(close.index)
    open_ = open_.reindex(close.index)

    # 乖离率（逐只按自身序列算，避免 NaN 污染）
    ma20 = close.rolling(BIAS_BUY_DAYS, min_periods=BIAS_BUY_DAYS).mean()
    ma50 = close.rolling(BIAS_SORT_DAYS, min_periods=BIAS_SORT_DAYS).mean()
    bias20 = (close / ma20 - 1.0) * 100.0
    bias50 = (close / ma50 - 1.0) * 100.0
    bmin5 = bias20.rolling(OVERSOLD_LOOKBACK, min_periods=1).min()

    return {
        "dates": close.index.tolist(),
        "codes": close.columns.tolist(),
        "close": close.to_numpy(dtype=float),
        "low": low.to_numpy(dtype=float),
        "open": open_.to_numpy(dtype=float),
        "bias20": bias20.to_numpy(dtype=float),
        "bias50": bias50.to_numpy(dtype=float),
        "bmin5": bmin5.to_numpy(dtype=float),
        "valid": close.notna().to_numpy(),
    }


# ---------------- 回测主体 ----------------
def run(m, th_map, *, intraday_stop=True, exec_mode="close", cash0=100000.0,
        stop_loss=STOP_LOSS, sell_profit=SELL_PROFIT, hold_max=HOLD_MAX_DAYS,
        cooldown=COOLDOWN, commission=COMMISSION, slippage=SLIPPAGE, verbose=False):
    """exec_mode: close=当日收盘成交 / next_open=次日开盘成交"""
    dates, codes = m["dates"], m["codes"]
    close, low, open_ = m["close"], m["low"], m["open"]
    bias20, bias50, bmin5, valid = m["bias20"], m["bias50"], m["bmin5"], m["valid"]
    n, k = close.shape

    th = np.array([th_map.get(c, cfg.BUY_BIAS_TH) for c in codes], dtype=float)
    idx_of = {c: i for i, c in enumerate(codes)}

    cash = cash0
    pos = None            # dict(j, shares, entry, entry_t, day_buy)
    equity = np.full(n, np.nan)
    held_flags = []
    trades = []
    last_stop_t = -10 ** 9
    pending_buy = None    # for next_open

    for t in range(n):
        # ---------- A. 次日开盘执行上一日信号 ----------
        if exec_mode == "next_open" and pending_buy is not None:
            j = pending_buy
            px = open_[t, j]
            if np.isfinite(px) and px > 0:
                fill = px * (1 + slippage)
                shares = int(cash * 0.995 / fill // LOT * LOT)
                if shares > 0:
                    cost = shares * fill
                    fee = max(cost * commission, MIN_COMMISSION)
                    if cost + fee <= cash:
                        cash -= cost + fee
                        pos = {"j": j, "shares": shares, "entry": fill,
                               "entry_t": t, "day_buy": t}
                        trades.append({"date": dates[t], "action": "buy", "code": codes[j],
                                       "price": fill, "shares": shares, "fee": fee,
                                       "reason": "抄底候选"})
            pending_buy = None

        # ---------- B. 盘中止损（用当日 low 模拟） ----------
        if pos is not None and intraday_stop and t > pos["day_buy"]:
            j = pos["j"]
            trigger = pos["entry"] * (1 - stop_loss)
            lo = low[t, j]
            if np.isfinite(lo) and lo <= trigger:
                op = open_[t, j]
                fill = trigger
                if np.isfinite(op) and op < trigger:     # 跳空低开 → 按开盘价成交
                    fill = op
                fill *= (1 - slippage)
                gross = pos["shares"] * fill
                fee = max(gross * commission, MIN_COMMISSION)
                cash += gross - fee
                ret = fill / pos["entry"] - 1
                trades.append({"date": dates[t], "action": "sell", "code": codes[j],
                               "price": fill, "shares": pos["shares"], "fee": fee,
                               "reason": "盘中止损", "ret": ret})
                last_stop_t = t
                pos = None

        # ---------- C. 候选池（当日收盘口径） ----------
        cand_mask = (bmin5[t] < th) & valid[t]
        top_j, top_b50 = -1, np.nan
        if cand_mask.any():
            cands = np.where(cand_mask)[0]
            order = cands[np.argsort(bias50[t, cands])]
            top_j = int(order[0])
            top_b50 = bias50[t, top_j]

        # ---------- D. 卖出四道闸门（收盘口径） ----------
        if pos is not None and t > pos["day_buy"]:
            j = pos["j"]
            px = close[t, j]
            if np.isfinite(px) and px > 0:
                ret = px / pos["entry"] - 1
                b20 = bias20[t, j]
                reason = None
                if ret <= -stop_loss:
                    reason = "深套止损"
                elif np.isfinite(b20) and b20 >= SELL_BIAS_TH and ret >= 0:
                    if top_j != j:
                        reason = "回本止盈"
                elif ret >= sell_profit:
                    if top_j != j:
                        reason = "目标收益"
                elif (t - pos["entry_t"]) >= hold_max:
                    # ★ 严格对齐 engine.py：到期后只有「候选第一不是自己」才换仓；
                    #   无候选时线上是 continue（继续持有），不是清仓。
                    if top_j >= 0 and top_j != j:
                        reason = "到期换仓"
                if reason:
                    fill = px * (1 - slippage)
                    gross = pos["shares"] * fill
                    fee = max(gross * commission, MIN_COMMISSION)
                    cash += gross - fee
                    trades.append({"date": dates[t], "action": "sell", "code": codes[j],
                                   "price": fill, "shares": pos["shares"], "fee": fee,
                                   "reason": reason, "ret": fill / pos["entry"] - 1})
                    # ★ 线上只有 intraday_stop_scan 会写 last_stop_date → 冷却只由盘中止损触发
                    if reason == "盘中止损":
                        last_stop_t = t
                    pos = None

        # ---------- E. 买入 ----------
        if pos is None and top_j >= 0:
            in_cool = (t - last_stop_t) < cooldown
            if not in_cool:
                if exec_mode == "next_open":
                    if t + 1 < n:
                        pending_buy = top_j
                else:
                    px = close[t, top_j]
                    if np.isfinite(px) and px > 0:
                        fill = px * (1 + slippage)
                        shares = int(cash * 0.995 / fill // LOT * LOT)
                        if shares > 0:
                            cost = shares * fill
                            fee = max(cost * commission, MIN_COMMISSION)
                            if cost + fee <= cash:
                                cash -= cost + fee
                                pos = {"j": top_j, "shares": shares, "entry": fill,
                                       "entry_t": t, "day_buy": t}
                                trades.append({"date": dates[t], "action": "buy",
                                               "code": codes[top_j], "price": fill,
                                               "shares": shares, "fee": fee,
                                               "reason": "抄底候选"})

        # ---------- F. 收盘估值 ----------
        if pos is not None:
            px = close[t, pos["j"]]
            mtm = pos["shares"] * (px if np.isfinite(px) else pos["entry"])
        else:
            mtm = 0.0
        equity[t] = cash + mtm
        held_flags.append(pos is not None)

    eq = pd.Series(equity, index=pd.to_datetime(dates)).dropna()
    return {"equity": eq, "trades": pd.DataFrame(trades), "dates": dates,
            "exposure": float(np.mean(held_flags)) if held_flags else 0.0}


# ---------------- 绩效 ----------------
def perf(eq, trades, cash0=100000.0, exposure=np.nan):
    if len(eq) < 2:
        return {}
    ret = eq.pct_change().fillna(0.0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / cash0 - 1
    cagr = (eq.iloc[-1] / cash0) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    dd = eq / eq.cummax() - 1
    vol = ret.std() * np.sqrt(252)
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else np.nan

    sells = trades[trades.action == "sell"] if len(trades) else pd.DataFrame()
    wins = (sells["ret"] > 0).sum() if len(sells) else 0
    win_rate = wins / len(sells) if len(sells) else np.nan
    hold = []
    if len(trades):
        buys = trades[trades.action == "buy"].reset_index(drop=True)
        ss = sells.reset_index(drop=True)
        m = min(len(buys), len(ss))
        if m:
            hold = (pd.to_datetime(ss["date"][:m]) - pd.to_datetime(buys["date"][:m])).dt.days.tolist()

    by_year = eq.groupby(eq.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    return {
        "start": str(eq.index[0].date()), "end": str(eq.index[-1].date()),
        "years": round(yrs, 2), "total_return": total, "cagr": cagr,
        "max_dd": float(dd.min()), "vol": vol, "sharpe": sharpe,
        "calmar": cagr / abs(dd.min()) if dd.min() < 0 else np.nan,
        "trades": len(sells), "win_rate": win_rate,
        "avg_hold_days": float(np.mean(hold)) if hold else np.nan,
        "exposure": exposure,
        "by_year": by_year,
        "equity": eq,
    }


def fmt(p, name=""):
    if not p:
        return name + " 无数据"
    return ("%s  %s~%s(%.1fy)  总收益%+.1f%%  年化%+.2f%%  最大回撤%.2f%%  "
            "夏普%.2f  卡玛%.2f  交易%d次  胜率%s  平均持有%.1f日  持仓占比%.1f%%") % (
        name, p["start"], p["end"], p["years"], p["total_return"] * 100,
        p["cagr"] * 100, p["max_dd"] * 100, p["sharpe"], p["calmar"], p["trades"],
        ("%.1f%%" % (p["win_rate"] * 100)) if np.isfinite(p["win_rate"]) else "n/a",
        p["avg_hold_days"] if np.isfinite(p["avg_hold_days"]) else -1,
        (p["exposure"] * 100) if np.isfinite(p["exposure"]) else -1)
