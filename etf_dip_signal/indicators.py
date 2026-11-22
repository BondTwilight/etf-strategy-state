# -*- coding: utf-8 -*-
"""
indicators.py —— 指标计算模块
对应聚宽策略中的：
  calculate_bias_intraday      -> calculate_bias()
  check_trend_intraday         -> check_trend()
  check_oversold_stabilized_intraday -> check_oversold_stabilized()
  _get_close_with_today        -> get_close_series()
"""

import numpy as np
import pandas as pd
import datetime as _dt

import config as cfg
import data_quality
from tdx_api import get_daily_kline, get_realtime


def _sanitize(closes):
    """★ 2026-10-20 新增：单日跳变清洗（|涨跌|>30% 视为脏数据，前缀等比缩放修复）。

    为什么必须放在指标层：
      抄底策略专门在暴跌日买入，一根假 -70% 的脏 K 线就能伪造一个超卖买点，
      以假低价全仓买入后再"恢复"，账面会出现几百个点的假收益。
      （实测次方 qfq 源 381 只里有 55 只、116 根此类脏数据）
    乖离率是比值型指标，前缀等比缩放不改变任何历史乖离率，因此本清洗零副作用。
    """
    if not getattr(cfg, 'SANITIZE_QUOTES', True):
        return closes
    arr = np.asarray(closes, dtype=float)
    if len(arr) < 2:
        return closes
    df = pd.DataFrame({'close': arr})
    fixed, hits = data_quality.repair_prices(df)
    if not hits:
        return closes
    return fixed['close'].to_numpy(dtype=float)


def _use_cifang():
    """是否启用次方量化作历史日线源（DATA_SOURCE='cifang'）。"""
    return str(getattr(cfg, 'DATA_SOURCE', 'web')).lower() == 'cifang'


def get_close_series(code: str, hist_count: int, include_today: bool = True,
                     today_price: float = None) -> pd.DataFrame:
    """返回最近 hist_count 根日线 close（T-1及之前），可选用 T 日实时价替换/衔接。
    完全对应 _get_close_with_today() 的逻辑。

    ★ 关键修正（2026-10-13）：
      腾讯日线的"末根"在不同时点含义不同，必须区分三种情况，否则会重复计算：
        情况A：日线末根 date == 今天 → 实时价【替换】末根
        情况B：日线末根 date < 今天，但实时价 == 末根收盘价（盘前/收盘后）
               → 两者是"同一根"，【不追加】
        情况C：日线末根 date < 今天，且实时价 != 末根收盘价（盘中）
               → 【追加】实时价作为当日
    """
    if hist_count < 0:
        hist_count = 0
    df = get_daily_kline(code, count=max(hist_count, 1) + 2)
    if df.empty:
        return None
    close = df['close'].astype(float).reset_index(drop=True)
    # ★ 先清洗历史（含当日）再拼接实时价，避免"脏昨天 + 真今天"被误判为跳变
    close = pd.Series(_sanitize(close.to_numpy(dtype=float)))

    if include_today:
        if today_price is None or not np.isfinite(today_price) or today_price <= 0:
            return None
        today_str = _dt.date.today().strftime('%Y-%m-%d')
        last_date = ''
        if 'date' in df.columns and len(df) > 0:
            last_date = str(df['date'].iloc[-1])[:10]
        last_close = float(close.iloc[-1]) if len(close) > 0 else None
        if last_date == today_str:
            # 情况A：日线末根已是当日 → 用实时价替换，避免重复
            close = close.iloc[:-1].reset_index(drop=True)
            close = pd.concat([close, pd.Series([float(today_price)])],
                              ignore_index=True)
        elif last_close is not None and abs(float(today_price) - last_close) < 1e-9:
            # 情况B：实时价与末根同值（未开盘）→ 不追加，避免重复
            pass
        else:
            # 情况C：盘中，日线尚未含当日 → 追加实时价作为当日
            close = pd.concat([close, pd.Series([float(today_price)])],
                              ignore_index=True)

    if hist_count > 0:
        return close.iloc[-hist_count:].reset_index(drop=True)
    return close


