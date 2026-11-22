# -*- coding: utf-8 -*-
"""市场状态检测器（对标次方量化）

口径已逐项反解并与次方页面 510300@2026-11-20 校验：
  MA5/10/20、DIF/DEA、BOLL 带宽、5/20 日均量 全部逐位一致
  RSI 用 **简单均值**（41.07，Wilder 会得 30.80 → 说明次方不用 Wilder）
  ATR 用 **简单均值**（0.0639，Wilder 0.0646）
  成交量单位 **亿股**

四维权重：趋势 40% ｜ 动量 30%（MACD+RSI）｜ 波动率 15%（ATR+BOLL）｜ 成交量 15%
综合分 = 0.40·趋势 + 0.30·动量 + 0.15·波动率 + 0.15·成交量
状态：>+30 牛市 ｜ -30~+30 震荡市 ｜ <-30 熊市
置信度 = min(|综合分|/100, 1)

子项映射（次方未公开，本实现定义，公布在页面「评分标准」里）：
  趋势   完全多头 +100 / 部分多头 +50 / 纠缠 0 / 部分空头 -50 / 完全空头 -100
   MACD   强势金叉 +100 / 弱势金叉 +50 / 弱势死叉 -50 / 强势死叉 -100
   RSI    超买 ≥70 +100 / 正常 0 / 超卖 ≤30 -100
   ATR    20日变化率 >+20% -100 / 正常 0 / <-20% +50
   BOLL   带宽 >0.15 +100 / 其余 0（极窄<0.05 单独提示「变盘临近」，不扣分）
   量     量比>1.5 放量：近5日涨 +100 跌 -100 ｜ 0.7~1.5 正常 0 ｜ <0.7 缩量：涨 +30 跌 -30
校验结果：510300@2026-11-20 复算 -32.5 / 熊市 / 置信 32.5%，次方页面 -31.5 / 熊市 / 31%。
"""
import numpy as np
import pandas as pd


