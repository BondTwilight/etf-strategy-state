# -*- coding: utf-8 -*-
"""
data_quality.py —— 行情数据质量守卫（2026-11-22 修订）

背景（真实案例，均为 次方量化 hist_em?adjust=qfq 检出）：
  159928  2021-06-25  close 1.235 → 0.315（-74.5%），次日 1.279（+306%）恢复
  159516  2026-03-30  close 0.415 → 0.213（-48.7%），次日 0.410 恢复
  159516  2026-07-13  close 0.452 → 0.865（+91.4%），**台阶式不回落**
  513100  2022-01-14  close 1.0385 → 0.2030（-80.4%），2022-01-17 → 1.0140（+399%）恢复
  515880  2026-02-03  0.527 → 0.181（-65.6%），02-04 → 0.526（+190%）恢复
  515880  2026-07-06  0.790 → 0.378（-52.2%），07-07 → 0.761（+101%）恢复

★ 2026-11-22 修订：原实现只做「前缀等比缩放」，只能正确处理**台阶式**跳变。
  遇到**尖峰式**（一天暴跌、次日恢复）会连做两次反向缩放，互相抵消，
  最终仍残留一个跳变 —— 实测 513100 修复后最大偏差仍 80.45%、515880 达 65.70%。
  这会让回测在异常日产生假信号与假成交（513100 在 96865 的 12 只池里，
  515880 在线C 的 381 池里且是当前持仓）。

  修订后区分两类：
    尖峰式（spike）：t 日异常，但 t+1 回到 t-1 附近 ⇒ 直接把 t 日价格置为 t-1
    台阶式（step） ：t 日跳变后不再回到原水平 ⇒ 前缀等比缩放（原逻辑）

判定阈值仍是 |r| > 30%（A 股 ETF 有涨跌停，正常不可能）。

局限（必须披露）：无法从价格单独区分「真实份额折算」与「qfq 因子错误」。
修订后的处理对两类都可接受，但价格绝对水平会与交易所行情不同。
"""
import numpy as np

JUMP_TH = 0.30          # 单日涨跌阈值（ETF 有涨跌停，正常不可能超 30%）


def repair_prices(df, jump_th=JUMP_TH):
    """对单只 ETF 日线做跳变修复。返回 (修好的 df, 跳变列表)。

    跳变列表元素：(日期, 修复前价格, 修复后价格, 缩放比例)
      缩放比例 > 0 ：前缀等比缩放（台阶式折算）
      缩放比例 = 0 ：该日被置为前值（尖峰式脏数据）
    """
    d = df.copy().reset_index(drop=True)
    n = len(d)
    if n < 2:
        return d, []
    cols = [c for c in ("open", "high", "low", "close") if c in d.columns]
    px = {c: d[c].to_numpy(dtype=float).copy() for c in cols}
    close = px["close"]
    fixed = []
    t = 1
    guard = 0
    while t < n and guard < n * 4:
        guard += 1
        prev, cur = close[t - 1], close[t]
        if not np.isfinite(prev) or prev <= 0 or not np.isfinite(cur) or cur <= 0:
            t += 1
            continue
        if abs(cur / prev - 1.0) <= jump_th:
            t += 1
            continue

        # ---- 判定尖峰 vs 台阶 ----
        spike = False
        if t + 1 < n:
            nxt = close[t + 1]
            if np.isfinite(nxt) and nxt > 0 and abs(nxt / prev - 1.0) <= jump_th:
                spike = True

        when = d.at[t, "date"] if "date" in d.columns else int(t)
        if spike:
            # 尖峰：t 日置为前值（OHLC 一起置），随后 t+1 与 t-1 自然衔接
            for c in cols:
                px[c][t] = px[c][t - 1]
            fixed.append((when, round(cur, 4), round(prev, 4), 0.0))
            t += 1
        else:
            # 台阶：前缀等比缩放
            R = cur / prev
            for c in cols:
                px[c][:t] *= R
            fixed.append((when, round(prev * R, 4), round(cur, 4), round(R, 4)))
            t += 1

    for c in cols:
        d[c] = px[c]
    return d, fixed


def audit(hist, verbose=True, top=12):
    """全池体检。返回 (修复后 hist, 统计 dict)。"""
    out = {}
    rows = []
    total = 0
    for code, df in hist.items():
        fixed_df, hits = repair_prices(df)
        out[code] = fixed_df
        total += len(hits)
        if hits:
            rows.append((code, len(hits), hits[0][0]))
    info = {"codes_affected": len(rows), "rows_fixed": total,
            "detail": sorted(rows, key=lambda x: -x[1])}
    if verbose:
        print("[数据体检] 检出单日跳变 >%.0f%%：%d 只标的、%d 根 K 线已修复"
              % (JUMP_TH * 100, info["codes_affected"], info["rows_fixed"]))
        if rows:
            print("           修正最多的标的：" + "、".join(
                "%s(%d根)" % (c, n) for c, n, _ in info["detail"][:top]))
    return out, info
