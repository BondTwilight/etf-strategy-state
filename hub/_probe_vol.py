# -*- coding: utf-8 -*-
"""核实「成交量/波动率为什么是 0」

用户说「最近成交量一直在下降」，而口径给 0 分（量能正常）。
要把三件事摊开：
  1. 量比 v5/v20 = ? 逐日成交量到底怎么走
  2. 量比的「水平」和「趋势」是不是两件事
  3. 布林带宽 0.0467 已在极窄区（<0.05），为什么映射到 0 分
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIP = os.path.join(ROOT, "etf_dip_signal")
sys.path.insert(0, DIP)

import market_state as ms  # noqa: E402

PARQ = os.path.join(DIP, "data", "all_etf_1120.parquet")
df = pd.read_parquet(PARQ, columns=["code", "date", "open", "close", "high", "low", "volume"])
df["code"] = df["code"].astype(str)

for code in ("510300", "159915"):
    g = df[df["code"] == code].sort_values("date").dropna(subset=["close"])
    g = g.tail(300).reset_index(drop=True)
    print("=" * 70)
    print("%s  最近 12 个交易日" % code)
    t = g.tail(12)[["date", "close", "volume"]].copy()
    t["量(亿股)"] = (t["volume"] / 1e8).round(2)
    t["较前日%"] = (t["volume"].pct_change() * 100).round(1)
    t["5日均(亿)"] = (g["volume"].rolling(5).mean().tail(12) / 1e8).round(2)
    t["20日均(亿)"] = (g["volume"].rolling(20).mean().tail(12) / 1e8).round(2)
    t["量比v5/v20"] = (g["volume"].rolling(5).mean().tail(12)
                       / g["volume"].rolling(20).mean().tail(12)).round(3)
    print(t[["date", "close", "量(亿股)", "较前日%", "5日均(亿)", "20日均(亿)", "量比v5/v20"]]
          .to_string(index=False))

    v = g["volume"]
    c, h, l = g["close"], g["high"], g["low"]
    v5 = v.rolling(5).mean().iloc[-1]
    v20 = v.rolling(20).mean().iloc[-1]
    print("\n  量比 v5/v20 = %.3f（口径判「正常」区间 0.7~1.5 ⇒ 0 分）" % (v5 / v20))
    # 趋势：最近 5 日量对前 5 日量
    a = v.tail(5).mean()
    b = v.iloc[-10:-5].mean()
    print("  最近5日均量 %.2f 亿 ｜ 前5日均量 %.2f 亿 ⇒ 环比 %+.1f%%"
          % (a / 1e8, b / 1e8, (a / b - 1) * 100))
    # 斜率：最近 10 日成交量对序号回归
    y = v.tail(10).values.astype(float) / 1e8
    x = np.arange(len(y))
    sl = np.polyfit(x, y, 1)[0]
    print("  最近10日成交量线性斜率 %+.3f 亿股/日（负 = 在缩量）" % sl)
    # 逐日下降天数
    d = np.diff(v.tail(11).values)
    print("  最近 10 个日变动里，下降 %d 天 / 上升 %d 天" % (int((d < 0).sum()), int((d > 0).sum())))
    # 口径之外的细节：单日放量倍数 + 与价格方向
    today_v = v.iloc[-1]
    mult = today_v / v20
    chg = c.iloc[-1] / c.iloc[-2] - 1
    combo = ("放量上涨" if (mult > 1.5 and chg > 0) else
             ("放量下跌" if mult > 1.5 else
              ("缩量上涨" if (mult < 0.7 and chg > 0) else
               ("缩量下跌" if mult < 0.7 else "量能平稳"))))
    print("  今日量 %.2f 亿 = 20 日均量的 %.2f 倍（单日口径，比 v5/v20 敏感）"
          % (today_v / 1e8, mult))
    print("  今日涨跌 %+.2f%% ⇒ 组合起来是「%s」（次方四维不含这一层）" % (chg * 100, combo))

    # 波动率
    c, h, l = g["close"], g["high"], g["low"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    prev = atr.iloc[-21:-1].mean()
    bw = (4 * c.rolling(20).std(ddof=0)) / c.rolling(20).mean()
    print("\n  ATR %.4f ｜ 20日变化 %+.2f%%（口径 >+20%% 扣分、<-20%% 加分、其余 0）"
          % (atr.iloc[-1], (atr.iloc[-1] / prev - 1) * 100))
    print("  布林带宽 %.4f（口径 >0.15 加分、<0.05 只提示不变盘、其余 0）" % bw.iloc[-1])
    print("  近 20 日带宽区间 %.4f ~ %.4f（分位 %.0f%%）"
          % (bw.tail(20).min(), bw.tail(20).max(),
             (bw.tail(20).rank(pct=True).iloc[-1]) * 100))
    print()
