# -*- coding: utf-8 -*-
"""
bt_multi.py —— 多持仓分仓回测引擎（2026-10-20 新增）

为什么单独写一个文件而不改 bt_etf_dip.run()：
  单仓引擎已通过「与线上 signal_alert 6/6 候选、乖离率 0.00pp 一致」的保真校验，
  是基准尺子。改它会让基准失效。这里复制逻辑并只扩展仓位维度，
  并用 max_hold=1 与单仓引擎逐笔对账（应完全同值）来证明等价。

多持仓的关键口径决定（必须显式，否则结果不可比）：

1. 每仓资金 = min(可用现金, 当前总权益 / max_hold)
   max_hold=1 时退化为「用全部现金」，与原引擎完全一致。

2. 卖出参照（与单仓口径的兼容推广）
   单仓原规则是「候选第一名不是自己」才允许卖出（回本止盈/目标收益/到期换仓）。
   多仓的自然推广是「自己不在前 max_hold 名之内」才允许被置换。
   max_hold=1 时：不在前 1 名 ⇔ 第 1 名不是自己 —— 与原规则严格一致。
   （未采用「只要不是第 1 名就卖」，否则 2/3 号仓会被天天换手。）

3. 深套止损 / 盘中止损：逐仓独立判定，与仓位数量无关。

4. 冷却：全局 last_stop_t，任一仓位触发盘中止损即全仓暂停开新仓（保守，沿原意）。
"""
import numpy as np
import pandas as pd

import config as cfg

LOT = cfg.LOT_SIZE
COMMISSION = cfg.COMMISSION
MIN_COMMISSION = cfg.MIN_COMMISSION
SLIPPAGE = cfg.SLIPPAGE
STOP_LOSS = cfg.STOP_LOSS_PCT
SELL_PROFIT = cfg.SELL_PROFIT_PCT
SELL_BIAS_TH = cfg.SELL_BIAS_TH
HOLD_MAX_DAYS = cfg.HOLD_MAX_DAYS
COOLDOWN = cfg.STOP_COOLDOWN_DAYS


