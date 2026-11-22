# -*- coding: utf-8 -*-
"""_patch_hub.py —— 把 hub_build.py 的「策略台账」块替换为 _sim 驱动版"""
import io
import os

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hub_build.py")
src = open(P, encoding="utf-8").read().split("\n")

START = next(i for i, l in enumerate(src) if l.strip() == "# ---------------- 策略台账 ----------------")
END = next(i for i, l in enumerate(src) if l.strip() == "# ---------------- 归档 ----------------")

NEW = '''    # ---------------- 策略台账（统一模拟引擎 _sim）----------------
    say("\\n[7/7] 策略台账（_sim 统一模拟引擎）")
    SIMP = os.path.join(DIP, "data", "_sim_out.json")
    if not os.path.exists(SIMP):
        say("      ⚠️ 缺少 data/_sim_out.json —— 先跑 etf_dip_signal/_sim.py")
        raise SystemExit(1)
    sim = json.load(open(SIMP, encoding="utf-8"))
    S = {x["id"]: x for x in sim["strategies"]}
    say("      regime = %s %s ｜ 已模拟 %d 条"
        % (sim["meta"]["regime"], sim["meta"]["regime_label"], len(S)))

    # ---- 净值序列（统一归一化到 100）----
    def to100(arr):
        if not arr:
            return []
        b = arr[0][1] or 1
        return [[d, round(v / b * 100, 3)] for d, v in arr]

    for sid in S:
        series[sid] = to100(S[sid]["equity"])
    series["bench300"] = norm(eq300)

    # ---- 线C 线上 vs 模拟 分叉 ----
    sim_hold = S["lineC"]["holdings"][0] if S["lineC"]["holdings"] else None
    live_hold = pos[0] if pos else None
    live_diff = None
    if sim_hold and live_hold:
        live_diff = {
            "sim": sim_hold, "live": live_hold,
            "gap": round((live_hold["pnl"] or 0) - (sim_hold["pnl"] or 0), 2),
            "why": ("11-13 线上未运行（11-16 才补跑，且补跑时已过下单时点）⇒ 错过一次换仓；"
                    "叠加 14:49 实时价与收盘价的排名差异"),
        }

    # ---- 五条策略 ----
    import _strategies as TX
    tctx = {"prem": {k: {"prem": v} for k, v in
                     {c: (prem[c].get("prem") if hasattr(prem.get(c), "get") else None)
                      for c in ["159100", "515880", "159509", "513100", "513310",
                                "159552", "515020"]}.items() if v is not None}}

    def mk(sid, text):
        d = S[sid]
        o = {
            "id": sid,
            "score": d["score"],
            "today": d["today"],
            "holdings": d["holdings"],
            "ret": d["ret"],
            "metrics": d["metrics"],
            "regime_here": d["regime_here"],
            "regime_all": d["regime_all"],
            "by_year": d["by_year"],
            "equity": series[sid],
            "trades": d["trades"],
            "n_trades": d["n_trades"],
            "sim": d["sim"],
            "calendar": d["calendar"],
            "series_id": sid,
            "live_diff": live_diff if sid == "lineC" else None,
        }
        o.update(text)
        return o

    strategies = [
        mk("lineC", TX.lineC(tctx, S["lineC"]["metrics"])),
        mk("momo96865", TX.momo(tctx, S["momo96865"]["metrics"])),
        mk("band96863", TX.band(tctx, S["band96863"]["metrics"])),
        mk("bank96864", TX.bank(tctx, S["bank96864"]["metrics"], s56b["cagr"])),
    ]

    # ---- 恒方：无历史序列，不给评分 ----
    if intel:
        hf = TX.hengfang(tctx, intel)
        hf.update({
            "id": "hengfang", "score": None, "today": None, "holdings": [],
            "ret": None,
            "metrics": {"cagr": None, "mdd": None, "sharpe": None, "sortino": None,
                        "calmar": None, "vol": None, "n": None, "win": None, "pl": None,
                        "final": None, "dd_days": None, "recover_days": None,
                        "cur_dd_days": None},
            "regime_here": None, "regime_all": {}, "by_year": {},
            "series_id": None, "trades": [], "n_trades": None, "sim": None,
            "calendar": None, "live_diff": None,
        })
        strategies.append(hf)

    strategies.sort(key=lambda x: -(x["score"]["total"] if x["score"] else -1))
    for i, s in enumerate(strategies, 1):
        s["rank"] = i

    # 环境适配矩阵（四条可模拟策略 × 5 个 regime）
    REG_ORDER = ["A", "C", "Bp", "B", "D"]
    matrix = {
        "regimes": [{"k": k, "n": sim["meta"]["regime_days"].get(k, 0),
                     "label": {"A": "趋势上行·低波", "C": "震荡·中高波",
                               "Bp": "趋势下行·成长占优", "B": "趋势下行·防御有效",
                               "D": "危机·去杠杆"}[k]} for k in REG_ORDER],
        "rows": [{"id": s["id"], "name": s["name"].split(" ·")[0],
                  "cells": [s["regime_all"].get(k) for k in REG_ORDER]}
                 for s in strategies if s["regime_all"]],
        "cur": sim["meta"]["regime"],
    }

'''
out = src[:START] + NEW.split("\n") + src[END:]
open(P, "w", encoding="utf-8").write("\n".join(out))
print("替换 %d-%d 行 → 新块 %d 行" % (START + 1, END, len(NEW.split("\n"))))
