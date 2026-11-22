# -*- coding: utf-8 -*-
"""逐位验证 score_core.js 与 Python 侧口径一致

对比三组：
  1. 市场状态检测器（510300）—— 对齐 etf_dip_signal/market_state.py
  2. 环境判据 4 条 + regime 分档 —— 对齐 etf_dip_signal/_sim.py regime_series()
  3. 策略适配排序 —— 对齐 hub.regime_matrix

任何一项偏差超过 1e-3 就必须修 JS，不能带着误差上线。
"""
import io
import json
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
N_CLOSE, N_OHLCV = 800, 260


def load(codes):
    df = pd.read_parquet(PARQ, columns=["code", "date", "open", "close",
                                        "high", "low", "volume"])
    df["code"] = df["code"].astype(str)
    return df[df["code"].isin(set(codes))].sort_values(["code", "date"])


def round_map(df, n):
    """模拟 _build_live.load_score_data 的取数与舍入，保证两边同源同精度"""
    close_map, ohlcv_map, dates = {}, {}, None
    for c, g in df.groupby("code"):
        g = g.dropna(subset=["close"])
        gc = g.tail(N_CLOSE)
        close_map[c] = [round(float(x), 3) for x in gc["close"].tolist()]
        if c in ("510300", "159915", "515450"):
            go = g.tail(n)
            ohlcv_map[c] = [[round(float(a), 3), round(float(b), 3),
                             round(float(d), 3), round(float(e), 3), int(f)]
                            for a, b, d, e, f in zip(go["open"], go["high"],
                                                     go["low"], go["close"],
                                                     go["volume"])]
            ds = [str(x)[:10] for x in go["date"].tolist()]
            if dates is None or len(ds) > len(dates):
                dates = ds
    return close_map, ohlcv_map, dates


def py_market_state(ohlcv, dates):
    df = pd.DataFrame(ohlcv, columns=["open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(dates)
    return ms.detect(df)


def py_regime(cl):
    """_sim.regime_series 的单点等价实现（同一公式，只取最后一日）"""
    hs = pd.Series(cl["510300"], dtype="float64").ffill()
    cy = pd.Series(cl["159915"], dtype="float64").ffill()
    dv = pd.Series(cl["510880"], dtype="float64").ffill()
    ma200 = hs.rolling(200, min_periods=120).mean()
    dev = hs / ma200 - 1
    below = bool(hs.iloc[-1] < ma200.iloc[-1])
    r20_cy = cy.pct_change(20)
    r20_dv = dv.pct_change(20)
    gmd = r20_cy - r20_dv
    vol = cy.pct_change().rolling(20).std() * np.sqrt(252)
    vp = vol.rolling(750, min_periods=250).apply(
        lambda a: float((a[:-1] < a[-1]).mean()), raw=True)
    v = float(vp.iloc[-1]) if np.isfinite(vp.iloc[-1]) else 0.5
    g = float(gmd.iloc[-1])
    dr = float(r20_dv.iloc[-1])
    if below and v >= 0.85 and dr < -0.05:
        code = "D"
    elif below and g < 0:
        code = "B"
    elif below:
        code = "Bp"
    elif v < 0.50:
        code = "A"
    else:
        code = "C"
    ma200d = dv.rolling(200, min_periods=120).mean()
    return {
        "code": code,
        "dev": float(dev.iloc[-1]),
        "vp": v,
        "gmd": g,
        "r20dv": dr,
        "dDev": float(dv.iloc[-1] / ma200d.iloc[-1] - 1),
        "below": below,
    }


def main():
    df = load(["510300", "159915", "510880", "515450"])
    close_map, ohlcv_map, dates = round_map(df, N_OHLCV)

    print("数据：close %d 只 ｜ OHLCV %d 只 ｜ 日期 %s ~ %s（%d 根）"
          % (len(close_map), len(ohlcv_map), dates[0], dates[-1], len(dates)))

    # ---------- 1. 市场状态 ----------
    print("\n=== 1. 市场状态检测器 510300 ===")
    o = ohlcv_map["510300"]
    py = py_market_state(o, dates[-len(o):])
    print("  Python  ind: MA5 %.4f MA10 %.4f MA20 %.4f MA60 %.4f"
          % (py["ind"]["MA5"], py["ind"]["MA10"], py["ind"]["MA20"], py["ind"]["MA60"]))
    print("          DIF %.4f DEA %.4f RSI %.2f ATR %.4f BW %.4f 量比 %.3f"
          % (py["ind"]["DIF"], py["ind"]["DEA"], py["ind"]["RSI"],
             py["ind"]["ATR"], py["ind"]["BOLL_bw"], py["ind"]["vol_ratio"]))
    print("          score %.1f %s conf %.1f" % (py["score"]["total"],
                                                py["score"]["state"], py["score"]["conf"]))
    print("          dims:", [(d["k"], d["v"]) for d in py["score"]["dims"]])

    # ---------- 2. 环境判据 ----------
    print("\n=== 2. 环境判据 ===")
    pr = py_regime(close_map)
    print("  Python  regime=%s ｜ dev %+.4f ｜ vp %.4f ｜ gmd %+.4f ｜ r20dv %+.4f ｜ dDev %+.4f"
          % (pr["code"], pr["dev"], pr["vp"], pr["gmd"], pr["r20dv"], pr["dDev"]))

    # ---------- 3. 适配矩阵 ----------
    hub = json.load(io.open(os.path.join(HERE, "hub.json"), encoding="utf-8"))
    mx = hub["regime_matrix"]
    print("\n=== 3. 适配矩阵（当前档 %s）===" % pr["code"])
    idx = [i for i, r in enumerate(mx["regimes"]) if r["k"] == pr["code"]]
    if idx:
        for row in mx["rows"]:
            c = row["cells"][idx[0]]
            print("  %-12s bp=%s win=%s n=%s" % (row["id"], c and c.get("mean_bp"),
                                                 c and c.get("win"), c and c.get("n")))

    # ---------- 输出给 JS 对比 ----------
    payload = {
        "close": close_map,
        "ohlcv": ohlcv_map,
        "dates": dates,
        "date": dates[-1],
    }
    with io.open(os.path.join(HERE, "_score_fixture.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    with io.open(os.path.join(HERE, "_score_expect.json"), "w", encoding="utf-8") as f:
        json.dump({
            "market": {"ind": py["ind"], "score": {
                "total": py["score"]["total"], "state": py["score"]["state"],
                "conf": py["score"]["conf"],
                "dims": [{"k": d["k"], "v": d["v"]} for d in py["score"]["dims"]]}},
            "regime": {"code": pr["code"], "dev": pr["dev"], "vp": pr["vp"],
                       "gmd": pr["gmd"], "r20dv": pr["r20dv"], "dDev": pr["dDev"]},
        }, f, ensure_ascii=False, indent=1)
    print("\n已写出 _score_fixture.json（%.1f KB）与 _score_expect.json"
          % (os.path.getsize(os.path.join(HERE, "_score_fixture.json")) / 1024))


if __name__ == "__main__":
    main()
