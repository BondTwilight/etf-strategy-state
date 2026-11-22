# -*- coding: utf-8 -*-
"""_px.py —— 价格源统一层

两种口径，明确分开，不许混用：

  收盘价口径（研究基准）  data/all_etf_1120.parquet
  执行时点口径（实盘口径）data/intraday_1430/1445/1450.parquet
                          data/all_etf_1445.parquet（381 池，含 OHLC）

为什么必须两种都留：
  平台用 14:30 分时价选股与成交，本地只有收盘价时，日偏差 |中位| 0.19%、P90 0.62%，
  9 年复利后被放大成 10pp 级别的复现误差 —— 这是口径问题，不是策略问题。
  但研究结论（参数选择、起点扫描）又必须能在长历史上跑，所以收盘价库仍然保留。
"""
import os

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

CACHE = {}


def _read(name):
    p = os.path.join(DATA, name)
    return pd.read_parquet(p) if os.path.exists(p) else None


def wide(tag, warm=True):
    """{tag: '1430'|'1445'|'1450'} → 宽表（index=date, columns=code, values=close）"""
    key = "w_" + tag
    if key in CACHE:
        return CACHE[key]
    df = _read("intraday_%s.parquet" % tag)
    if df is None:
        return None
    df["code"] = df["code"].astype(str)
    p = df.pivot(index="date", columns="code", values="close").sort_index()
    if warm:
        w = _read("intraday_%s_warm.parquet" % tag)
        if w is not None:
            w["code"] = w["code"].astype(str)
            pw = w.pivot(index="date", columns="code", values="close").sort_index()
            p = pd.concat([pw, p])
            p = p[~p.index.duplicated(keep="last")].sort_index()
    CACHE[key] = p
    return p


def close_wide(start="2015-01-05"):
    key = "close"
    if key in CACHE:
        return CACHE[key]
    df = _read("all_etf_1120.parquet")
    df["code"] = df["code"].astype(str)
    df["date"] = pd.to_datetime(df["date"].astype(str).str[:10])
    p = df.pivot(index="date", columns="code", values="close").sort_index()
    p = p.loc[start:]
    CACHE[key] = p
    return p


def hist_1445():
    """381 池 14:45 的 OHLCV，供 bt.build_matrices 用。返回 {code: DataFrame}"""
    key = "h1445"
    if key in CACHE:
        return CACHE[key]
    df = _read("all_etf_1445.parquet")
    if df is None:
        return None
    df["code"] = df["code"].astype(str)
    out = {}
    for c, g in df.groupby("code"):
        g = g.drop_duplicates("date").sort_values("date")
        out[c] = g[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    CACHE[key] = out
    return out


def pair(tag, a="159552", b="515020"):
    p = wide(tag)
    if p is None:
        return None
    return pd.DataFrame({"main": p[a], "bank": p[b]}).dropna()


def describe():
    """给看板用的口径自述"""
    rows = []
    for tag, hh in (("1430", "14:30"), ("1445", "14:45"), ("1450", "14:50")):
        p = wide(tag)
        if p is None:
            continue
        rows.append({"tag": tag, "time": hh, "codes": int(p.shape[1]),
                     "rows": int(len(p)),
                     "from": str(p.index.min().date()), "to": str(p.index.max().date())})
    h = hist_1445()
    return {"intraday": rows,
            "pool1445": (None if h is None else
                         {"codes": len(h), "rows": int(sum(len(v) for v in h.values()))})}
