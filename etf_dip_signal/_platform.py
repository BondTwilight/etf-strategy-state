# -*- coding: utf-8 -*-
"""平台真实持仓快照：官方 API 取 my-running + spot + hist，落 data/_platform.json

原则：持仓与绩效以平台/线上为准；本地回测只作曲线与归因，不作为持仓来源。
"""
import datetime
import json
import os

import numpy as np
import pandas as pd

import cf_api
import market_state as ms

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "_platform.json")
END = "2026-11-20"

# 本地名称兜底（API 查不到时用）
NAME_FB = {
    "513290": "纳指生物科技ETF", "515450": "红利低波ETF", "515020": "银行ETF华夏",
    "515880": "通信ETF国泰", "159100": "巴西ETF", "159552": "中证2000增强ETF",
    "159509": "纳指科技ETF", "513100": "纳指ETF", "513310": "中韩半导体ETF",
    "513030": "德国ETF", "518880": "黄金ETF", "588000": "科创50ETF",
    "501225": "全球芯片LOF", "159915": "创业板ETF", "162719": "石油LOF",
    "159985": "豆粕ETF", "513520": "日经ETF", "162411": "油气ETF",
    "161128": "标普信息科技LOF", "162415": "美国消费LOF", "510300": "沪深300ETF",
    "159941": "纳指ETF广发", "512800": "银行ETF", "161226": "国投白银LOF",
}

MOMO_POOL = ["518880", "159509", "588000", "501225", "513100", "513310",
             "159915", "162719", "159985", "513030", "513290", "513520"]
BAND_POOL = ["162411", "513100", "161128", "588000", "162415", "515450"]


