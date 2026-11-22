# -*- coding: utf-8 -*-
"""把四条策略统一成「账本（book）」

为什么要有这一层
  原来每条策略的输出格式都不一样：线C 用 positions.json、平台三条用 _platform.json、
  回测净值在 _sim_out.json。想回答「同步模拟谁赚得多」根本没法比。
  借鉴 turtle_project 的 G_SIMULATED_PORTFOLIO：一本 book = 资金 + 持仓 + 交易 + 每日净值。

同时补「龟龟六问」的 ETF 版
  龟龟skill 是给个股做基本面研究的（六个经营问题 → 价格后裁决 → 现金回本），
  和 ETF 轮动不在同一维度，不能直接套。但它的提问顺序可以移植：
  先问「这门生意怎么赚钱、什么时候会坏、坏了能亏多少」，再看价格。
  我们把它翻译成 ETF 语言，答案全部从已有数据自动算，不手填结论。

输出 data/_books.json
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

# 策略的机制事实（设计层面写死，不是从数据推的 —— 数据推不出「对手盘是谁」）
MECHANISM = {
    "lineC": {
        "edge": "均值回归：20 日乖离跌破分档阈值（-16%/-11%/-5%）才买，等反弹到 +3% 或回本走",
        "who_loses": "在恐慌里割肉的人。你买的是他们砸出来的坑 —— 所以必须等「跌透」，"
                     "早一天买就是接下跌中继",
        "why_stop": "市场不跌就没得买（85% 时间空仓），或跌得不深不触发阈值",
    },
    "momo96865": {
        "edge": "动量：加权斜率 V2 排序，只买 20/26 日涨幅都为正的最强标的",
        "who_loses": "在趋势末端追高的人。你在趋势中段进，把最后一棒留给他们 —— "
                     "所以拐点会被反杀（2026-10~11 回撤 22.76%）",
        "why_stop": "动量崩溃：所有标的转负时空仓，但要先被反复止损几次才认出来",
    },
    "band96863": {
        "edge": "动量 + 区间过滤：只买 19 日涨幅在 2%~10% 的「温和上涨」，过热和过冷都不要",
        "who_loses": "追极端热点的人。你放弃最猛的那只，换取不回撤 —— "
                     "代价是牛市里跑不赢纯动量",
        "why_stop": "6 只池里没有一只落在带内时空仓，或带内只剩最弱的那只",
    },
    "bank96864": {
        "edge": "趋势跟踪：10 日加权斜率在 [0.4,2.5] 且价格站上 MA10 才做进攻腿，"
                "否则自动落到银行默认腿吃股息",
        "who_loses": "在震荡里被反复打脸的人。你只在斜率确认后进，代价是错过第一波",
        "why_stop": "斜率掉出区间 → 切银行；银行也跌 → 双 5% 止损",
    },
}

REGIME_CN = {"A": "A 上行·低波", "B": "B 下行·防御有效", "Bp": "B′ 下行·成长占优",
             "C": "C 震荡·中高波", "D": "D 危机·去杠杆"}

# _platform.json 用的是平台数字 ID，book 用的是字符串 key，必须映射
PLAT_ID = {"momo96865": 96865, "band96863": 96863, "bank96864": 96864}

# _sim_out.json 里没有 name 字段（只有 id），中文名在这里补
BOOK_NAME = {
    "lineC": ("线C 乖离抄底", "线C"),
    "momo96865": ("线B · momo 原版（96865）", "线B momo"),
    "band96863": ("消费轮动 96863", "消费轮动"),
    "bank96864": ("等股灾 96864", "等股灾"),
}


def load(fn):
    p = os.path.join(DATA, fn)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def six_q(key, s, robust):
    """龟龟六问的 ETF 版 —— 答案从数据算，不手填"""
    m = s.get("metrics") or {}
    ra = s.get("regime_all") or {}
    mech = MECHANISM.get(key, {})
    tr = [t for t in (s.get("trades") or []) if t.get("ret") is not None]
    worst_trade = min(tr, key=lambda t: t["ret"]) if tr else None

    # Q2：最差的环境。必须区分「真的差」和「样本不够」
    cand = [(k, v) for k, v in ra.items() if v and (v.get("n") or 0) >= 20]
    worst_reg = best_reg = None
    reg_note = ""
    if len(cand) >= 2:
        worst_reg = min(cand, key=lambda kv: kv[1]["mean_bp"])[0]
        best_reg = max(cand, key=lambda kv: kv[1]["mean_bp"])[0]
        w = ra[worst_reg]
        if w["mean_bp"] > 0:
            reg_note = ("各档都赚钱，最弱的一档是 %s（日均 %+.1f bp，%d 天）—— "
                        "说明它不太吃天气；反过来说，真正让它亏钱的坏天气还没在样本里出现过，"
                        "这才是它最大的未知" % (REGIME_CN.get(worst_reg, worst_reg),
                                          w["mean_bp"], w["n"]))
        else:
            reg_note = "最差的一档是 %s，日均 %+.1f bp（%d 天）" % (
                REGIME_CN.get(worst_reg, worst_reg), w["mean_bp"], w["n"])
    elif len(cand) == 1:
        only = cand[0][0]
        best_reg = only
        reg_note = ("样本几乎全在 %s（%d 天，日均 %+.1f bp），"
                    "其他环境样本都不足 20 天 —— 跨环境稳健性还看不清，"
                    "这是它最大的未知" % (REGIME_CN.get(only, only),
                                       ra[only]["n"], ra[only]["mean_bp"]))
    else:
        reg_note = "各环境样本都不足 20 天，暂无法判断它在哪种天气会坏"

    # Q6：稳健性
    rb = (robust or {}).get(key) or {}
    starts = rb.get("starts") or {}
    start_txt = ""
    if starts:
        vals = [v for v in starts.values() if isinstance(v, (int, float))]
        if vals:
            start_txt = "五起点 %+.1f%% ~ %+.1f%%（%s）" % (
                min(vals), max(vals), "全正" if min(vals) > 0 else "有负")

    # Q3：失效能亏多少 —— 只有在真有「最差档」时才拿它当证据
    q3 = "历史最大回撤 %.1f%%" % abs(m.get("mdd") or 0)
    if worst_trade:
        q3 += "；最差单笔 %.2f%%（%s %s）" % (worst_trade["ret"], worst_trade["date"],
                                            worst_trade["code"])
    if worst_reg and ra.get(worst_reg) and ra[worst_reg]["mean_bp"] <= 0:
        q3 += "；最差环境 %s 日均 %+.1f bp（%d 天）" % (
            REGIME_CN.get(worst_reg, worst_reg),
            ra[worst_reg]["mean_bp"], ra[worst_reg]["n"])
    elif worst_reg:
        q3 += "（回撤来自 %s 那一段，但该档日均仍为正 %+.1f bp）" % (
            REGIME_CN.get(worst_reg, worst_reg), ra[worst_reg]["mean_bp"])
    elif len(cand) == 1:
        q3 += "；但只有 %s 一档有足够样本（%d 天），其他天气下的回撤没有实测" % (
            REGIME_CN.get(cand[0][0], cand[0][0]), cand[0][1]["n"])

    cost = rb.get("cost") or {}
    q5 = ("零成本 %.2f%% → 3tick %.2f%%" % (cost.get("zero"), cost.get("t3"))
          if cost.get("zero") is not None and cost.get("t3") is not None
          else "未测成本阶梯")
    n = m.get("n") or 0
    q6 = "样本 %.1f 年 ｜ %d 笔平仓 ｜ 跨 %d 个环境" % (
        (len(s.get("equity") or []) / 244.0), n, len(ra))
    if start_txt:
        q6 += " ｜ " + start_txt

    return [
        {"n": 1, "q": "这门生意赚什么钱？", "a": mech.get("edge", "—")},
        {"n": 2, "q": "什么时候会失效？",
         "a": mech.get("why_stop", "—") + "。" + reg_note},
        {"n": 3, "q": "失效时能亏多少？", "a": q3},
        {"n": 4, "q": "对手盘是谁？为什么他愿意卖给你？", "a": mech.get("who_loses", "—")},
        {"n": 5, "q": "成本和容量吃掉多少？", "a": q5},
        {"n": 6, "q": "凭什么相信历史会重复？", "a": q6},
    ]


def pack_nav(eq, days=60):
    """最近 N 天的净值 + 逐日变化 —— 让「每天在变」看得见"""
    if not eq:
        return None
    tail = eq[-days:] if len(eq) > days else eq
    now = tail[-1][1]
    d1 = tail[-2][1] if len(tail) >= 2 else now
    d7 = tail[-6][1] if len(tail) >= 6 else (tail[0][1] if tail else now)
    d30 = tail[-21][1] if len(tail) >= 21 else (tail[0][1] if tail else now)

    def pct(a, b):
        return round((a / b - 1) * 100, 2) if b else None

    return {
        "series": tail,
        "now": round(now, 0),
        "d1": round(d1, 0), "d7": round(d7, 0), "d30": round(d30, 0),
        "chg_1d": pct(now, d1), "chg_7d": pct(now, d7), "chg_30d": pct(now, d30),
        "hi": round(max(x[1] for x in tail), 0),
        "lo": round(min(x[1] for x in tail), 0),
    }


def norm_pos(p):
    """平台快照与模拟持仓的字段名不同，统一成一套"""
    return {
        "code": p.get("code"),
        "name": p.get("name"),
        "shares": p.get("shares") if p.get("shares") is not None else (p.get("amount") or 0),
        "cost": p.get("cost") if p.get("cost") is not None else p.get("buy_price"),
        "last": p.get("last"),
        "pnl": p.get("pnl"),
        "pnl_amt": p.get("pnl_amt"),
        "mv": p.get("mv"),
        "entry_date": p.get("entry_date") or p.get("buy_date"),
        "held_days": p.get("held_days"),
        "prem": p.get("prem"),
        "fallback": p.get("fallback"),
        "stop": p.get("stop"),
    }


def main():
    sim = load("_sim_out.json")
    plat = load("_platform.json")
    robust = load("_robust.json") or {}
    if not sim:
        print("缺 _sim_out.json，无法建 book")
        return 1

    meta = sim.get("meta") or {}
    books = []
    for s in sim["strategies"]:
        key = s["id"]
        nav = pack_nav(s.get("equity"))
        if not nav:
            continue
        # 真实持仓（平台优先，缺则用模拟持仓）
        pid = PLAT_ID.get(key)
        live = None
        if plat and pid:
            for b in (plat.get("strategies") or []):
                if b.get("id") == pid:
                    live = b
                    break
        raw_holds = (live or {}).get("holding") or s.get("holdings") or []
        holds = [norm_pos(p) for p in raw_holds if p.get("code")]

        books.append({
            "key": key,
            "name": BOOK_NAME.get(key, (s.get("name") or key, key))[0],
            "short": BOOK_NAME.get(key, (key, key))[1],
            "time": ((meta.get("caliber") or {}).get(key) or {}).get("time", ""),
            "capital": 100000,
            "nav": nav,
            "ret": s.get("ret") or {},
            "metrics": {
                "cagr": (s.get("metrics") or {}).get("cagr"),
                "mdd": (s.get("metrics") or {}).get("mdd"),
                "sharpe": (s.get("metrics") or {}).get("sharpe"),
                "win": (s.get("metrics") or {}).get("win"),
                "n": (s.get("metrics") or {}).get("n"),
            },
            "positions": holds,
            "trades": (s.get("trades") or [])[-8:],
            "n_trades": s.get("n_trades"),
            "today": s.get("today"),
            "score": s.get("score"),
            "regime_here": s.get("regime_here"),
            "regime_all": s.get("regime_all"),
            "sim": {k: v for k, v in (s.get("sim") or {}).items() if k != "equity"},
            "sixq": six_q(key, s, robust),
            # 平台官方口径（有则带上，用于对照本地复现）
            "official": (live or {}).get("official"),
            "sim_start": (live or {}).get("sim_start"),
            # 真账 vs 回测：说清楚哪个是哪个
            "acct": "平台API" if live else "回测净值",
            "caliber": ((meta.get("caliber") or {}).get(key) or {}).get("note", ""),
        })

    # 按「近 30 日收益」排序 —— 直接回答「最近谁赚得多」
    books.sort(key=lambda b: -(b["nav"].get("chg_30d") or -999))

    out = {
        "built": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_date": meta.get("data_date"),
        "regime": meta.get("regime"),
        "regime_label": meta.get("regime_label"),
        "n": len(books),
        "books": books,
    }
    p = os.path.join(DATA, "_books.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    print("写出 %s（%.1f KB）｜ %d 本账" % (p, os.path.getsize(p) / 1024, len(books)))
    print("\n%-12s %10s %10s %9s %9s %8s" % ("策略", "净值", "近1日", "近7日", "近30日", "回撤"))
    for b in books:
        nv = b["nav"]
        print("%-12s %10.0f %9s%% %8s%% %8s%% %7s%%"
              % (b["short"][:12], nv["now"],
                 nv["chg_1d"], nv["chg_7d"], nv["chg_30d"], b["metrics"]["mdd"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
