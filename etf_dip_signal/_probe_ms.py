# -*- coding: utf-8 -*-
"""市场状态检测器：口径反解 + 对齐校验（对标次方 510300 2026-11-22 读数）"""
import json
import os
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

KEY = "ak_REPLACE_WITH_SECRET"
BASE = "https://www.cifangquant.com/api"
HDR = {"x-api-key": KEY, "User-Agent": "Mozilla/5.0"}
HERE = os.path.dirname(os.path.abspath(__file__))


def hist(sym, s, e, adjust="none"):
    q = urllib.parse.urlencode({"symbol": sym, "start_date": s, "end_date": e,
                                "adjust": adjust})
    req = urllib.request.Request(BASE + "/fund/hist_em?" + q, headers=HDR)
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8"))
    rows = d["data"][sym]
    df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low",
                                     "chg", "volume", "amount", "iopv"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for c in ["open", "close", "high", "low", "volume", "amount"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def indicators(df, tag=""):
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    ma5, ma10, ma20 = c.rolling(5).mean(), c.rolling(10).mean(), c.rolling(20).mean()
    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    dif = e12 - e26
    dea = dif.ewm(span=9, adjust=False).mean()

    # RSI 14：Wilder 与 简单均值 两种
    d = c.diff()
    up, dn = d.clip(lower=0), (-d).clip(lower=0)
    rsi_w = 100 - 100 / (1 + up.ewm(alpha=1 / 14, adjust=False).mean() /
                         dn.ewm(alpha=1 / 14, adjust=False).mean())
    rsi_s = 100 - 100 / (1 + up.rolling(14).mean() / dn.rolling(14).mean())

    # ATR 14
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_w = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr_s = tr.rolling(14).mean()

    mid = ma20
    std = c.rolling(20).std(ddof=0)
    bw = (2 * std * 2) / mid          # (upper-lower)/mid = 4*std/mid

    v5, v20 = v.rolling(5).mean(), v.rolling(20).mean()

    i = df.index[-1]
    out = {
        "date": i.strftime("%Y-%m-%d"),
        "close": round(float(c.iloc[-1]), 4),
        "MA5": round(float(ma5.iloc[-1]), 4), "MA10": round(float(ma10.iloc[-1]), 4),
        "MA20": round(float(ma20.iloc[-1]), 4),
        "DIF": round(float(dif.iloc[-1]), 4), "DEA": round(float(dea.iloc[-1]), 4),
        "RSI_wilder": round(float(rsi_w.iloc[-1]), 2),
        "RSI_simple": round(float(rsi_s.iloc[-1]), 2),
        "ATR_wilder": round(float(atr_w.iloc[-1]), 4),
        "ATR_simple": round(float(atr_s.iloc[-1]), 4),
        "BOLL_bw": round(float(bw.iloc[-1]), 4),
        "vol5_yi": round(float(v5.iloc[-1]) / 1e8, 2),
        "vol20_yi": round(float(v20.iloc[-1]) / 1e8, 2),
        "vol_ratio": round(float(v5.iloc[-1] / v20.iloc[-1]), 3),
        "amt5_yi": round(float(df["amount"].rolling(5).mean().iloc[-1]) / 1e8, 2),
        "amt20_yi": round(float(df["amount"].rolling(20).mean().iloc[-1]) / 1e8, 2),
    }
    atr_prev = atr_w.iloc[-21:-1].mean()
    out["ATR_chg_pct"] = round(float(atr_w.iloc[-1] / atr_prev - 1) * 100, 2)

    if tag:
        print("--- %s ---" % tag)
        for k, vv in out.items():
            print("   %-12s %s" % (k, vv))
    return out


print("次方页面读数（510300，2026-05-26 ~ 2026-11-22）：")
print("   MA5 4.046 / MA10 4.084 / MA20 4.107")
print("   DIF -0.0700 / DEA -0.0741")
print("   RSI 41.07 ｜ ATR 0.0639 ｜ BOLL带宽 0.0467")
print("   5日均量 26.45亿 / 20日均量 20.59亿 ｜ 综合 -31.5 ｜ 置信 31%\n")

long = hist("510300", "2018-01-01", "2026-11-22")
r_long = indicators(long, "全历史起点（2018-01-01 起，EMA 更稳）")

win = long.loc["2026-05-26":]
r_win = indicators(win, "仅区间起点（2026-05-26 起，EMA 会被窗口污染）")

print("\n与目标对比：")
tgt = {"MA5": 4.046, "MA10": 4.084, "MA20": 4.107, "DIF": -0.0700, "DEA": -0.0741,
       "RSI_wilder": 41.07, "ATR_wilder": 0.0639, "BOLL_bw": 0.0467,
       "vol5_yi": 26.45, "vol20_yi": 20.59}
for k, t in tgt.items():
    a, b = r_long.get(k), r_win.get(k)
    fmt = "%+.4f" if isinstance(t, float) and abs(t) < 10 else "%.2f"
    print("  %-12s 目标 %-9s 全历史 %-9s 区间 %-9s  %s" % (
        k, ("%g" % t), ("%g" % a), ("%g" % b),
        "OK" if a is not None and abs(a - t) <= max(0.002, abs(t) * 0.002) else "差异"))

with open(os.path.join(HERE, "data", "_ms_probe.json"), "w", encoding="utf-8") as f:
    json.dump({"target": tgt, "full": r_long, "window": r_win}, f,
              ensure_ascii=False, indent=1)