def _r(x, n=4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


def indicators(df):
    """df 需含 open/close/high/low/volume，索引为日期。返回末根指标。"""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    ma = {n: c.rolling(n).mean() for n in (5, 10, 20, 60)}
    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    dif = e12 - e26
    dea = dif.ewm(span=9, adjust=False).mean()

    d = c.diff()
    up, dn = d.clip(lower=0), (-d).clip(lower=0)
    rsi = 100 - 100 / (1 + up.rolling(14).mean() / dn.rolling(14).mean())

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    mid = ma[20]
    std = c.rolling(20).std(ddof=0)
    bw = (4 * std) / mid          # (上轨−下轨)/中轨

    v5, v20 = v.rolling(5).mean(), v.rolling(20).mean()
    i = df.index[-1]
    o = {
        "date": i.strftime("%Y-%m-%d"),
        "close": _r(c.iloc[-1]),
        "chg": _r(df["chg"].iloc[-1], 2) if "chg" in df else _r((c.iloc[-1] / c.iloc[-2] - 1) * 100, 2),
        "MA5": _r(ma[5].iloc[-1]), "MA10": _r(ma[10].iloc[-1]),
        "MA20": _r(ma[20].iloc[-1]), "MA60": _r(ma[60].iloc[-1], 4) if len(df) >= 60 else None,
        "DIF": _r(dif.iloc[-1]), "DEA": _r(dea.iloc[-1]),
        "MACD_HIST": _r((dif.iloc[-1] - dea.iloc[-1]) * 2, 4),
        "RSI": _r(rsi.iloc[-1], 2),
        "ATR": _r(atr.iloc[-1], 4),
        "BOLL_bw": _r(bw.iloc[-1], 4),
        "BOLL_up": _r((mid + 2 * std).iloc[-1]),
        "BOLL_dn": _r((mid - 2 * std).iloc[-1]),
        "vol5": _r(v5.iloc[-1] / 1e8, 2), "vol20": _r(v20.iloc[-1] / 1e8, 2),
        "vol_ratio": _r(v5.iloc[-1] / v20.iloc[-1], 3),
        "ret5": _r((c.iloc[-1] / c.iloc[-6] - 1) * 100, 2) if len(df) > 6 else None,
    }
    prev = atr.iloc[-21:-1].mean()
    o["ATR_chg"] = _r((atr.iloc[-1] / prev - 1) * 100, 2) if prev and np.isfinite(prev) else None
    return o


def score(o):
    """四维打分。返回明细 + 综合 + 状态 + 置信度。"""
    # ---- 趋势：MA 排列（完全需 close 与 MA60 同向）
    m5, m10, m20 = o["MA5"], o["MA10"], o["MA20"]
    m60 = o.get("MA60")
    bull = m5 > m10 > m20 and (m60 is None or m20 > m60)
    bear = m5 < m10 < m20 and (m60 is None or m20 < m60)
    if bull:
        t, t_lab = 100, "完全多头"
    elif bear:
        t, t_lab = -100, "完全空头"
    elif m5 > m10 and m10 <= m20:
        t, t_lab = 50, "部分多头（短期拐头）"
    elif m5 < m10 and m10 >= m20:
        t, t_lab = -50, "部分空头（短期拐头）"
    else:
        t, t_lab = 0, "纠缠"

    # ---- 动量：MACD 四档 + RSI 三档
    dif, dea, rsi = o["DIF"], o["DEA"], o["RSI"]
    if dif > dea and dif > 0:
        mc, mc_lab = 100, "强势金叉"
    elif dif > dea:
        mc, mc_lab = 50, "弱势金叉"
    elif dif < dea and dif < 0:
        mc, mc_lab = -100, "强势死叉"
    else:
        mc, mc_lab = -50, "弱势死叉"
    if rsi >= 70:
        rs, rs_lab = 100, "超买"
    elif rsi <= 30:
        rs, rs_lab = -100, "超卖"
    else:
        rs, rs_lab = 0, "正常"
    mom = 0.5 * mc + 0.5 * rs

    # ---- 波动率：ATR 变化 + BOLL 带宽
    ac = o.get("ATR_chg")
    if ac is None:
        at, at_lab = 0, "无数据"
    elif ac > 20:
        at, at_lab = -100, "波动率快速上升"
    elif ac < -20:
        at, at_lab = 50, "波动率收敛"
    else:
        at, at_lab = 0, "波动率正常"
    bw = o["BOLL_bw"]
    if bw > 0.15:
        bt, bt_lab = 100, "趋势强劲"
    elif bw < 0.05:
        bt, bt_lab = 0, "极窄·等待方向"
    else:
        bt, bt_lab = 0, "正常"
    vol = 0.5 * at + 0.5 * bt

    # ---- 成交量：量比 × 近5日方向
    vr, r5 = o["vol_ratio"], o["ret5"]
    if vr is None:
        vt, vt_lab = 0, "无数据"
    elif vr > 1.5:
        if r5 is not None and r5 >= 0:
            vt, vt_lab = 100, "放量上涨"
        else:
            vt, vt_lab = -100, "放量下跌"
    elif vr < 0.7:
        if r5 is not None and r5 >= 0:
            vt, vt_lab = 30, "缩量上涨"
        else:
            vt, vt_lab = -30, "缩量下跌"
    else:
        vt, vt_lab = 0, "量能正常"

    total = 0.40 * t + 0.30 * mom + 0.15 * vol + 0.15 * vt
    if total > 30:
        state, scls = "牛市", "bull"
    elif total < -30:
        state, scls = "熊市", "bear"
    else:
        state, scls = "震荡市", "range"
    conf = min(abs(total) / 100.0, 1.0)

    return {
        "total": _r(total, 1),
        "state": state, "cls": scls,
        "conf": _r(conf * 100, 1),
        "conf_note": ("判断不可靠，方向并不明确" if conf < 0.3 else
                      ("可以当作重要参考" if conf > 0.7 else "中等强度，需结合其他证据")),
        "dims": [
            {"k": "趋势", "w": 40, "v": _r(t, 1), "label": t_lab,
             "detail": "MA5 %.3f ｜ MA10 %.3f ｜ MA20 %.3f%s"
                       % (m5, m10, m20, "" if m60 is None else " ｜ MA60 %.3f" % m60),
             "why": "完全多头 +100 / 完全空头 −100；均线纠缠才是 0"},
            {"k": "动量", "w": 30, "v": _r(mom, 1), "label": "%s / RSI %s" % (mc_lab, rs_lab),
             "detail": "DIF %.4f %s DEA %.4f ｜ RSI %.2f"
                       % (dif, ">" if dif > dea else "<", dea, rsi),
             "why": "MACD 四档（±100/±50）与 RSI 三档（超买+100/超卖−100/正常 0）各半"},
            {"k": "波动率", "w": 15, "v": _r(vol, 1), "label": "%s / %s" % (at_lab, bt_lab),
             "detail": "ATR %.4f（20日变化 %+.1f%%）｜ 布林带宽 %.4f"
                       % (o["ATR"], o["ATR_chg"] or 0, bw),
             # 0 分不是没数据：ATR 变化在 ±20% 内、布林带宽在 0.05~0.15 之间都算中性。
             # 把「离触发还差多少」写出来，用户才不会以为是坏值。
             "why": "ATR 20日变化 %+.1f%%（±20%% 外才计分，还差 %.1fpp）｜ 带宽 %.4f（<0.05 极窄、>0.15 才给强趋势分）"
                    % (o["ATR_chg"] or 0, max(0.0, 20 - abs(o["ATR_chg"] or 0)), bw)},
            {"k": "成交量", "w": 15, "v": _r(vt, 1), "label": vt_lab,
             "detail": "5日均量 %.2f 亿股 / 20日均量 %.2f 亿股 ⇒ 量比 %.2f"
                       % (o["vol5"], o["vol20"], vr),
             "why": "量比 %.2f：>1.5 才放量（还差 %.2f），<0.7 才缩量；中间一律中性 0"
                    % (vr or 0, max(0.0, 1.5 - (vr or 0)))},
        ],
        "squeeze": bool(bw < 0.05),
    }


def detect(df):
    o = indicators(df)
    s = score(o)
    return {"ind": o, "score": s}


def chart_series(df, n=90):
    """K 线图数据：末 n 根的 OHLCV + MA5/MA20 + 布林带。"""
    d = df.tail(n).copy()
    ma5 = df["close"].rolling(5).mean().tail(n)
    ma20 = df["close"].rolling(20).mean().tail(n)
    std = df["close"].rolling(20).std(ddof=0).tail(n)
    out = []
    for (dt, row), a, b, s in zip(d.iterrows(), ma5.values, ma20.values, std.values):
        out.append({
            "d": dt.strftime("%Y-%m-%d"),
            "o": _r(row["open"], 3), "c": _r(row["close"], 3),
            "h": _r(row["high"], 3), "l": _r(row["low"], 3),
            "v": _r(row["volume"] / 1e8, 2),
            "ma5": None if not np.isfinite(a) else round(float(a), 3),
            "ma20": None if not np.isfinite(b) else round(float(b), 3),
            "bu": None if not np.isfinite(b) else round(float(b + 2 * s), 3),
            "bd": None if not np.isfinite(b) else round(float(b - 2 * s), 3),
        })
    return out