def run(m, th_map, *, max_hold=1, intraday_stop=True, exec_mode="close",
        cash0=100000.0, stop_loss=STOP_LOSS, sell_profit=SELL_PROFIT,
        hold_max=HOLD_MAX_DAYS, cooldown=COOLDOWN, commission=COMMISSION,
        slippage=SLIPPAGE, trace=None, uncond_tp=False, trail=None,
        uncond_timeout=False, timeout_live=False, market_gate_ma=0,
        trend_mode=0, scale=None, be_stop=None, cash_yield=0.0,
        idle_ret=None, idle_cost=0.0, min_depth=0.0,
        tick_frac=0.0, protect_lag=0, liq=None, trail_k=0.0, trail_floor=0.04,
        trail_cap=0.20, excess_min=None, excess_max=None, excess_lb=5,
        rank_mat=None, class_cap=None, cls_mat=None, trail_delay=0,
        stop_map=None, size_map=None):
    """rank_mat: (n, m) 排序键矩阵。None=按 bias50 绝对值升序（现行口径）。
        传入则用它排序，用于「按各自历史极端程度排序」（z-score / 分位）。
    class_cap: dict{类别: 最大持仓数}；配合 cls_mat 实现「类内限额」。
    cls_mat:  (n, m) 类别编码矩阵（int），-1=不参与类内限额。"""
    """trace: 传入 list 则记录「止盈条件已成立但被候选排名否决」的事件。
    uncond_tp: True=止盈不等候选（+3% 即卖）
    trail: 移动止盈回撤比例（如 0.08=自持仓最高价回撤 8% 即卖），None=不启用
    uncond_timeout: True=满 hold_max 日无条件清仓（不看候选）
    timeout_live: True=严格对齐线上：满 hold_max 日后，只要「候选第一不是自己」就退出，
                  包括「当天完全没有候选」的情形（线上此时若天基营=空仓即清仓）。
                  默认 False 是早期回测口径（无候选则继续持有），比线上保守。
    """
    dates, codes = m["dates"], m["codes"]
    close, low, open_ = m["close"], m["low"], m["open"]
    bias20, bias50, bmin5, valid = m["bias20"], m["bias50"], m["bmin5"], m["valid"]
    n = close.shape[0]

    th = np.array([th_map.get(c, cfg.BUY_BIAS_TH) for c in codes], dtype=float)

    # ★ 市场闸门（可选）：池内等权指数跌破 N 日均线则不开新仓
    gate = np.ones(n, dtype=bool)
    if market_gate_ma:
        r = close[1:] / close[:-1] - 1.0
        r = np.where(np.isfinite(r), r, np.nan)
        mkt_ret = np.nanmean(r, axis=1)
        mkt_ret = np.where(np.isfinite(mkt_ret), mkt_ret, 0.0)
        idx = np.concatenate([[1.0], np.cumprod(1.0 + mkt_ret)])
        ma = pd.Series(idx).rolling(market_gate_ma).mean().to_numpy()
        gate = np.where(np.isfinite(ma), idx >= ma, True)

    # ★ 个股趋势确认（对应 indicators.check_trend，TREND_FILTER_MODE）
    #   mode 1=非新低（当日价 > 近5根含当日最低） 2=站上均线 3=两者
    #   历史不足 look 根时按"通过"处理，与线上 `if len < look+1: return True` 一致
    if trend_mode:
        look = cfg.TREND_LOOKBACK
        cdf = pd.DataFrame(close)
        rmin = cdf.rolling(look, min_periods=look).min().to_numpy()
        rmean = cdf.rolling(look, min_periods=look).mean().to_numpy()
        not_new_low = np.where(np.isfinite(rmin), close > rmin, True)
        above_ma = np.where(np.isfinite(rmean), close > rmean, True)
        if trend_mode == 1:
            trend_ok = not_new_low
        elif trend_mode == 2:
            trend_ok = above_ma
        else:
            trend_ok = not_new_low & above_ma
    else:
        trend_ok = np.ones_like(close, dtype=bool)

    cash = cash0
    held = {}                 # j -> dict(shares, entry, entry_t, day_buy)
    equity = np.full(n, np.nan)
    held_flags = []
    trades = []
    last_stop_t = -10 ** 9
    pending_buys = []         # for next_open

    # ★ 波动率归一化的移动止盈：trail_i = clip(k × σ20_i, floor, cap)
    #   动机：固定 8% 对日波动 2% 的油气ETF只有 4 个日波动（太紧、易误杀），
    #        对日波动 0.5% 的宽基是 16 个日波动（太松、形同虚设）。
    trail_mat = None
    if trail_k:
        _r = np.diff(np.log(np.where(close > 0, close, np.nan)), axis=0,
                     prepend=np.nan)
        _sig = pd.DataFrame(_r).rolling(20, min_periods=10).std().to_numpy()
        trail_mat = np.clip(trail_k * _sig, trail_floor, trail_cap)
        trail_mat[~np.isfinite(trail_mat)] = trail if trail else 0.08

    # ★ 同步性 / 个体性：候选近 N 日收益 相对 全池中位数 的超额
    #   理论依据 Da/Liu/Schaumburg (2014)：基本面无法解释的收益更容易反转。
    #   全池一起跌 = 情绪/流动性冲击（易反转）；只有它跌 = 个股/主题事件（未必反转）。
    excess = None
    if excess_min is not None or excess_max is not None:
        _c = pd.DataFrame(close)
        _ret = _c / _c.shift(excess_lb) - 1.0
        _med = _ret.median(axis=1)
        excess = (_ret.sub(_med, axis=0)).to_numpy()

    def _slip(px, base, tf):
        """单边滑点：不低于 base，且不低于 tf 个最小报价单位(0.001 元)。
        低价 ETF 的一跳相对成本极高（0.36 元 → 0.28%），统一滑点会系统性低估。"""
        if tf and np.isfinite(px) and px > 0:
            return max(base, tf * 0.001 / px)
        return base

    def buy(j, px, t, reason="抄底候选"):
        nonlocal cash
        if not (np.isfinite(px) and px > 0):
            return False
        fill = px * (1 + _slip(px, slippage, tick_frac))
        total = cash + sum(
            h["shares"] * (close[t, jj] if np.isfinite(close[t, jj]) else h["entry"])
            for jj, h in held.items())
        budget = min(cash, total / max_hold)
        # ★ 波动率目标仓位：高波动标的按比例缩量，空出的现金不计收益
        if size_map:
            budget *= float(size_map.get(codes[j], 1.0))
        if scale is not None:
            budget *= float(scale[t])
        if budget <= 0:
            return False
        shares = int(budget * 0.995 / fill // LOT * LOT)
        if shares <= 0:
            return False
        cost = shares * fill
        fee = max(cost * commission, MIN_COMMISSION)
        if cost + fee > cash:
            return False
        # ★ 闲置资金从 idle 资产切换到策略标的：扣一次切换成本
        if idle_ret is not None and idle_cost:
            cash *= (1.0 - idle_cost)
        cash -= cost + fee
        held[j] = {"shares": shares, "entry": fill, "entry_t": t, "day_buy": t,
                   "stop": (stop_map.get(codes[j], stop_loss) if stop_map else stop_loss)}
        trades.append({"date": dates[t], "action": "buy", "code": codes[j],
                       "price": fill, "shares": shares, "fee": fee, "reason": reason})
        return True

    def sell(j, px, t, reason, pre_slipped=False):
        nonlocal cash
        h = held.pop(j)
        # 盘中止损已在触发器上算好成交价（含跳空），此处不再二次扣滑点
        fill = px if pre_slipped else px * (1 - _slip(px, slippage, tick_frac))
        gross = h["shares"] * fill
        fee = max(gross * commission, MIN_COMMISSION)
        cash += gross - fee
        # ★ 卖出后资金回到 idle 资产：扣一次切换成本
        if idle_ret is not None and idle_cost:
            cash *= (1.0 - idle_cost)
        trades.append({"date": dates[t], "action": "sell", "code": codes[j],
                       "price": fill, "shares": h["shares"], "fee": fee,
                       "reason": reason, "ret": fill / h["entry"] - 1})

    for t in range(n):
        # ---------- A0. 闲置现金：买 idle 资产 或 计息 ----------
        if idle_ret is not None:
            _ir = idle_ret[t]
            if np.isfinite(_ir):
                cash *= (1.0 + _ir)
        elif cash_yield:
            cash *= (1.0 + cash_yield / 252.0)

        # ---------- A. 次日开盘执行 ----------
        if exec_mode == "next_open" and pending_buys:
            for j in pending_buys:
                if len(held) >= max_hold or j in held:
                    continue
                buy(j, open_[t, j], t)
            pending_buys = []

        # ---------- B. 盘中止损（逐仓，用 low 模拟） ----------
        if intraday_stop:
            for j in list(held.keys()):
                h = held[j]
                if t <= h["day_buy"]:
                    continue
                trigger = h["entry"] * (1 - h.get("stop", stop_loss))
                lo = low[t, j]
                if np.isfinite(lo) and lo <= trigger:
                    op = open_[t, j]
                    fill = trigger
                    if np.isfinite(op) and op < trigger:      # 跳空低开
                        fill = op
                    fill *= (1 - slippage)
                    sell(j, fill, t, "盘中止损", pre_slipped=True)
                    last_stop_t = t

        # ---------- C. 候选排名 ----------
        cand_mask = (bmin5[t] < th) & valid[t]
        # ★ 信号深度闸门：只做“比阈值再深 N 个百分点”的信号（浅信号质量差）
        if min_depth:
            cand_mask = cand_mask & ((th - bmin5[t]) >= min_depth)
        if excess_min is not None:
            cand_mask = cand_mask & (excess[t] >= excess_min)
        if excess_max is not None:
            cand_mask = cand_mask & (excess[t] <= excess_max)
        if liq is not None:
            cand_mask = cand_mask & liq[t]
        if trend_mode:
            cand_mask = cand_mask & trend_ok[t]
        order = np.array([], dtype=int)
        if cand_mask.any():
            cands = np.where(cand_mask)[0]
            key = bias50[t] if rank_mat is None else rank_mat[t]
            cands = cands[np.isfinite(key[cands])]
            if len(cands):
                order = cands[np.argsort(key[cands])]
            # ★ 类内限额：把某类别的持仓数卡在 class_cap 以内（None=不限）
            if class_cap and cls_mat is not None and len(order):
                _kept, _cnt = [], {}
                for _j in order:
                    _c = int(cls_mat[t, _j])
                    if _c >= 0 and _c in class_cap:
                        if _cnt.get(_c, 0) >= class_cap[_c]:
                            continue
                        _cnt[_c] = _cnt.get(_c, 0) + 1
                    _kept.append(_j)
                order = np.array(_kept, dtype=int)
        keep_top = set(order[:max_hold].tolist())
        top_j = int(order[0]) if len(order) else -1

        # ---------- D. 卖出四道闸门 ----------
        for j in list(held.keys()):
            h = held[j]
            if t <= h["day_buy"]:
                continue
            px = close[t, j]
            if not (np.isfinite(px) and px > 0):
                continue
            ret = px / h["entry"] - 1
            b20 = bias20[t, j]
            displaceable = j not in keep_top        # max_hold=1 时 ⇔ top_j != j
            reason = None

            # ★ 保护位参考价：protect_lag=0 → 当日收盘（≈14:56 快照，可执行）；
            #   =1 → 前一交易日收盘（14:45 决策时唯一"已确认"的收盘价，零前视）
            if protect_lag and t - protect_lag >= 0:
                _pp = close[t - protect_lag, j]
                px_p = _pp if (np.isfinite(_pp) and _pp > 0) else px
            else:
                px_p = px
            ret_p = px_p / h["entry"] - 1

            # ★ 保本止损（「赚过就绝不再亏」）：浮盈曾达 be_stop 后，回落到成本价即卖
            if be_stop is not None:
                if ret_p >= be_stop:
                    h["armed"] = True
                if h.get("armed") and 0 >= ret_p > -h.get("stop", stop_loss):
                    sell(j, px, t, "保本止损")
                    continue

            # ★ 移动止盈：自建仓以来最高收盘价回撤超过 trail 即卖（独立于候选排名）
            _trail_j = (float(trail_mat[t, j]) if trail_mat is not None
                        else trail)
            if _trail_j and _trail_j > 0:
                peak = h.get("peak", h["entry"])
                if px_p > peak:
                    peak = px_p
                    h["peak"] = px_p
                _hit = (peak > 0 and px_p / peak - 1 <= -_trail_j
                        and ret_p > -h.get("stop", stop_loss))
                if _hit:
                    # ★ trail_delay：触发后需「连续 N 天仍触发」才真卖。
                    #   0=当天触发当天卖（现行）；1=次日仍触发才卖；以此类推。
                    #   动机：止损常落在急跌惯性末端，当天卖出等于卖在最低点。
                    if trail_delay and trail_delay > 0:
                        if h.get("pend_t") is None:
                            h["pend_t"] = t
                        if t - h["pend_t"] >= trail_delay:
                            reason = "移动止盈"
                    else:
                        reason = "移动止盈"
                    if reason and trace is not None:
                        trace.append({"date": dates[t], "code": codes[j],
                                      "event": "移动止盈", "ret": ret,
                                      "peak_ret": peak / h["entry"] - 1})
                else:
                    # 价格回到触发线之上 → 撤销待确认
                    h["pend_t"] = None
                if reason:
                    sell(j, px, t, reason)
                    continue

            if ret <= -h.get("stop", stop_loss):
                reason = "深套止损"
            elif np.isfinite(b20) and b20 >= SELL_BIAS_TH and ret >= 0 and (displaceable or uncond_tp):
                reason = "回本止盈"
            elif ret >= sell_profit and (displaceable or uncond_tp):
                reason = "目标收益"
            elif (t - h["entry_t"]) >= hold_max and (
                    uncond_timeout
                    or (timeout_live and displaceable)          # 线上：不是候选第一就退
                    or (displaceable and top_j >= 0)):          # 早期口径：须有候选
                reason = "到期换仓"

            # ★ 记录「条件已成立但被候选排名否决」——这是高胜率与回撤并存的直接机制
            if reason is None and trace is not None:
                if ret >= sell_profit:
                    trace.append({"date": dates[t], "code": codes[j],
                                  "event": "止盈被否决(+3%已达标但仍是候选第一)",
                                  "ret": ret, "peak_ret": np.nan})
                elif np.isfinite(b20) and b20 >= SELL_BIAS_TH and ret >= 0:
                    trace.append({"date": dates[t], "code": codes[j],
                                  "event": "回本止盈被否决", "ret": ret, "peak_ret": np.nan})

            if reason:
                sell(j, px, t, reason)
                if reason == "盘中止损":
                    last_stop_t = t

        # ---------- E. 开仓 ----------
        if len(held) < max_hold and len(order) and (t - last_stop_t) >= cooldown and gate[t]:
            slots = max_hold - len(held)
            picks = [int(j) for j in order if int(j) not in held][:slots]
            if exec_mode == "next_open":
                if t + 1 < n:
                    pending_buys = picks
            else:
                for j in picks:
                    if len(held) >= max_hold:
                        break
                    buy(j, close[t, j], t)

        # ---------- F. 收盘估值 ----------
        mtm = 0.0
        for j, h in held.items():
            px = close[t, j]
            mtm += h["shares"] * (px if np.isfinite(px) else h["entry"])
        equity[t] = cash + mtm
        held_flags.append(len(held) > 0)

    eq = pd.Series(equity, index=pd.to_datetime(dates)).dropna()
    return {"equity": eq, "trades": pd.DataFrame(trades), "dates": dates,
            "exposure": float(np.mean(held_flags)) if held_flags else 0.0}