# ---------------------------------------------------------------- 指标
def wslope_v2(close, n):
    """加权斜率 V2：w=(1+i/n)^2，年化 exp(slope*250)-1，得分=年化×R²（与 96865/96864 同源）"""
    y = np.asarray(close[-n:], dtype=float)
    if len(y) < n or not np.all(np.isfinite(y)) or y[0] <= 0:
        return None, None
    x = np.arange(n, dtype=float)
    w = (1 + x / n) ** 2
    sw = w.sum()
    mx, my = (w * x).sum() / sw, (w * y).sum() / sw
    sxx = (w * (x - mx) ** 2).sum()
    if sxx <= 0:
        return None, None
    slope = (w * (x - mx) * (y - my)).sum() / sxx
    ann = np.exp(slope * 250) - 1
    yhat = my + slope * (x - mx)
    ss_res = (w * (y - yhat) ** 2).sum()
    ss_tot = (w * (y - my) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return float(ann), float(ann * max(r2, 0))


def ret_n(close, n):
    s = pd.Series(close)
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else None


# ---------------------------------------------------------------- 主流程
def main():
    print("[1] 拉平台策略 …")
    runs = cf_api.my_running()
    print("    %d 条" % len(runs))

    codes = set()
    for s in runs:
        for h in (s.get("holding_etfs") or []):
            codes.add(str(h["code"]))
    codes |= set(MOMO_POOL) | set(BAND_POOL) | {"510300", "159552", "515020", "515880"}
    codes = sorted(codes)

    print("[2] 实时快照 %d 只 …" % len(codes))
    sp = cf_api.spot(codes)

    print("[3] 历史日线 …")
    px = cf_api.hist(codes, "2025-05-01", END, "none")
    print("    %d/%d 只有数据" % (len(px), len(codes)))

    print("[4] 名称 …")
    names = dict(NAME_FB)
    miss = [c for c in codes if c not in names]
    if miss:
        try:
            names.update({k: v for k, v in cf_api.fund_name(miss).items() if v})
        except Exception as e:
            print("    名称查询失败 %r" % (e,))

    def last_of(c):
        if c in sp and sp[c].get("last"):
            return float(sp[c]["last"])
        if c in px:
            return float(px[c]["close"].iloc[-1])
        return None

    def prem_of(c):
        """溢价必须用不复权价 ÷ IOPV；IOPV 为 0/缺失时返回 None（不能算成 inf）"""
        if c in sp and sp[c].get("iopv"):
            v = (float(sp[c]["last"]) / float(sp[c]["iopv"]) - 1) * 100
            return v if np.isfinite(v) else None
        if c in px:
            x = px[c]
            s = (x["close"] / x["iopv"].replace(0, np.nan) - 1).replace(
                [np.inf, -np.inf], np.nan).dropna() * 100
            if len(s):
                return float(s.iloc[-1])
        return None

    def tdays_between(d0, d1=END):
        if "510300" not in px:
            return None
        idx = px["510300"].index
        a = pd.Timestamp(d0)
        return int(((idx > a) & (idx <= pd.Timestamp(d1))).sum())

    # ---------------- 逐策略
    out = []
    for s in runs:
        sid = s["strategy_id"]
        holds = []
        for h in (s.get("holding_etfs") or []):
            c = str(h["code"])
            last = last_of(c)
            bp = float(h.get("buy_price") or 0) or None
            holds.append({
                "code": c, "name": names.get(c, c),
                "amount": int(h.get("amount") or 0),
                "buy_price": round(bp, 4) if bp else None,
                "buy_date": h.get("buy_date"),
                "last": round(last, 4) if last else None,
                "pnl": round((last / bp - 1) * 100, 2) if (last and bp) else None,
                "pnl_amt": round((last - bp) * int(h.get("amount") or 0), 0) if (last and bp) else None,
                "mv": round(last * int(h.get("amount") or 0), 0) if last else None,
                "iopv": round(float(sp[c]["iopv"]), 4) if c in sp and sp[c].get("iopv") else None,
                "prem": round(prem_of(c), 2) if prem_of(c) is not None else None,
                "held_days": tdays_between(h["buy_date"]) if h.get("buy_date") else None,
                "fallback": bool(h.get("fallback")),
            })

        p = s.get("performance") or {}
        blk = {
            "id": sid, "name": s["strategy_name"],
            "desc": s.get("strategy_description"),
            "execute": s.get("execute_time"),
            "capital": float(s.get("initial_capital") or 0),
            "start": s.get("start_date"),
            "sim_start": s.get("simulation_start_date"),
            "official": {
                "total": p.get("total_return"), "cagr": p.get("annualized_return"),
                "sharpe": p.get("sharpe_ratio"), "mdd": p.get("max_drawdown"),
                "win": p.get("win_rate"), "trades": p.get("total_trades"),
            },
            "holding": holds,
            "rules": {},
        }

        # ---- 96865 / 94744：momo 动量排名（收盘价代理 14:30 分时价）
        if sid in (96865, 94744):
            rows = []
            for c in MOMO_POOL:
                if c not in px:
                    continue
                cl = px[c]["close"]
                a20, s20 = wslope_v2(cl.values, 20)
                r20, r26 = ret_n(cl.values, 20), ret_n(cl.values, 26)
                ok = (r20 is not None and r20 * 100 >= 1) and (r26 is not None and r26 * 100 >= 1) \
                    and (s20 is not None and 0.0 <= s20 <= 3.0)
                rows.append({"code": c, "name": names.get(c, c), "score": s20,
                             "r20": r20 * 100 if r20 is not None else None,
                             "r26": r26 * 100 if r26 is not None else None,
                             "prem": round(prem_of(c), 2) if prem_of(c) is not None else None,
                             "pass": bool(ok)})
            rows = [x for x in rows if x["score"] is not None]
            rows.sort(key=lambda x: -x["score"])
            ok_rows = [x for x in rows if x["pass"]]
            blk["rules"] = {
                "type": "momentum_rank",
                "pool_n": len(rows), "pass_n": len(ok_rows),
                "rank": rows[:6],
                "top": ok_rows[0] if ok_rows else None,
                "hold_rank": next((i + 1 for i, x in enumerate(ok_rows)
                                   if holds and x["code"] == holds[0]["code"]), None),
                "note": "以收盘价代理 14:30 分时价复算加权斜率 V2（20日），"
                        "双滤条件 20日涨幅≥1%、26日涨幅≥1%、得分≤3.0",
            }

        # ---- 96863：19 日区间涨幅 ∈[2%,10%] 取最强
        elif sid == 96863:
            rows = []
            for c in BAND_POOL:
                if c not in px:
                    continue
                r19 = ret_n(px[c]["close"].values, 19)
                if r19 is None:
                    continue
                v = r19 * 100
                rows.append({"code": c, "name": names.get(c, c), "r19": round(v, 2),
                             "prem": round(prem_of(c), 2) if prem_of(c) is not None else None,
                             "pass": 2.0 <= v <= 10.0})
            rows.sort(key=lambda x: -x["r19"])
            ok_rows = [x for x in rows if x["pass"]]
            blk["rules"] = {
                "type": "band",
                "pool_n": len(rows), "pass_n": len(ok_rows),
                "rank": rows,
                "top": ok_rows[0] if ok_rows else None,
                "hold_band": next((x for x in rows if holds and x["code"] == holds[0]["code"]), None),
                "note": "19 日区间涨幅需落在 2%~10% 带内，带内取涨幅最高；带外不买",
            }

        # ---- 96864：159552 斜率∈[0.4,2.5] 且 price>MA10，否则持 515020
        elif sid == 96864:
            c = "159552"
            blk["rules"] = {"type": "slope_switch", "note": "10 日加权斜率∈[0.4,2.5] 且收盘>MA10 才持 159552，否则切银行 515020"}
            if c in px:
                cl = px[c]["close"]
                a10, s10 = wslope_v2(cl.values, 10)
                ma10 = cl.rolling(10).mean().iloc[-1]
                blk["rules"].update({
                    "score": round(s10, 3) if s10 is not None else None,
                    "r10": round(ret_n(cl.values, 10) * 100, 2) if ret_n(cl.values, 10) else None,
                    "above_ma10": bool(cl.iloc[-1] > ma10),
                    "in_range": bool(s10 is not None and 0.4 <= s10 <= 2.5),
                    "signal_on": bool(s10 is not None and 0.4 <= s10 <= 2.5 and cl.iloc[-1] > ma10),
                    "ma10": round(float(ma10), 4),
                })
            if holds and holds[0]["buy_price"]:
                bp = holds[0]["buy_price"]
                hi = float(px[holds[0]["code"]]["high"].loc[holds[0]["buy_date"]:].max()) \
                    if holds[0]["code"] in px else None
                blk["rules"]["stop_loss"] = round(bp * 0.95, 4)
                blk["rules"]["dd_stop"] = round(hi * 0.95, 4) if hi else None
                blk["rules"]["to_stop"] = round((holds[0]["last"] / (bp * 0.95) - 1) * 100, 2) \
                    if holds[0]["last"] else None
                # 把**较紧的那个**止损写进持仓行（双 5% 里有两条：跌幅、高点回撤）
                _st = [x for x in (blk["rules"]["stop_loss"], blk["rules"]["dd_stop"]) if x]
                if _st and holds[0]["last"]:
                    tight = max(_st)          # 多头仓位，价格越高越先触发
                    holds[0]["stop"] = tight
                    holds[0]["dist_stop"] = round(
                        (holds[0]["last"] / tight - 1) * 100, 2)
                    holds[0]["stop_note"] = ("双 5%% 止损：跌幅止损 %.4f ｜ 高点回撤止损 %.4f"
                                             "（较紧的是 %.4f）"
                                             % (blk["rules"]["stop_loss"],
                                                blk["rules"]["dd_stop"], tight))

        out.append(blk)

    # ---------------- 市场状态（基准 + 创业板 + 线C 持仓）
    print("[5] 市场状态 …")
    mkt = {}
    for c, lab in (("510300", "沪深300"), ("159915", "创业板"), ("515880", "通信")):
        if c in px and len(px[c]) > 70:
            r = ms.detect(px[c])
            mkt[c] = {"label": lab, "name": names.get(c, c), "ind": r["ind"],
                      "score": r["score"], "chart": ms.chart_series(px[c], 90)}

    doc = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_date": END,
        "source": "次方量化官方 API（/api/strategy/my-running + /api/fund/spot + /api/fund/hist_em）",
        "strategies": out,
        "market": mkt,
        "spot": {c: {k: sp[c].get(k) for k in ("last", "pre_close", "open", "high", "low",
                                               "iopv", "amount", "trade_time",
                                               "bid_price1", "ask_price1",
                                               "bid_volume1", "ask_volume1")}
                 for c in sp},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print("    写出 %s (%.1f KB)" % (OUT, os.path.getsize(OUT) / 1024))

    print("\n=== 真实持仓 ===")
    for b in out:
        h = b["holding"]
        if not h:
            print("  %-6s %-16s 空仓" % (b["id"], b["name"]))
        for x in h:
            print("  %-6s %-16s %s %-16s %9d 份  成本 %.4f → %.4f  %+.2f%%  持 %s 日  溢价 %.2f%%"
                  % (b["id"], b["name"], x["code"], x["name"], x["amount"],
                     x["buy_price"] or 0, x["last"] or 0, x["pnl"] or 0,
                     x["held_days"], x["prem"] or 0))

    print("\n=== 规则状态 ===")
    for b in out:
        r = b["rules"]
        if r.get("type") == "momentum_rank":
            print("  %s 池 %d 只 / 合格 %d 只 / 持仓排名 %s / 第一 %s"
                  % (b["id"], r["pool_n"], r["pass_n"], r["hold_rank"],
                     r["top"]["name"] if r["top"] else "无"))
        elif r.get("type") == "band":
            print("  %s 池 %d / 带内 %d / 第一 %s / 持仓19日 %s%%"
                  % (b["id"], r["pool_n"], r["pass_n"],
                     r["top"]["name"] if r["top"] else "无",
                     r["hold_band"]["r19"] if r["hold_band"] else "?"))
        elif r.get("type") == "slope_switch":
            print("  %s 159552 得分 %s 在区间 %s / 上MA10 %s / 信号 %s"
                  % (b["id"], r.get("score"), r.get("in_range"),
                     r.get("above_ma10"), r.get("signal_on")))

    print("\n=== 市场状态 ===")
    for c, m in mkt.items():
        print("  %s %-6s %s  %6.1f 分  置信 %s%%"
              % (c, m["label"], m["score"]["state"], m["score"]["total"], m["score"]["conf"]))


if __name__ == "__main__":
    main()
