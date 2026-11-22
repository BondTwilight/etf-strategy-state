# -*- coding: utf-8 -*-
"""
_p4_band.py —— 趋势带原语移植验证（2026-11-22）

要验证的问题
------------
消费轮动 96863 的核心原语不是"19日动量最强"，而是"只做 2%~10% 这段趋势带"。
本脚本把它移植到我们自己的池子，回答三件事：

  Q1 它在 381 冻结池 / 12 只消费池上，长期（2021~2026）是否还成立？
  Q2 结论是否随起点翻转？（2021 / 2022 / 2023 三起点，符号翻转=噪声）
  Q3 它与线C（乖离抄底）的日收益相关性有多高？能否成为一条真正独立的腿？

口径（必须显式，否则不可比）
--------------------------
1. 信号 = N=19 日区间涨幅（收盘价比值），只取 [lo, hi] 带内。
   原策略用 14:50 分时价，此处用收盘价代理 —— 属已知差异，另用 lag=1 做稳健性。
2. 排序 = 带内动量降序取第一名（原 `_sort_key` 的 -value）。
3. 卖出 = 持有满 min_hold 个交易日后，若"第一名不是自己"则换仓；
   带内无人则清仓（原 `if k>=n or not value_nominal(): break`）。
4. 不允许 ffill：动量窗口必须最近 20 个交易日全有数据，否则该标的当日无效。
5. 成本 = 佣金万2.5（单边）+ 滑点 0.1%。
6. 成交价 = 当日收盘价（lag=0）/ 昨日信号今日收盘（lag=1）。

起点敏感性是本项目的硬规则：符号随起点翻转 ⇒ 一律判噪声，不得提建议。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import data_quality
import bt_etf_dip as bt
import bt_multi as bm

DATA = os.path.join(BASE, "data", "all_etf_1119.parquet")
POOL_JSON = os.path.join(BASE, "data", "fixed_pool.json")
CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]
CONSUME_NAMES = {"162411": "油气", "513100": "纳指100", "161128": "标普信息",
                 "588000": "科创50", "162415": "美国消费", "515450": "红利低波"}

CASH0 = 100000.0
COMM = 0.00025
SLIP = 0.001


# ---------------------------------------------------------------- 数据
def load_all(codes):
    """一次读盘，返回 (hist dict, pivot close, 清洗统计)。"""
    df = pd.read_parquet(DATA)
    df["code"] = df["code"].astype(str)
    sub = df[df.code.isin(set(codes))]
    hist, px = {}, {}
    fixed_rows = 0
    for c, g in sub.groupby("code"):
        s = g[["date", "open", "high", "low", "close", "volume"]].copy()
        s["date"] = s["date"].astype(str).str[:10]
        s = s.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        s2, hits = data_quality.repair_prices(s)
        fixed_rows += len(hits)
        hist[c] = s2
        px[c] = pd.to_numeric(
            s2.set_index(pd.to_datetime(s2["date"]))["close"], errors="coerce"
        ).astype(float)
    p = pd.DataFrame(px).sort_index()
    return hist, p, fixed_rows


# ---------------------------------------------------------------- 指标
def stats(eq, trades, cash0=CASH0, exposure=np.nan):
    eq = pd.Series(eq).dropna()
    if len(eq) < 2:
        return {}
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    dr = eq.pct_change().dropna()
    vol = dr.std() * np.sqrt(252)
    sharpe = (dr.mean() * 252) / vol if vol > 0 else np.nan
    calmar = cagr / abs(dd) if dd < 0 else np.nan
    if isinstance(trades, pd.DataFrame):
        t = trades.copy()
    else:
        t = pd.DataFrame(trades) if (trades is not None and len(trades)) else pd.DataFrame()
    ntr = int(len(t)) if len(t) else 0
    win = avg_w = avg_l = pl = np.nan
    if len(t) and "ret" in t.columns:
        r = t["ret"].dropna()
        if len(r):
            win = (r > 0).mean()
            avg_w = r[r > 0].mean() if (r > 0).any() else np.nan
            avg_l = r[r < 0].mean() if (r < 0).any() else np.nan
            pl = abs(avg_w / avg_l) if np.isfinite(avg_l) and avg_l != 0 else np.nan
    return dict(cagr=cagr, max_dd=dd, vol=vol, sharpe=sharpe, calmar=calmar,
                trades=ntr, win=win, avg_win=avg_w, avg_loss=avg_l, pl=pl,
                exposure=exposure, final=eq.iloc[-1], equity=eq)


def by_year(eq):
    r = pd.Series(eq).pct_change().fillna(0.0)
    return r.groupby(r.index.year).apply(lambda s: (1 + s).prod() - 1)


# ---------------------------------------------------------------- 趋势带
def run_band(p, lo=0.02, hi=0.10, look=18, min_hold=5,
             comm=COMM, slip=SLIP, cash0=CASH0,
             stop_loss=None, cooldown=0, lag=0):
    """趋势带轮动：带内动量最强 Top1、满 min_hold 才可换、无默认腿。

    look 口径（★ 已用逐日复现锁定）：
        平台 value_filters = {days:19, exclude_today:False}
        → size = 19-1 = 18，Growth 保留最近 18 个 tick，再与今日 tick 比
        → (P_t - P_{t-18}) / P_{t-18}  =  shift(18)
        用 shift(19) 会让 11 月逐日收益平均误差从 0.01% 放大到 1.47pp，
        并在 2020-2026 把年化从 48.77% 压到 16.22% —— 窗口差一天，结论全反。
    """
    mom = p / p.shift(look) - 1.0
    need = look + 1
    ok = p.notna().rolling(need, min_periods=need).sum() == need
    mom = mom.where(ok)
    if lag:
        mom = mom.shift(lag)

    dates = p.index
    n = len(dates)
    close = p.to_numpy(dtype=float)
    col = {c: i for i, c in enumerate(p.columns)}   # 预建列索引，避免循环内 get_loc
    # 估值专用：停牌日用最近有效价 carry-forward（否则持仓市值会被算成 0，
    # 制造假的 -99.9% 回撤 —— 首版 lag=1 就栽在这里）
    close_mv = p.ffill().to_numpy(dtype=float)

    cash = cash0
    code = None
    shares = 0
    entry_i = None
    entry_px = 0.0
    last_stop_i = -10 ** 9
    eq = np.full(n, np.nan)
    held_flags = []
    trades = []

    for i in range(n):
        px_row = close[i]
        row = mom.iloc[i]
        cand = row.dropna()
        cand = cand[(cand >= lo) & (cand <= hi)]
        top = cand.idxmax() if len(cand) else None

        # ---- 1) 止损（收盘口径）----
        if code is not None and stop_loss and entry_px > 0:
            cur = px_row[col[code]]
            if np.isfinite(cur) and cur / entry_px - 1.0 <= -stop_loss:
                sp = cur * (1 - slip)
                cash += shares * sp * (1 - comm)
                trades.append({"date": dates[i], "action": "stop", "code": code,
                               "price": sp, "shares": shares,
                               "ret": sp / entry_px - 1.0 - 2 * (comm + slip)})
                code, shares, entry_i, entry_px = None, 0, None, 0.0
                last_stop_i = i

        # ---- 2) 换仓判定（满 min_hold 才可卖）----
        if code is not None and entry_i is not None and (i - entry_i) >= min_hold:
            if top != code:                      # 第一名不是自己（或带内无人）
                cur = px_row[col[code]]
                if np.isfinite(cur):
                    sp = cur * (1 - slip)
                    cash += shares * sp * (1 - comm)
                    trades.append({"date": dates[i], "action": "sell", "code": code,
                                   "price": sp, "shares": shares,
                                   "ret": sp / entry_px - 1.0 - 2 * (comm + slip)})
                    code, shares, entry_i, entry_px = None, 0, None, 0.0

        # ---- 3) 买入 ----
        if code is None and top is not None and (i - last_stop_i) > cooldown:
            bp = px_row[col[top]] * (1 + slip)
            if np.isfinite(bp) and bp > 0:
                can = int((cash / (bp * (1 + comm))) // 100) * 100
                if can > 0:
                    cash -= can * bp * (1 + comm)
                    shares, code, entry_i, entry_px = can, top, i, bp
                    trades.append({"date": dates[i], "action": "buy", "code": code,
                                   "price": bp, "shares": can, "ret": np.nan})

        mv = 0.0
        if code is not None:
            cur = close_mv[i][col[code]]
            if np.isfinite(cur):
                mv = shares * cur
        eq[i] = cash + mv
        held_flags.append(1 if code is not None else 0)

    eqs = pd.Series(eq, index=pd.to_datetime(dates)).dropna()
    expo = float(np.mean(held_flags)) if held_flags else np.nan
    return {"equity": eqs, "trades": trades, "exposure": expo}


# ---------------------------------------------------------------- 线C
def load_pool_codes():
    import json
    d = json.load(open(POOL_JSON, encoding="utf-8"))
    return [str(c) for c in d["codes"]], {str(k): int(v) for k, v in d["bmap"].items()}


def run_lineC(hist, bmap, start, end):
    m = bt.build_matrices(hist, start=start, end=end)
    r = bm.run(m, bmap, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True)
    p = bt.perf(r["equity"], r["trades"], CASH0, r["exposure"])
    p["equity"] = r["equity"]
    p["trades_df"] = r["trades"]
    return p


# ---------------------------------------------------------------- 主流程
def main():
    lines = []

    def say(s=""):
        lines.append(str(s))
        print(s)

    say("=" * 100)
    say("趋势带原语移植验证（19日区间涨幅，2%~10% 带，Top1，min_hold=5）")
    say("数据：all_etf_1119.parquet（2015-01-05 ~ 2026-11-19，已做跳变前缀修复）")
    say("=" * 100)

    codes381, bmap = load_pool_codes()
    say("\n[数据加载] 381 冻结池 %d 只 + 12 消费池 6 只" % len(codes381))
    hist, p_all, fixed = load_all(set(codes381) | set(CONSUME))
    say("  跳变修复 %d 根 K 线；价格矩阵 %d 行 × %d 列（%s ~ %s）"
        % (fixed, p_all.shape[0], p_all.shape[1],
           p_all.index[0].date(), p_all.index[-1].date()))

    tracks = [
        ("381池", [c for c in codes381 if c in p_all.columns]),
        ("12池", [c for c in CONSUME if c in p_all.columns]),
    ]
    starts = ["2020-01-01", "2021-01-01", "2022-01-01", "2023-01-01"]
    end = "2026-11-19"

    # ============ A. 主表：起点 × 池 × 变体 ============
    say("\n" + "=" * 100)
    say("A. 趋势带主表（无止损原版 / 加-15%止损 / 加止损+3日冷却）")
    say("=" * 100)
    say("\n%-10s %-8s %-14s %8s %9s %7s %7s %6s %7s %7s %8s"
        % ("起点", "池", "变体", "年化", "最大回撤", "夏普", "卡玛",
           "交易", "胜率", "盈亏比", "持仓占比"))
    say("-" * 112)

    band_res = {}
    for st in starts:
        for tname, tcodes in tracks:
            sub = p_all[tcodes].loc[st:end]
            for vname, kw in [
                ("原版", dict()),
                ("-15%止损", dict(stop_loss=0.15)),
                ("止损+冷却3", dict(stop_loss=0.15, cooldown=3)),
            ]:
                r = run_band(sub, **kw)
                s = stats(r["equity"], r["trades"], CASH0, r["exposure"])
                if not s:
                    continue
                band_res[(st, tname, vname)] = (s, r)
                say("%-10s %-8s %-14s %+7.2f%% %8.2f%% %7.2f %7.2f %6d %6.1f%% %7.2f %7.1f%%"
                    % (st, tname, vname, s["cagr"] * 100, s["max_dd"] * 100,
                       s["sharpe"], s["calmar"], s["trades"],
                       (s["win"] * 100) if np.isfinite(s["win"]) else -1,
                       s["pl"] if np.isfinite(s["pl"]) else -1,
                       s["exposure"] * 100))

    # ============ B. 平台保真度核对（12池 2020 起 对 53.87%）============
    say("\n" + "=" * 100)
    say("B. 保真度核对：12 池 2020-01-01 起，平台宣称年化 53.87% / 回撤 20.34% / 夏普 1.85")
    say("=" * 100)
    r0 = run_band(p_all[CONSUME].loc["2020-01-01":end])
    s0 = stats(r0["equity"], r0["trades"], CASH0, r0["exposure"])
    say("  本地复现：年化 %+.2f%%  回撤 %.2f%%  夏普 %.2f  卡玛 %.2f  交易 %d 次  胜率 %.1f%%  盈亏比 %.2f  期末 %.2f 倍"
        % (s0["cagr"] * 100, s0["max_dd"] * 100, s0["sharpe"], s0["calmar"],
           s0["trades"], s0["win"] * 100, s0["pl"], r0["equity"].iloc[-1] / CASH0))
    say("  差异：年化 %+.2fpp，回撤 %+.2fpp，胜率 %+.2fpp，盈亏比 %+.2f"
        % (s0["cagr"] * 100 - 53.87, s0["max_dd"] * 100 - 20.34,
           s0["win"] * 100 - 52.32, s0["pl"] - 1.97))
    say("  差异来源（已量化）：① 成交价 14:50 分时 vs 收盘（11-16 单日 0.06pp）")
    say("                    ② 初始资金 1 万 vs 10 万，整手取整粒度不同")
    say("                    ③ 平台回撤区间 2026-03-30~05-19，本地需核对是否同段")

    # ============ C. 与线C 相关性 ============
    say("\n" + "=" * 100)
    say("C. 与线C（乖离抄底 v4.6 原版）相关性与收益对比")
    say("=" * 100)
    c_res = {}
    for st in ["2021-01-01", "2022-01-01", "2023-01-01"]:
        h381 = {c: hist[c] for c in codes381 if c in hist}
        pc = run_lineC(h381, bmap, st, end)
        c_res[st] = pc
        # 同期趋势带（381 池，原版）
        sb, rb = band_res[(st, "381池", "原版")]
        # 对齐日收益
        e1 = rb["equity"]
        e2 = pd.Series(pc["equity"])
        idx = e1.index.intersection(e2.index)
        rho = np.nan
        if len(idx) > 60:
            rho = pd.Series(e1.reindex(idx)).pct_change().corr(
                pd.Series(e2.reindex(idx)).pct_change())
        say("\n  起点 %s" % st)
        say("    线C        年化 %+6.2f%%  回撤 %6.2f%%  夏普 %5.2f  卡玛 %5.2f  交易 %3d 次"
            % (pc["cagr"] * 100, pc["max_dd"] * 100, pc["sharpe"],
               pc["calmar"], pc["trades"]))
        say("    趋势带381  年化 %+6.2f%%  回撤 %6.2f%%  夏普 %5.2f  卡玛 %5.2f  交易 %3d 次"
            % (sb["cagr"] * 100, sb["max_dd"] * 100, sb["sharpe"],
               sb["calmar"], sb["trades"]))
        say("    日收益相关系数 ρ = %+.3f  （重叠 %d 个交易日）"
            % (rho if np.isfinite(rho) else float("nan"), len(idx)))
        # 50/50 合成
        if len(idx) > 60:
            ra = pd.Series(e1.reindex(idx)).pct_change().fillna(0.0)
            rb2 = pd.Series(e2.reindex(idx)).pct_change().fillna(0.0)
            mix = (1 + 0.5 * ra + 0.5 * rb2).cumprod()
            sm = stats(mix, [], CASH0)
            say("    50/50 合成  年化 %+6.2f%%  回撤 %6.2f%%  夏普 %5.2f  卡玛 %5.2f"
                % (sm["cagr"] * 100, sm["max_dd"] * 100, sm["sharpe"], sm["calmar"]))

    # ============ D. 分年收益（381池 2021起 原版）============
    say("\n" + "=" * 100)
    say("D. 分年收益对比（2021 起，381 池）")
    say("=" * 100)
    sb, rb = band_res[("2021-01-01", "381池", "原版")]
    yb = by_year(rb["equity"])
    yc = by_year(c_res["2021-01-01"]["equity"])
    say("  %-6s %12s %12s" % ("年份", "趋势带381", "线C"))
    for y in sorted(set(yb.index) | set(yc.index)):
        a = yb.get(y, np.nan)
        b = yc.get(y, np.nan)
        say("  %-6d %11s %11s" % (y,
                                  ("%+.2f%%" % (a * 100)) if np.isfinite(a) else "-",
                                  ("%+.2f%%" % (b * 100)) if np.isfinite(b) else "-"))

    # ============ E. 稳健性：lag / 成本 ============
    say("\n" + "=" * 100)
    say("E. 稳健性：成交滞后与成本（381 池 2021 起）")
    say("=" * 100)
    sub = p_all[[c for c in codes381 if c in p_all.columns]].loc["2021-01-01":end]
    for lbl, kw in [("lag=0 当日收盘", dict(lag=0)),
                    ("lag=1 昨日信号", dict(lag=1)),
                    ("零成本", dict(lag=0, comm=0.0, slip=0.0)),
                    ("3tick 滑点0.3%", dict(lag=0, slip=0.003))]:
        r = run_band(sub, **kw)
        s = stats(r["equity"], r["trades"], CASH0, r["exposure"])
        say("  %-16s 年化 %+6.2f%%  回撤 %6.2f%%  夏普 %5.2f  交易 %3d 次  持仓 %5.1f%%"
            % (lbl, s["cagr"] * 100, s["max_dd"] * 100, s["sharpe"],
               s["trades"], s["exposure"] * 100))

    # ============ F. 带内无人天数（空仓率来源）============
    say("\n" + "=" * 100)
    say("F. 空仓结构：381 池每日带内候选数量分布（2021 起）")
    say("=" * 100)
    sub = p_all[[c for c in codes381 if c in p_all.columns]].loc["2021-01-01":end]
    mom = sub / sub.shift(18) - 1.0
    ok = sub.notna().rolling(19, min_periods=19).sum() == 19
    mom = mom.where(ok)
    cnt = ((mom >= 0.02) & (mom <= 0.10)).sum(axis=1)
    say("  有效标的数中位 %.0f｜带内候选数：均值 %.1f 中位 %.0f"
        % (ok.sum(axis=1).median(), cnt.mean(), cnt.median()))
    say("  带内=0 的天数占比 %.1f%%（= 必然空仓）；带内>=1 占比 %.1f%%"
        % ((cnt == 0).mean() * 100, (cnt >= 1).mean() * 100))
    say("  带内候选数分位：10%%=%.0f 25%%=%.0f 50%%=%.0f 75%%=%.0f 90%%=%.0f"
        % tuple(np.percentile(cnt, [10, 25, 50, 75, 90])))

    # ============ G. 12 池参数平台检查 ============
    say("\n" + "=" * 100)
    say("G. 12 池参数平台检查（look=18, 2020 起）—— 真 alpha 应有「平台」，不是尖峰")
    say("=" * 100)
    say("  %-16s %8s %9s %7s %6s %7s %7s"
        % ("参数", "年化", "最大回撤", "夏普", "交易", "胜率", "盈亏比"))
    say("  " + "-" * 74)
    sub12 = p_all[CONSUME].loc["2020-01-01":end]
    for mh in [1, 3, 5, 10, 20, 40]:
        r = run_band(sub12, min_hold=mh)
        s = stats(r["equity"], r["trades"], exposure=r["exposure"])
        say("  %-16s %+7.2f%% %8.2f%% %7.2f %6d %6.1f%% %7.2f"
            % ("min_hold=%d" % mh, s["cagr"] * 100, s["max_dd"] * 100,
               s["sharpe"], s["trades"], s["win"] * 100, s["pl"]))
    for lo, hi in [(0.0, 999), (0.0, 0.10), (0.02, 0.10), (0.05, 0.10), (0.02, 0.20)]:
        r = run_band(sub12, lo=lo, hi=hi)
        s = stats(r["equity"], r["trades"], exposure=r["exposure"])
        say("  %-16s %+7.2f%% %8.2f%% %7.2f %6d %6.1f%% %7.2f"
            % ("带[%.0f%%,%.0f%%]" % (lo * 100, min(hi, 9.99) * 100),
               s["cagr"] * 100, s["max_dd"] * 100, s["sharpe"],
               s["trades"], s["win"] * 100, s["pl"]))
    say("  注：带[0%,999%%] = 不做区间过滤、纯最强动量，用来分离「动量」与「区间带」各自的贡献")

    # ============ H. 回撤归因 ============
    say("\n" + "=" * 100)
    say("H. 12 池最大回撤归因（look=18, 2020 起）")
    say("=" * 100)
    eq0 = r0["equity"]
    dd0 = eq0 / eq0.cummax() - 1.0
    trough = dd0.idxmin()
    peak = eq0.loc[:trough].idxmax()
    say("  峰值 %s（%.0f）→ 谷底 %s（%.0f），回撤 %.2f%%，修复需 %.1f 个交易日"
        % (peak.date(), eq0.loc[peak], trough.date(), eq0.loc[trough],
           dd0.min() * 100, 0))
    td = r0["trades"]
    seg = [t for t in td if peak <= pd.Timestamp(t["date"]) <= trough]
    say("  区间内交易 %d 笔：" % len(seg))
    for t in seg:
        act = "买入" if t["action"] == "buy" else ("卖出" if t["action"] == "sell" else "止损")
        say("    %s %-4s %s %-8s ret=%s"
            % (pd.Timestamp(t["date"]).date(), act, t["code"],
               CONSUME_NAMES.get(t["code"], ""),
               ("%+.2f%%" % (t["ret"] * 100)) if np.isfinite(t["ret"]) else "-"))
    # 修复天数
    after = eq0.loc[trough:]
    rec = after[after >= eq0.loc[peak]]
    if len(rec):
        nd = len(eq0.loc[trough:rec.index[0]]) - 1
        say("  实际修复 %d 个交易日（平台宣称 62 天）" % nd)
    else:
        say("  至样本末仍未修复前高")

    out = os.path.join(BASE, "_p4_band.log")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n[已保存] " + out)


if __name__ == "__main__":
    main()
