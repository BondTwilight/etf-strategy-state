# -*- coding: utf-8 -*-
"""_industry.py —— 行业内部相对强弱（纯本地数据，不联网）

为什么不是「行业涨幅排名」
--------------------------
涨幅排名只回答「谁涨得多」，回答不了「这块是真扩散还是龙头一个人拉」。
真正的相对强弱要看**内部**：
  · 中位涨幅 —— 不被一两只龙头带偏
  · 广度     —— 行业内多少只站上 MA20（参与度）
  · 广度变化 —— 5 个交易日前相比，参与度在变好还是变差（拐点）
  · 分化度   —— 行业内收益的横截面标准差（分化大 ⇒ 选错就白干）
  · 领先差   —— 第一名与中位数之差（越大越是「独涨」）

综合分 = 四项横截面分位的加权（20日 .45 / 广度 .30 / 广度Δ5 .15 / 5日 .10），
再映射到 0~100。**分位而不是 z 值**：行业只有 20 来个，z 会被极端值带跑。

口径
----
数据：etf_dip_signal/data/all_etf_1120.parquet（前复权日线，与 etf_qfq 逐日对齐）
分组：fixed_pool.json 的 subclass（381 只，2026-10-14 冻结）
基准：510300 沪深300ETF
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PX = os.path.join(ROOT, "etf_dip_signal", "data", "all_etf_1120.parquet")
POOL = os.path.join(ROOT, "etf_dip_signal", "data", "fixed_pool.json")
OUT = os.path.join(HERE, "industry.json")

BENCH = "510300"

# 三类，各自内部排名（跨类相减没有意义：港股 ETF 和 A 股行业不是一个池子）
INDUSTRY = ["电子通信", "半导体", "机械制造", "新能源", "医药", "农业", "有色",
            "能源煤炭", "消费", "化工", "军工", "地产建筑", "食品饮料", "银行",
            "贵金属", "证券保险", "公用环保", "传媒游戏", "钢铁", "能化", "农产品",
            "股息红利"]
REGION = ["港股", "美股", "日本", "欧股", "中概", "新兴市场", "中东", "主题区域"]
WIDE = ["大盘", "中盘", "小盘", "科创板", "创业板", "央企国企", "策略"]

# subclass 是「行业」没错，但 38 只策略类里混着红利低波这类真·防御资产，
# 归到「策略」里读不出信息。用 cmap 的粗分类兜一层：股息红利 单独成组。
WIDE_SUB = {"大盘", "中盘", "小盘", "科创板", "创业板", "央企国企", "策略", "其他"}
# 515020 华夏中证银行ETF 不在 2026-10-14 冻结的 381 池里，但它是 96864 的默认腿 ——
# 看板最重要的持仓必须有行业归属，这里显式补进去。
EXTRA = {"515020": "银行"}


def _load():
    px = pd.read_parquet(PX, columns=["code", "date", "close"])
    px["code"] = px["code"].astype(str)
    px = px.drop_duplicates(["code", "date"]).sort_values(["code", "date"])
    close = px.pivot(index="date", columns="code", values="close").sort_index()
    pool = json.load(open(POOL, encoding="utf-8"))
    names = {str(k): v for k, v in (pool.get("name") or {}).items()}
    sub = {str(k): v for k, v in (pool.get("subclass") or {}).items()}
    cmap = {str(k): v for k, v in (pool.get("cmap") or {}).items()}
    # 归一：红利类从「策略」里提出来，515020 显式补进银行
    for code, c in list(cmap.items()):
        if sub.get(code) in WIDE_SUB and c == "股票-股息红利":
            sub[code] = "股息红利"
    sub.update(EXTRA)
    names.setdefault("515020", "银行ETF华夏")
    return close, names, sub


def _pct(s, n):
    return s / s.shift(n) - 1.0


def compute():
    close, names, sub = _load()
    last = close.index[-1]
    codes = [c for c in close.columns if c in sub]
    c = close[codes]
    ma20 = c.rolling(20, min_periods=20).mean()
    ma60 = c.rolling(60, min_periods=60).mean()
    r5 = _pct(c, 5).iloc[-1]
    r20 = _pct(c, 20).iloc[-1]
    r60 = _pct(c, 60).iloc[-1]
    br20 = (c > ma20)
    br_now = br20.iloc[-1]
    br_prev = br20.iloc[-6] if len(br20) > 6 else br_now
    ok20 = c.notna().iloc[-1] & c.shift(20).notna().iloc[-1]
    ok60 = c.notna().iloc[-1] & c.shift(60).notna().iloc[-1]

    bench20 = float(_pct(close[BENCH], 20).iloc[-1]) if BENCH in close.columns else np.nan

    def pack(group_codes, tag):
        rows = []
        for code in group_codes:
            if not ok20.get(code, False) or pd.isna(r20.get(code)):
                continue
            rows.append({
                "c": code, "n": names.get(code, code),
                "r5": round(float(r5[code]) * 100, 2) if pd.notna(r5.get(code)) else None,
                "r20": round(float(r20[code]) * 100, 2),
                "r60": round(float(r60[code]) * 100, 2) if (ok60.get(code, False) and pd.notna(r60.get(code))) else None,
                "ma20": bool(br_now.get(code, False)),
            })
        if len(rows) < 3:
            return None
        g = pd.DataFrame(rows)
        med20 = float(g.r20.median())
        med5 = float(g.r5.dropna().median()) if g.r5.notna().any() else None
        med60 = float(g.r60.dropna().median()) if g.r60.notna().any() else None
        n_ma = int(g.ma20.sum())
        # 广度 Δ5：只对「当时也有 MA20」的票算，避免新上市票把分母带歪
        codes_g = [x for x in g.c]
        prev_ok = [x for x in codes_g if bool(br_prev.get(x, False))]
        prev_br = (len(prev_ok) / len(codes_g)) if codes_g else None
        d5 = (n_ma / len(codes_g) - prev_br) * 100 if prev_br is not None else None
        return {
            "k": tag, "n": len(g),
            "r5": None if med5 is None else round(med5, 2),
            "r20": round(med20, 2),
            "r60": None if med60 is None else round(med60, 2),
            "ex20": round(med20 - bench20 * 100, 2) if pd.notna(bench20) else None,
            "br20": round(n_ma / len(g) * 100, 0),
            "n_ma": n_ma,
            "d5": None if d5 is None else round(d5, 0),
            "disp": round(float(g.r20.std(ddof=0)), 2),
            "lead": round(float(g.r20.max() - med20), 2),
            "top": g.sort_values("r20", ascending=False).head(3).to_dict("records"),
            "bot": g.sort_values("r20").head(3).to_dict("records"),
            "members": g.sort_values("r20", ascending=False).to_dict("records"),
        }

    def rank(groups):
        """四项横截面分位加权 → 0~100。同分时按 20 日收益排。"""
        if not groups:
            return groups
        def pct(key):
            vals = [x.get(key) for x in groups]
            valid = [v for v in vals if v is not None]
            if len(valid) < 2:
                return {id(x): 50.0 for x in groups}
            s = pd.Series(valid).rank(pct=True)
            mp = {}
            for v in valid:
                mp[v] = float(s[pd.Series(valid) == v].iloc[0]) * 100
            return {id(x): (mp.get(x.get(key), 50.0) if x.get(key) is not None else 50.0)
                    for x in groups}
        p20, pb, pd5, p5 = pct("r20"), pct("br20"), pct("d5"), pct("r5")
        for x in groups:
            # 权重：涨幅 45 / 广度水平 30 / 广度变化 15 / 5 日 10。
            # 广度变化只做「修正项」而不是主项 —— 它回答的是「在变好还是变差」，
            # 不是「现在强不强」；两者混在一起会把深跌板块的反弹算成强势。
            x["score"] = round(0.45 * p20[id(x)] + 0.30 * pb[id(x)]
                               + 0.15 * pd5[id(x)] + 0.10 * p5[id(x)], 1)
            # 状态：涨幅 × 广度 两个维度，避免把「一只龙头拉指数」读成走强
            if x["r20"] > 0 and x["br20"] >= 60:
                x["state"] = "扩散上涨"
            elif x["r20"] > 0 and x["br20"] >= 50:
                x["state"] = "上涨·广度一般"
            elif x["r20"] > 0:
                x["state"] = "龙头独涨"
            elif x["br20"] >= 50:
                x["state"] = "抗跌蓄势"
            else:
                x["state"] = "全面走弱"
            x["mom"] = ("广度改善" if (x.get("d5") or 0) >= 15
                        else ("广度骤降" if (x.get("d5") or 0) <= -15 else "平稳"))
            # 真扩散：涨 + 多数在线上 + 广度没在退
            x["broad"] = bool(x["r20"] > 0 and x["br20"] >= 60 and (x.get("d5") or 0) > -5)
        groups.sort(key=lambda z: (-z["score"], -z["r20"]))
        return groups

    def build(subs, only=None):
        buckets = {}
        for code, s in sub.items():
            if only and s not in only:
                continue
            if code in c.columns:
                buckets.setdefault(s, []).append(code)
        out = [pack(v, k) for k, v in buckets.items()]
        return rank([x for x in out if x])

    inds = build(sub, INDUSTRY)
    regions = build(sub, REGION)
    wide = build(sub, WIDE)

    # ---------- 一句话读懂 ----------
    s = []
    if inds:
        t = inds[0]
        s.append("%s 最强：%d 只里 %d 只站上 20 日线，中位 %+.1f%%%s。"
                 % (t["k"], t["n"], t["n_ma"], t["r20"],
                    ("，广度 5 日 %+.0fpp" % t["d5"]) if t["d5"] is not None else ""))
        w = inds[-1]
        s.append("%s 最弱：中位 %+.1f%%，广度 %.0f%%。" % (w["k"], w["r20"], w["br20"]))
        narrow = [x for x in inds if x["state"] == "龙头独涨"]
        if narrow:
            s.append("另有 %d 个行业是「龙头独涨」（%s）—— 指数在涨，但不到一半的票跟上，"
                     "追进去容易接最后一棒。"
                     % (len(narrow), "、".join(x["k"] for x in narrow[:3])))
    return {
        "date": str(last)[:10],
        "bench": BENCH,
        "bench20": None if pd.isna(bench20) else round(float(bench20) * 100, 2),
        "industries": inds,
        "regions": regions,
        "wide": wide,
        "summary": "".join(s),
        "note": "前复权日线；分组用 fixed_pool 的 subclass（2026-10-14 冻结）。"
                "广度=行业内收盘价站上 MA20 的只数占比；Δ5=与 5 个交易日前相比的百分点变化。",
    }


if __name__ == "__main__":
    d = compute()
    json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("行业 %d 个 · 区域 %d · 宽基 %d · 数据日 %s · 基准 20 日 %s%%"
          % (len(d["industries"]), len(d["regions"]), len(d["wide"]),
             d["date"], d["bench20"]))
    print("  " + d["summary"])
    print("  %-8s %6s %6s %6s %6s %6s %6s %6s" %
          ("行业", "分", "20日", "超额", "广度", "Δ5", "分化", "状态"))
    for x in d["industries"]:
        print("  %-8s %6.1f %+6.2f %+6.2f %5.0f%% %5s %6.2f %s"
              % (x["k"], x["score"], x["r20"], x["ex20"] or 0, x["br20"],
                 ("%+.0f" % x["d5"]) if x["d5"] is not None else "—",
                 x["disp"], x["state"]))
    if "--json" in sys.argv:
        print(json.dumps(d, ensure_ascii=False)[:1200])