def calculate_bias(codes, rt_df: pd.DataFrame, kline_map: dict = None) -> pd.DataFrame:
    """计算全部候选 ETF 的 20 日 / 50 日乖离率。
    返回列：代码 / 名称 / 20日乖离率(%) / 50日乖离率(%)
    ★ 若传入 kline_map（预取的并发日线），则零网络开销。
    """
    need = max(cfg.BIAS_SORT_DAYS, cfg.BIAS_BUY_DAYS)
    price_map = dict(zip(rt_df['code'], rt_df['price'])) if not rt_df.empty else {}

    # 若未预取，则批量拉取
    if kline_map is None:
        if _use_cifang():
            # ★ 2026-10-20：次方量化前复权（50只/请求，8 批拉完 381 只）
            import cifang_quote
            kline_map = cifang_quote.prefetch_batch(codes, count=need + 12)
            if len(kline_map) < len(codes) * 0.90:
                # 次方覆盖不足 → 缺的用原链路补齐，不让池子残缺
                import web_quote
                for c in codes:
                    if c in kline_map:
                        continue
                    d = web_quote.fetch_daily_kline(c, count=need + 2)
                    if d is not None and not d.empty:
                        kline_map[c] = d
        else:
            import web_quote
            kline_map = web_quote.fetch_daily_kline_batch(codes, count=need + 2)

    records = []
    today_str = _dt.date.today().strftime('%Y-%m-%d')
    for code in codes:
        last_price = price_map.get(code)
        if last_price is None or last_price <= 0:
            continue
        df = kline_map.get(code)
        if df is None or df.empty:
            continue
        closes_full = pd.to_numeric(df['close'], errors='coerce').dropna().tolist()
        if len(closes_full) < need:
            continue
        # ★ 单日跳变清洗（脏 K 线会伪造假的深超卖买点）
        closes_full = list(_sanitize(np.asarray(closes_full, dtype=float)))
        # 取"日线末根"的日期与收盘价，用于判断实时价是否代表同一根
        last_k_date = ''
        last_k_close = None
        if 'date' in df.columns and len(df) > 0:
            last_k_date = str(df['date'].iloc[-1])[:10]
        if len(closes_full) > 0:
            last_k_close = float(closes_full[-1])

        # ★ 正确的当日价格口径（务必与同花顺/聚宽一致）：
        #   情况A：日线末根日期 == 今天（日线已含当日未完成K线）
        #           → 用实时价【替换】末根，绝不再追加
        #   情况B：日线末根日期 < 今天，但实时价 == 末根收盘价
        #           （盘前/收盘后，实时价就是上一交易日收盘）
        #           → 实时价与末根是"同一根"，【不追加】，直接用日线原序列
        #   情况C：日线末根日期 < 今天，且实时价 != 末根收盘价
        #           （盘中已开盘，日线尚未更新当日）
        #           → 【追加】实时价作为当日
        if last_k_date == today_str:
            closes = closes_full[:-1] + [float(last_price)]
        elif last_k_close is not None and abs(float(last_price) - last_k_close) < 1e-9:
            closes = closes_full                      # 同一根，不追加
        else:
            closes = closes_full + [float(last_price)]  # 追加真正的当日
        closes = closes[-need:]
        close = pd.Series(closes)
        last = float(close.iloc[-1])
        ma_buy = close.rolling(cfg.BIAS_BUY_DAYS).mean().iloc[-1]
        ma_sort = close.rolling(cfg.BIAS_SORT_DAYS).mean().iloc[-1]
        if not np.isfinite(ma_buy) or not np.isfinite(ma_sort) or ma_buy <= 0 or ma_sort <= 0:
            continue
        bias_buy = (last - ma_buy) / ma_buy * 100
        bias_sort = (last - ma_sort) / ma_sort * 100
        records.append({
            '代码': code,
            '20日乖离率(%)': bias_buy,
            '50日乖离率(%)': bias_sort,
        })
    return pd.DataFrame(records) if records else pd.DataFrame()


def check_trend(code: str, mode: int, rt_df: pd.DataFrame) -> bool:
    """趋势过滤器，对应 check_trend_intraday()。
    mode 0 = 不启用；1 = 非新低；2 = 站上均线；3 = 两者

    ★ 口径统一（2026-10-15）：两个 mode 全部改用「含当日的最近 TREND_LOOKBACK 根」，
      第 T 根 = 计算时点(14:50)的实时价，与候选池 check_oversold_stabilized 完全一致。
      - mode1「非新低」：当日价 > 近5根(含当日)最低价 ⇔ 当日不是最近5日的最低点
        （旧口径为 T-5..T-1 不含当日，已弃用）
      - mode2「站上均线」：当日价 > 近5根(含当日)均值
    """
    if mode == 0:
        return True
    look = cfg.TREND_LOOKBACK
    price_map = dict(zip(rt_df['code'], rt_df['price'])) if not rt_df.empty else {}
    close = get_close_series(code, look + 1, include_today=True,
                             today_price=price_map.get(code))
    if close is None or len(close) < look + 1:
        return True
    last = float(close.iloc[-1])
    recent = close.iloc[-look:]                  # ★ 含当日的近 look 根
    ma = float(recent.mean())
    recent_low = float(recent.min())
    not_new_low = last > recent_low
    above_ma = last > ma
    if mode == 1:
        return not_new_low
    if mode == 2:
        return above_ma
    if mode == 3:
        return not_new_low and above_ma
    return True


def check_oversold_stabilized(code: str, rt_df: pd.DataFrame,
                              buy_bias_th_map: dict) -> bool:
    """超卖企稳判断，对应 check_oversold_stabilized_intraday()。
    条件：近 OVERSOLD_LOOKBACK 根的 20 日乖离率最小值 < 该 ETF 阈值，且趋势过滤通过。

    ★ 修正（2026-10-13）：原实现取 need-1 根却判断 len<need，导致恒为 False、
      抄底候选池永远为空。正确理解：计算"最近 5 根各自的 20 日乖离率"，
      至少需要 20 + 5 - 1 = 24 根收盘价。
    """
    need = 20 + cfg.OVERSOLD_LOOKBACK - 1    # 24 = 20日均线 + 近5根最少所需
    price_map = dict(zip(rt_df['code'], rt_df['price'])) if not rt_df.empty else {}
    last_price = price_map.get(code)
    if last_price is None or last_price <= 0:
        return False
    close = get_close_series(code, need, include_today=True, today_price=last_price)
    if close is None or len(close) < need:
        return False
    ma20 = close.rolling(20).mean()
    bias20 = (close / ma20 - 1) * 100
    recent = bias20.iloc[-cfg.OVERSOLD_LOOKBACK:]
    if recent.isna().all():
        return False
    th = buy_bias_th_map.get(code, cfg.BUY_BIAS_TH)
    if recent.min() >= th:
        return False
    return check_trend(code, cfg.TREND_FILTER_MODE, rt_df)
