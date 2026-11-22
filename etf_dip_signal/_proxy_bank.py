# -*- coding: utf-8 -*-
"""_proxy_bank.py —— 96864「等股灾」样本能不能补足？用代理标的做压力测试

问题：159552（中证2000增强）2024-06-28 才上市，所以真实样本只有 2.1 年，
样本充分度 5.7/12，rankable 过不了。用户要求「把样本补足」。

可以做的不是「把 2.1 年写成 7 年」，而是**代理回测**：
用 512100（中证1000ETF，2016 上市）在 2019-2024 跑同一套规则，
看这套「小盘 + 银行默认腿 + 双 5% 止损」的边缘是否在更长样本里成立。
代理只能提高「结论方向」的置信度，不能把 159552 的真实历史变长。

口径：日线前复权收盘（all_etf_1120.parquet），信号当日收盘成交（比 14:30 略乐观），
费用 万0.5 + 单边 0.1%。
"""
import json
import os

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.join(BASE, "data", "all_etf_1120.parquet")

MAIN = "512100"     # 代理主腿：中证1000ETF（2016 上市）
REAL = "159552"     # 真实主腿：中证2000增强（2024-06 上市）
BANK = "515020"
COST = 0.0005 + 0.001


def load():
    df = pd.read_parquet(PX, columns=["code", "date", "close"])
    df["code"] = df["code"].astype(str)
    px = df.pivot(index="date", columns="code", values="close").sort_index()
    return px[[c for c in (MAIN, REAL, BANK) if c in px.columns]].dropna(how="all")


def wslope(s, n=10):
    """加权斜率 V2：ln 价格 → 权重 linspace(1,2,n)^2 → 加权 OLS → 年化"""
    y = np.log(np.asarray(s, dtype=float))
    if len(y) < n or not np.all(np.isfinite(y[-n:])):
        return np.nan
    y = y[-n:]
    w = np.linspace(1, 2, n) ** 2
    x = np.arange(n)
    xm = np.average(x, weights=w)
    ym = np.average(y, weights=w)
    b = np.sum(w * (x - xm) * (y - ym)) / np.sum(w * (x - xm) ** 2)
    return float(np.exp(b * 250) - 1)


def run(px, main, start, end, lo=0.4, hi=2.5, min_hold=5, stop=0.05):
    d = px.loc[start:end]
    if main not in d.columns or d[main].dropna().empty:
        return None
    main_s = d[main].ffill()
    bank_s = d[BANK].ffill()
    ma10 = main_s.rolling(10).mean()

    pos = BANK          # 空仓期默认持银行
    entry = None
    peak = None
    vals = [1.0]
    trades = []
    hold = 0
    for i in range(11, len(d)):
        px_main, px_bank = main_s.iloc[i], bank_s.iloc[i]
        prev_main, prev_bank = main_s.iloc[i - 1], bank_s.iloc[i - 1]
        # 当日收益（按昨日持仓）
        r = (px_main / prev_main - 1) if pos == main else (px_bank / prev_bank - 1)
        vals.append(vals[-1] * (1 + r))
        hold += 1
        # 止损（双 5%：跌幅 / 高点回撤）
        if pos == main and entry:
            peak = max(peak or px_main, px_main)
            if (px_main / entry - 1 <= -stop) or (px_main / peak - 1 <= -stop):
                pos, entry, peak, hold = BANK, None, None, 0
                trades.append({"d": str(d.index[i])[:10], "a": "stop"})
                continue
        if hold < min_hold:
            continue
        s = wslope(main_s.iloc[:i + 1], 10)
        if not np.isfinite(s):
            continue
        want = main if (lo <= s <= hi and px_main > ma10.iloc[i]) else BANK
        if want != pos:
            pos = want
            hold = 0
            if pos == main:
                entry, peak = px_main, px_main
            trades.append({"d": str(d.index[i])[:10], "a": "switch"})
    eq = pd.Series(vals, index=d.index[10:])
    ret = eq.iloc[-1] - 1
    yrs = (pd.to_datetime(d.index[-1]) - pd.to_datetime(d.index[10])).days / 365.25
    ann = (1 + ret) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    dd = float((eq / eq.cummax() - 1).min())
    return {"start": str(d.index[10])[:10], "end": str(d.index[-1])[:10],
            "years": round(yrs, 1), "ann": round(ann * 100, 2),
            "dd": round(dd * 100, 2), "trades": len(trades),
            "final": round(eq.iloc[-1], 3)}


if __name__ == "__main__":
    px = load()
    print("数据：", px.index.min(), "~", px.index.max(), "｜列", list(px.columns))
    cases = [
        ("代理 512100 · 2020-2024（159552 上市前）", MAIN, "2020-01-02", "2024-06-27"),
        ("真实 159552 · 2024-06 至今", REAL, "2024-06-28", "2026-11-20"),
        ("代理 512100 · 2024-06 至今（同期对照）", MAIN, "2024-06-28", "2026-11-20"),
    ]
    out = {}
    for name, code, s, e in cases:
        r = run(px, code, s, e)
        out[name] = r
        print("%-34s %s" % (name, r))
    json.dump(out, open(os.path.join(BASE, "data", "_proxy96864.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
