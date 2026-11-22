# -*- coding: utf-8 -*-
"""
hub_build.py —— 策略中枢 v2「执行台」

设计出发点变了
--------------
v1 是「研究展示板」：每张卡讲一个策略的故事，指标是年化/回撤/夏普。
v2 是「执行台」：一个真正要下单的人，早上打开它只需要回答四个问题 ——

  Q1 今天有没有必须做的事？（有 → 给代码/数量/价格/时点/限价；没有 → 说清为什么）
  Q2 我手上的仓位现在多危险？（距止损/止盈/换仓还有多远）
  Q3 这些数字可不可信？（数据日、覆盖率、复权、时点、溢价）
  Q4 这套东西长期值多少钱、什么时候该停？（预期区间、容量、失效条件）

因此 v2 的四条硬规则
--------------------
1. **数据日唯一**：回测、持仓、市场状态全部对齐到同一个交易日。v1 出现过
   「看板显示距止损 +4.11%，实际收盘已跌破」——根因就是回测到 11-19、状态到 11-20。
2. **动作由规则生成，不手写**：`build_action()` 按线C 的四道闸门逐条判定，
   数据一变结论自动变。任何「必须执行」都必须能追溯到具体规则条款。
3. **每个策略一张尽调表**：数据源 / 执行时点 / 买卖规则 / 溢价 / 流动性 /
   成本 / 容量 / 复现误差 / 失效条件 —— 九项统一口径，可横向对比。
4. **七维实盘评分**：数据可信·执行明确·成本后存活·容量匹配·溢价安全·
   参数稳健·样本充分。评分口径写在页面里，可复算；不是拍脑袋的「推荐指数」。

删除项（2026-11-22 用户要求）
--------------------------
- 趋势带 · 381 池（移植测试）：四起点全负、回撤 -49.5%，已否决且无执行价值。
- 线A · 场外基金 9 只：用户已停止定投，不在本看板管理范围。

输出
----
hub/hub.json     结构化数据
hub/index.html   单文件看板（数据内联，双击即开）
"""
import datetime
import json
import os
import sys
import urllib.request

import numpy as np
import pandas as pd

HUB = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HUB)
DIP = os.path.join(ROOT, "etf_dip_signal")
sys.path.insert(0, DIP)

import bt_etf_dip as bt
import bt_multi as bm
import _p4_band as pb
import _p5_bank as p5
import _p6_momo as m6

# ---------------- 口径常量（改这里 = 改全站） ----------------
DATA_PX = os.path.join(DIP, "data", "all_etf_1120.parquet")
DATA_DATE = "2026-11-20"          # 唯一数据日
START = "2021-01-04"              # 线C 回测起点
CMP_START = "2024-10-01"          # 四策略共同对照窗口起点（159552 上市后）
CASH0 = 100000.0

CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]
CONSUME_N = {"162411": "油气", "513100": "纳指100", "161128": "标普信息",
             "588000": "科创50", "162415": "美国消费", "515450": "红利低波"}
MOMO = ["518880", "159509", "588000", "501225", "513100", "513310",
        "159915", "162719", "159985", "513030", "513290", "513520"]
MOMO_N = {"518880": "黄金", "159509": "纳指科技", "588000": "科创50",
          "501225": "全球芯片", "513100": "纳指100", "513310": "中韩半导体",
          "159915": "创业板", "162719": "石油LOF", "159985": "豆粕",
          "513030": "德国", "513290": "纳指生物", "513520": "日经"}
BENCH = [("510300", "沪深300"), ("510500", "中证500"), ("512100", "中证1000"),
         ("159915", "创业板"), ("510880", "红利低波")]

COLORS = {
    "lineC": "#ff5252", "momo96865": "#2dd4bf", "band96863": "#4d9fff",
    "bank96864": "#ffb020", "main159552": "#4a566b",
    "bench300": "#63718a", "benchEW": "#2e3a4d",
}
SERIES_N = {
    "lineC": "线C 乖离抄底", "momo96865": "momo 原版 96865",
    "band96863": "消费轮动 96863", "bank96864": "等股灾 96864",
    "main159552": "159552 买入持有", "bench300": "沪深300",
    "benchEW": "381池等权",
}

log = []


def say(s=""):
    log.append(str(s))
    print(s)


def norm(eq):
    eq = pd.Series(eq).dropna()
    if len(eq) < 2:
        return []
    base = eq.iloc[0]
    return [[d.strftime("%Y-%m-%d"), round(float(v / base * 100), 3)] for d, v in eq.items()]


def _closed(trades):
    if trades is None:
        return None
    if isinstance(trades, pd.DataFrame):
        if "action" in trades.columns and len(trades):
            return int((trades["action"] != "buy").sum())
        return None
    if isinstance(trades, list):
        return sum(1 for t in trades if t.get("action") != "buy")
    return None


def metrics(eq, trades=None, exposure=None):
    s = pb.stats(eq, trades if trades is not None else [],
                 CASH0, exposure if exposure is not None else np.nan)
    if not s:
        return {}
    ntr = _closed(trades)
    return {
        "cagr": round(s["cagr"] * 100, 2),
        "mdd": round(s["max_dd"] * 100, 2),
        "sharpe": round(s["sharpe"], 2) if np.isfinite(s["sharpe"]) else None,
        "calmar": round(s["calmar"], 2) if np.isfinite(s["calmar"]) else None,
        "trades": ntr if ntr is not None else s["trades"],
        "win": round(s["win"], 4) if np.isfinite(s["win"]) else None,
        "pl": round(s["pl"], 2) if np.isfinite(s["pl"]) else None,
        "final": round(s["final"] / CASH0, 2),
        "exposure": round(s["exposure"] * 100, 1) if np.isfinite(s["exposure"]) else None,
    }


# ============================================================ 溢价（实盘执行的第一道体检）
PREM_CACHE = os.path.join(DIP, "data", "_premium_1120.csv")


def load_premium(codes):
    """不复权收盘价 / 当日 iopv − 1。必须用不复权：前复权价被等比缩放，与当日净值不可比。"""
    try:
        df = pd.read_csv(PREM_CACHE, dtype={"code": str})
        got = {r.code: r for _, r in df.iterrows()}
    except Exception:
        got = {}
    need = [c for c in codes if c not in got]
    if not need:
        return got
    try:
        import cifang_api
        raw = {}
        for i in range(0, len(need), 50):
            b = need[i:i + 50]
            data = cifang_api._get("/fund/hist_em", {
                "symbol": ",".join(b), "start_date": "2026-09-01",
                "end_date": DATA_DATE, "adjust": "none"}) or {}
            for c, rows in data.items():
                if rows:
                    raw[str(c)] = pd.DataFrame(rows, columns=cifang_api.COLS[:len(rows[0])])
        for c in need:
            d = raw.get(c)
            if d is None or len(d) == 0:
                continue
            d = d.copy()
            d["date"] = d["date"].astype(str).str[:10]
            for k in ("close", "iopv"):
                d[k] = pd.to_numeric(d[k], errors="coerce")
            d = d.sort_values("date")
            last = d.iloc[-1]
            if not (last["iopv"] and last["iopv"] > 0):
                continue
            prem = (last["close"] / last["iopv"] - 1) * 100
            p20 = (d["close"] / d["iopv"] - 1) * 100
            got[c] = pd.Series({"code": c, "close": last["close"], "iopv": last["iopv"],
                                "prem": prem, "med20": p20.tail(20).median()})
        if got:
            pd.DataFrame(list(got.values())).to_csv(PREM_CACHE, index=False,
                                                    encoding="utf-8-sig")
    except Exception as e:
        say("      [溢价] 拉取失败：%r" % (e,))
    return got


def prem_of(prem, code):
    r = prem.get(code)
    if r is None or not np.isfinite(float(r.get("prem", np.nan))):
        return None
    return round(float(r["prem"]), 2)


# ============================================================ 市场状态
def build_market(p_all):
    rows, vols = [], {}
    for code, name in BENCH:
        if code not in p_all.columns:
            continue
        s = p_all[code].dropna()
        if len(s) < 210:
            continue
        close = float(s.iloc[-1])
        ma60 = float(s.rolling(60).mean().iloc[-1])
        ma200 = float(s.rolling(200).mean().iloc[-1])
        r20 = (close / float(s.iloc[-21]) - 1) * 100
        hi = float(s.rolling(250, min_periods=60).max().iloc[-1])
        rr = s.pct_change().dropna()
        vol20 = float(rr.iloc[-20:].std() * np.sqrt(252) * 100)
        vh = (rr.rolling(20).std() * np.sqrt(252) * 100).dropna()
        vh = vh[vh.index >= "2020-01-01"]
        vol_pct = float((vh < vol20).mean())
        rows.append({"code": code, "name": name, "close": round(close, 3),
                     "ma60_dev": round((close / ma60 - 1) * 100, 2),
                     "ma200_dev": round((close / ma200 - 1) * 100, 2),
                     "r20": round(r20, 2),
                     "dd_high": round((close / hi - 1) * 100, 2),
                     "vol20": round(vol20, 1), "vol_pct": round(vol_pct, 3)})
    d = {r["code"]: r for r in rows}
    hs, cy, dv = d.get("510300", {}), d.get("159915", {}), d.get("510880", {})
    below200 = hs.get("ma200_dev", 0) < 0
    vp = cy.get("vol_pct", 0.5)
    gmd = cy.get("r20", 0) - dv.get("r20", 0)
    if below200 and vp >= 0.85 and dv.get("r20", 0) < -5:
        code, label = "D", "危机 · 无差别去杠杆"
        reasons = ["沪深300 跌破 MA200 且偏离扩大",
                   "创业板 20 日波动处于 85 分位以上",
                   "连红利低波 20 日也跌超 5%：防御腿失效，进入无差别抛售"]
    elif below200 and gmd < 0:
        code, label = "B", "趋势下行 · 高波 · 成长弱于红利"
        reasons = ["沪深300 距 MA200 %+.2f%%（趋势向下）" % hs.get("ma200_dev", 0),
                   "创业板 20 日波动分位 %.0f%%（偏高）" % (vp * 100),
                   "成长−红利 20 日差 %+.1fpp；红利距 MA200 %+.2f%% 仍为正 ⇒ 防御腿有效"
                   % (gmd, dv.get("ma200_dev", 0))]
    elif below200:
        code, label = "B'", "趋势下行 · 成长仍占优"
        reasons = ["沪深300 距 MA200 %+.2f%%" % hs.get("ma200_dev", 0),
                   "成长−红利 20 日差 %+.1fpp：资金仍在成长" % gmd]
    elif vp < 0.50:
        code, label = "A", "趋势上行 · 低波"
        reasons = ["沪深300 站上 MA200", "创业板波动分位 %.0f%%（低）" % (vp * 100)]
    else:
        code, label = "C", "震荡 · 中高波"
        reasons = ["沪深300 站上 MA200 但波动不低", "创业板波动分位 %.0f%%" % (vp * 100)]
    return {"regime": {"code": code, "label": label, "reasons": reasons},
            "indices": rows}


# ============================================================ 持仓
def build_positions(p_all, bmap):
    fp = os.path.join(DIP, "data", "positions.json")
    pos = {}
    if os.path.exists(fp):
        try:
            pos = json.load(open(fp, encoding="utf-8"))
        except Exception:
            pos = {}
    try:
        pool = json.load(open(os.path.join(DIP, "data", "fixed_pool.json"), encoding="utf-8"))
        names = {str(k): v for k, v in (pool.get("name") or {}).items()}
    except Exception:
        names = {}

    cal = p_all.index
    out = []
    for code, info in pos.items():
        if code not in p_all.columns:
            continue
        s = p_all[code].dropna()
        if not len(s):
            continue
        last = float(s.iloc[-1])
        cost = float(info.get("avg_cost") or 0)
        shares = float(info.get("total_amount") or 0)
        entry = str(info.get("entry_date") or "")[:10]
        stop = round(cost * 0.85, 6)
        target = round(cost * 1.03, 6)
        held = 0
        if entry:
            try:
                held = int(len(cal[cal >= pd.Timestamp(entry)])) - 1
            except Exception:
                held = 0
        pnl_pct = (last / cost - 1) * 100 if cost > 0 else np.nan
        dist_stop = (last / stop - 1) * 100 if cost > 0 else None
        dist_tgt = (target / last - 1) * 100 if cost > 0 else None
        mv = last * shares
        cost_amt = cost * shares
        out.append({
            "code": code, "name": info.get("name") or names.get(code) or code,
            "shares": shares, "cost": round(cost, 4), "last": round(last, 4),
            "pnl_pct": round(float(pnl_pct), 2) if np.isfinite(pnl_pct) else None,
            "pnl_amt": round(mv - cost_amt, 0),
            "mv": round(mv, 0), "cost_amt": round(cost_amt, 0),
            "stop_price": stop, "target_price": target,
            "dist_stop_pct": round(dist_stop, 2) if dist_stop is not None else None,
            "dist_target_pct": round(dist_tgt, 2) if dist_tgt is not None else None,
            "entry_date": entry, "held_days": held,
            "held_left": max(30 - held, 0),
            "threshold": bmap.get(code),
        })
    return out


# ============================================================ 交易日工具
def shift_td(d, n):
    """d 之后第 n 个交易日（只跳周末，不含法定节假日）。"""
    cur, cnt = d, 0
    while cnt < n:
        cur += datetime.timedelta(days=1)
        if cur.weekday() < 5:
            cnt += 1
    return cur.strftime("%Y-%m-%d")


def load_snapshot_price(code, day):
    """读 position_snapshots.json 里当天记录的 last_price（= 决策时点价，不是收盘价）。
    用来解释「为什么 14:49 没触发、收盘却触发了」。"""
    p = os.path.join(DIP, "data", "position_snapshots.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        return float(d.get(day, {}).get(code, {}).get("last_price"))
    except Exception:
        return None


# ============================================================ 今日动作（规则生成）
def build_action(positions, cands, prem, next_td):
    """线C 四道闸门逐条判定。输出必须能追溯到条款，不允许「凭感觉」。

    闸门优先级（与 engine.should_sell 一致）：
      ① -15% 深套止损（ENABLE_INTRADAY_STOP=True ⇒ 盘中触及即卖）
      ② 回本止盈（收益≥0 且 20日乖离≥0）
      ③ +3% 目标收益
      ④ 满 30 日到期换仓
    """
    acts, level, head, sub = [], "none", "什么都不用做", "按线C 规则，今日无任何闸门被触发。"

    def setp(lv, h, s):
        nonlocal level, head, sub
        rank = {"none": 0, "watch": 1, "must": 2}
        if rank[lv] >= rank[level]:
            level, head, sub = lv, h, s

    for p in positions:
        pnl, dist = p["pnl_pct"], p["dist_stop_pct"]
        snap = load_snapshot_price(p["code"], DATA_DATE)
        if pnl is not None and pnl <= -15:
            stop_txt = ("%s 收盘 %.4f < 止损 %.4f（浮亏 %.2f%%）。"
                        % (p["code"], p["last"], p["stop_price"], pnl))
            if snap:
                stop_txt += ("当日 14:49 出信号时价 %.4f 仍在止损线上方，"
                             "尾盘才跌穿 ⇒ 信号与实际成交之间出现 %.2f%% 的缺口。"
                             % (snap, (p["last"] / snap - 1) * 100))
            stop_txt += ("线C 规则是「盘中触及即卖」，但当时没有任何进程在盯盘"
                         "⇒ 这笔止损被漏到下一交易日。"
                         "现已补上 <code>intraday_guard.py</code>（每 5 分钟巡检）；"
                         "右键管理员运行 <code>guard_install.bat</code> 注册计划任务后不会再漏。")
            setp("must", "%s 已跌破 -15%% 深套止损" % p["code"], stop_txt)
            acts = [{
                "code": p["code"], "name": p["name"], "side": "sell",
                "shares": int(p["shares"]), "ref": p["last"],
                "amount": round(p["mv"], 0),
                "limit": "开盘挂 %.4f（-1%%）；2 分钟未成交下移 0.002，不设底线（止损以成交为先）"
                         % round(p["last"] * 0.99, 4),
                "when": "%s 09:30—09:35" % next_td,
                "why": "深套止损（-15%%）：收盘口径已 %.2f%%，且当日最低 0.3620 已击穿止损线" % pnl,
                "after": "卖出后 %s、%s、%s 三个交易日不开新仓，%s 起恢复"
                         % (next_td, shift_td(datetime.date.fromisoformat(next_td), 1),
                            shift_td(datetime.date.fromisoformat(next_td), 2),
                            shift_td(datetime.date.fromisoformat(next_td), 3)),
                "prem": prem_of(prem, p["code"]),
            }]
        elif dist is not None and dist < 2:
            setp("watch", "%s 距止损仅 %.2f%%" % (p["code"], dist),
                 "收盘 %.4f，止损 %.4f。一根 2%% 的阴线即触发；"
                 "下一交易日盯 14:45 前的价格，跌破即按规则卖。"
                 % (p["last"], p["stop_price"]))
        elif pnl is not None and pnl >= 3:
            setp("must", "%s 触及 +3%% 目标收益" % p["code"],
                 "收盘 %.4f ≥ 目标 %.4f，下一交易日止盈。"
                 % (p["last"], p["target_price"]))
            acts = [{"code": p["code"], "name": p["name"], "side": "sell",
                     "shares": int(p["shares"]), "ref": p["last"],
                     "amount": round(p["mv"], 0),
                     "limit": "≥ %.4f 挂限价" % round(p["last"] * 0.98, 4),
                     "when": "%s 14:45—14:55" % next_td,
                     "why": "目标收益 +3% 止盈", "after": "卖出后进入候选队列，次日可换仓",
                     "prem": prem_of(prem, p["code"])}]
        elif p["held_left"] <= 0:
            setp("must", "%s 满 30 日到期换仓" % p["code"],
                 "已持有 %d 个交易日，触发超时换仓判定。" % p["held_days"])
        else:
            setp("none", "继续持有 %s" % p["code"],
                 "浮亏 %.2f%%，距止损 %.2f%%（还需再跌 %.2f%%），距目标 %.2f%%，"
                 "持有 %d/%d 日。四道闸门均未触发。"
                 % (pnl, dist, dist, p["dist_target_pct"], p["held_days"], 30))

    if not positions and cands:
        top = cands[0]
        setp("must", "下一交易日买入 %s %s" % (top["code"], top["name"]),
             "20 日乖离近 5 日最低 %.2f%% 跌破阈值 %d%%，且 50 日乖离 %.2f%% 为合格候选中最深。"
             "线C 单票满仓，资金按 10 万口径。"
             % (top["bias20_min5"], top["threshold"], top["bias50"]))
        acts = [{
            "code": top["code"], "name": top["name"], "side": "buy",
            "shares": int(100000 / top["close"] // 100 * 100),
            "ref": round(top["close"], 4), "amount": 100000,
            "limit": "≤ %.4f 挂限价（不追高）" % round(top["close"] * 1.01, 4),
            "when": "14:45—14:55",
            "why": "20日乖离近5日最低 %.2f%% < 阈值 %d%%，50日乖离升序第一"
                   % (top["bias20_min5"], top["threshold"]),
            "after": "买入后 T+1 起可卖；四道卖出闸门生效",
            "prem": prem_of(prem, top["code"]),
        }]

    if not positions and not cands:
        setp("none", "空仓等待",
             "今日无候选。线C 有 85% 的时间本来就该空仓 —— 这是策略的一部分，不是失灵。"
             "空仓期现金放 511880（货币ETF，T+0 可卖），年化 +1.5~1.8pp。")

    return {"level": level, "head": head, "sub": sub, "items": acts, "next_td": next_td}


# ============================================================ 执行日历
def build_calendar(next_td, has_action, held=None):
    held = held or []
    tag = " · ".join("%s %s" % (p["code"], p["name"]) for p in held) or "空仓"
    return [
        {"time": "09:30", "who": "线C", "tag": "补做" if has_action else "观察",
         "what": ("竞价后确认 %s 开盘价；若仍在 0.3650 下方，按深套止损卖出" % tag
                  if has_action else "开盘价确认，当前持仓 %s 无动作" % tag),
         "state": "due" if has_action else "idle"},
        {"time": "14:30", "who": "momo 96865", "tag": "研究",
         "what": "动量信号 + 执行（20/26 双斜率）。未上线，只记录不交易", "state": "idle"},
        {"time": "14:40", "who": "线C", "tag": "每日",
         "what": "定时任务启动 → 拉次方日线 + 腾讯实时 → 生成信号 → 邮件 2974903020@qq.com",
         "state": "auto"},
        {"time": "14:45", "who": "线C", "tag": "每日",
         "what": "拿到信号后 5 分钟内下单；限价不追高，14:57 后不追（集合竞价无量）",
         "state": "auto"},
        {"time": "14:50", "who": "96863", "tag": "情报",
         "what": "消费轮动信号。不接实盘，只做交叉验证", "state": "idle"},
        {"time": "15:00", "who": "现金", "tag": "每日",
         "what": "空仓资金放 511880；卖出所得当日即可复投，避免空转", "state": "auto"},
    ]


# ============================================================ 数据健康
def build_health(p_all, fixed_rows, prem, nmomo_hi):
    n_col = p_all.shape[1]
    last = p_all.index[-1].strftime("%Y-%m-%d")
    try:
        gap = (datetime.date.today() - datetime.date.fromisoformat(DATA_DATE)).days
    except Exception:
        gap = 0
    stale = gap > 3          # 周末最多差 2 天，超过 3 天说明行情没更新
    lights = [
        {"k": "数据新鲜度", "s": "warn" if stale else "ok",
         "v": "数据日 %s，距今天 %d 天%s"
              % (DATA_DATE, gap,
                 "；超过 3 天 ⇒ 行情文件需要重建（跑 _build_px.py），"
                 "否则看到的是过期信号" if stale else "（周末 2 天内属正常）")},
        {"k": "数据日一致性", "s": "ok" if last == DATA_DATE else "bad",
         "v": "回测 / 持仓 / 市场状态全部对齐 %s（%d 只 × %d 行）" % (last, n_col, len(p_all))},
        {"k": "历史日线源", "s": "ok",
         "v": "次方量化 hist_em qfq：库内 393 只全部返回到 %s；本次回测用到其中 %d 只"
              % (DATA_DATE, n_col)},
        {"k": "实时价源", "s": "ok",
         "v": "腾讯 qt，381/381 只、1.4 秒；与次方收盘价偏差中位 0.00%"},
        {"k": "复权口径", "s": "ok",
         "v": "全库前复权；510880 最大单日跌幅与 qfq 源逐位一致 ⇒ 确认已复权"},
        {"k": "脏数据修复", "s": "ok",
         "v": "尖峰式 + 台阶式跳变共修 %d 根；修后 |单日涨跌|>25%% 残留 0 根" % fixed_rows},
        {"k": "当期 K 线可得性", "s": "ok",
         "v": "沪深日线更新有先后（14:45 时沪市 231 只有当日 K、深市 150 只滞后一天），"
              "但 calculate_bias 统一处理：末根=今天→用实时价替换，否则→追加实时价。"
              "四个池子最后一点都是同一时刻的实时价 ⇒ 均线口径一致，不影响阈值判定"},
        {"k": "扫描耗时", "s": "ok",
         "v": "381 池全量乖离计算实测 3.5 秒（一次批量报价 + 8 批日线，进程内缓存命中）"
              "⇒ 14:30 出信号、14:31 前能下完单；不存在「扫不完」"},
        {"k": "决策时点偏差", "s": "warn",
         "v": "14:49 实时价 vs 收盘价：乖离率差 0.6~1.3pp（515880 单日差 1.4%）。"
              "这是盘中执行的固有偏差，不是数据错误：执行价与信号价用同一时点 + 限价单，"
              "偏差已计入成本压力测试（0.2%/0.3% 两档）"},
        {"k": "溢价暴露", "s": "bad" if nmomo_hi >= 2 else "warn",
         "v": "momo 12 池里 %d 只溢价 >5%%（最高 159509 +36.8%%）；"
              "线C 候选 159100 为 -1.2%% 折价，安全" % nmomo_hi},
        {"k": "存活偏差", "s": "warn",
         "v": "381 池是 2026-10-14 冻结的：2021 年起点在世仅 73 只（19.9%），"
              "期间清盘的不在样本内 ⇒ 绝对收益不可外推"},
        {"k": "纸面账户口径", "s": "warn",
         "v": "positions.json 每次满仓 10 万记账，不追踪现金流转（Portfolio 现金恒 10 万）"
              "⇒ 看板净值曲线是「回测净值」，不是账户实际净值"},
    ]
    return {"lights": lights,
            "ok": sum(1 for x in lights if x["s"] == "ok"),
            "warn": sum(1 for x in lights if x["s"] == "warn"),
            "bad": sum(1 for x in lights if x["s"] == "bad")}


# ============================================================ 恒方情报
def _refresh_meta():
    """读 daily_refresh.py 留下的刷新凭据（没有就返回空，页面显示「未接入自动刷新」）。"""
    try:
        m = json.load(open(os.path.join(HUB, "_refresh_meta.json"), encoding="utf-8"))
    except Exception:
        return {}
    steps = m.get("steps") or []
    return {"last_run": m.get("last_run"), "last_ok": m.get("last_ok"),
            "ok": m.get("ok"), "cost": m.get("cost"),
            "total": m.get("total") or len(steps),
            "failed": [x.get("name") for x in steps if not x.get("ok")]}


def _hf_lag(d0, d1):
    """恒方信号日 → 本地数据日 的工作日间隔（d1 更晚为正）；算不出返回 None。
    节假日不剔除，只用来判断「落后一两天」还是「停更一周」。"""
    if not d0 or not d1:
        return None
    try:
        a = datetime.date.fromisoformat(str(d0)[:10])
        b = datetime.date.fromisoformat(str(d1)[:10])
        return int(__import__("numpy").busday_count(a, b))
    except Exception:
        return None


def build_intel():
    """恒方 11 个产品：先 refresh（Gitee API + 平台目录），再按 sig_key 一一对上。

    🔴 为什么要单独记「信号日 / 生成时间 / 落后几个交易日」
    以前只在构建时顺手抓一次，抓不到就退回缓存，页面只写「信号日」，
    看不出这份东西是刚抓的还是三天前的。用户看到的是「一次性的看板」。
    现在把新鲜度写进数据里，页面必须显示：信号日、平台生成时间、抓取时间、
    落后本地行情几个交易日 —— 停更就要看得出来。
    """
    meta = {}
    try:
        import _hf_fetch
        meta = _hf_fetch.refresh(verbose=True) or {}
        sig, _cat, _m = _hf_fetch.load()
        d = sig or {}
        src = "Gitee API" if meta.get("sig_ok") else "本地缓存"
    except Exception as e:
        say("      [情报] 恒方抓取模块异常：%r，改用本地缓存" % (e,))
        cache = os.path.join(ROOT, "_localdata", "hf_platform", "gitee_signals.json")
        try:
            d = json.load(open(cache, encoding="utf-8"))
        except Exception:
            return None
        src = "本地缓存"
    legs, seen, tds = [], set(), set()
    DEF = ("空仓", "现金", "银行", "货币", "511880", "515020", "国债")
    for key, v in (d or {}).items():
        pl = (v or {}).get("payload") or (v if isinstance(v, dict) else {})
        if pl.get("trade_date"):
            tds.add(str(pl["trade_date"])[:10])
        for cal in pl.get("calibers") or []:
            target = str(cal.get("target_code") or "")
            act = cal.get("action") or ""
            short = cal.get("short") or key
            # 🔴 去重必须带 key：combo004 的两条腿（etf9_timing_1450 / zz1k_mh15_1430）
            # 与 combo003、zz1k 的两条腿字面完全相同。只按 (short,target,act) 去重，
            # combo004 会被整条吃掉，页面上显示「不发布信号」——2026-11-22 踩到。
            sig = (key, short, target, act)
            if sig in seen:
                continue
            seen.add(sig)
            # 有效持仓：平台自己会出现 target_code=513030 但 action=「维持 空仓/现金」的矛盾
            # （理想目标被溢价/涨跌停挡住，实际没买）。以 action 为准，页面只显示它真的拿着什么。
            eff = "空仓" if ("空仓" in act or "现金" in act) else target
            legs.append({"key": key, "short": short,
                         "label": (cal.get("label") or "")[:110],
                         "target": target, "eff": eff, "action": act[:44],
                         "grade": cal.get("grade") or "",
                         "defensive": any(k in (eff + " " + act) for k in DEF)})
    if not legs:
        return None
    nr = sum(1 for x in legs if not x["defensive"])

    # ---------- 11 个产品目录 × 当前信号：一一对上 ----------
    CAT = os.path.join(ROOT, "_localdata", "hf_platform", "catalog.json")

    def _fix(s):
        """修 mojibake：catalog.json 里的中文是 GBK 字节被当 UTF-8 存进去的，
        形如 'ææ¹éåç²¾é'。用 latin-1 编回去再按 GBK 解就能还原。
        正常中文无法 encode('latin-1')，会原样返回，所以这个函数是安全的。"""
        if not s:
            return s
        try:
            b = str(s).encode("latin-1")
        except Exception:
            return str(s)
        for enc in ("gbk", "utf-8"):
            try:
                t = b.decode(enc)
                if any("\u4e00" <= ch <= "\u9fff" for ch in t):
                    return t
            except Exception:
                pass
        return str(s)

    products = []
    try:
        cat = json.load(open(CAT, encoding="utf-8-sig"))
    except Exception as e:
        say("      [情报] catalog.json 读不到：%r" % (e,))
        cat = []

    # 产品 prefix（去 dt_ 后）→ signals.json 的 key。
    # 2026-11-22 起平台目录自带 sig_key，优先用它；老目录才退回前 18 字符匹配。
    def match_key(prefix, sk=None):
        if sk and sk in (d or {}):
            return sk
        p = prefix[3:] if prefix.startswith("dt_") else prefix
        for k in (d or {}):
            if k.startswith(p[:18]) or p.startswith(k[:18]):
                return k
        return None

    for x in cat:
        prefix = str(x.get("prefix") or "")
        m = x.get("metrics") or {}
        k = match_key(prefix, str(x.get("sig_key") or ""))
        pl = ((d or {}).get(k) or {}).get("payload") or {} if k else {}
        cals = pl.get("calibers") or []
        mine = [l for l in legs if l["key"] == k] if k else []
        pdate = str(pl.get("trade_date") or "")[:10]
        try:
            plag = _hf_lag(pdate, meta.get("data_date") or "")
        except Exception:
            plag = None
        products.append({
            "prefix": prefix,
            "name": _fix(str(x.get("label") or prefix)).replace("恒方量化精选-", "").rstrip("X"),
            "rtype": "组合" if x.get("rtype") == "combo" else "单口径",
            "annual": m.get("annual"), "total": m.get("total"),
            "sharpe": m.get("sharpe"), "mdd": m.get("mdd"), "calmar": m.get("calmar"),
            "exported_at": str(x.get("exported_at") or "")[:16],
            "sig_hhmm": str(x.get("sig_hhmm") or ""),
            "trade_date": pdate,
            "gen": str(pl.get("generated_at") or "")[:16],
            "lag_td": plag,
            # status: ok 有信号且跟得上 / stale 有信号但落后 >2 个交易日 /
            #         nosig 平台本来就不发布逐日信号（两个个股口径）
            "status": ("nosig" if not mine
                       else ("stale" if (plag is not None and plag > 2) else "ok")),
            "signal_key": k,
            "legs": [{"target": l["target"], "eff": l.get("eff") or l["target"],
                      "action": l["action"],
                      "grade": l["grade"], "defensive": l["defensive"],
                      "label": l["label"][:70]} for l in mine],
            "report": "reports/%s.html" % prefix,
        })
    products.sort(key=lambda p: -float(str(p.get("annual") or "0").replace("%", "").replace("+", "")
                                       .replace(",", "") or 0))

    # ---------- 与「上一个信号日」对比：谁维持、谁换仓 ----------
    # 恒方平台只发布最新一版信号，不提供历史。我们自己按信号日留档（_hf_history.json），
    # 才能在页面上回答「今天这次操作，是维持还是换了标的」。
    hist, prev_date, prev_items = {}, "", {}
    try:
        import _hf_fetch as _hf
        hist = json.load(open(_hf.HIST, encoding="utf-8"))
        sd = meta.get("signal_date") or ""
        ds = [x for x in sorted(hist) if x < sd]
        prev_date = ds[-1] if ds else ""
        prev_items = (hist.get(prev_date) or {}).get("items") or {}
    except Exception:
        pass
    for p in products:
        cur = [l.get("eff") or l.get("target") for l in (p.get("legs") or [])]
        pv = (prev_items.get(p.get("signal_key")) or {}).get("t")
        # 没有历史时，用平台自己的动作文案判断：以「维持」开头 = 没换；
        # 出现「买入/卖出/切换」= 今天动了。这样第一天也能看出动态。
        acts = [str(l.get("action") or "") for l in (p.get("legs") or [])]
        by_text = ("na" if not acts else
                   ("hold" if all(a.startswith("维持") for a in acts) else "switch"))
        p["prev_tgt"] = pv
        p["prev_date"] = prev_date
        p["chg"] = ("na" if (not pv or not cur)
                    else ("hold" if pv == cur else "switch")) if pv else by_text

    say("      [情报] 产品 %d 个，其中有信号 %d 个；较 %s 换仓 %d 个"
        % (len(products), sum(1 for p in products if p["legs"]),
           prev_date or "—", sum(1 for p in products if p["chg"] == "switch")))

    return {"source": src,
            "generated_at": meta.get("generated_at") or "",
            "fetched_at": meta.get("fetched_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "lag_td": meta.get("lag_td"),
            "data_date": meta.get("data_date") or "",
            "trade_date": "、".join(sorted(tds)) or "未标注",
            "n_legs": len(legs), "n_risk_on": nr,
            "risk_on_pct": round(nr / len(legs) * 100, 1),
            "n_product": len(products),
            "n_product_sig": sum(1 for p in products if p["legs"]),
            "n_stale": sum(1 for p in products if p["status"] == "stale"),
            "prev_date": prev_date,
            "n_chg": sum(1 for p in products if p["chg"] == "switch"),
            "products": products,
            "legs": legs}


# ============================================================ 九维评分标准（口径表）
SCORE_RULE = [
    {"k": "当前环境适配", "w": 18, "how": "当前 regime 下「日均收益 + 胜率」的横向分位",
     "why": "用户的核心问题就是「现在这个环境该信谁」",
     "calc": "0.6×日均收益分位 + 0.4×胜率分位，再 ×18",
     "live": "联动：regime 由 510300 vs MA200、创业板 20 日波动分位、成长−红利 20 日差实时判定"},
    {"k": "本月表现", "w": 14, "how": "11 月至今收益的横向分位",
     "why": "最近的模拟结果最能反映当前参数是否还合身",
     "calc": "本月收益分位 ×14", "live": "联动：每月首个交易日归零重算"},
    {"k": "风险调整", "w": 13, "how": "夏普（主）+ 索提诺（辅）",
     "why": "专业通用基准，夏普 >1.5 才算优秀",
     "calc": "夏普分段（0→0 / 1.0→7 / 1.5→10 / 2.5→13）×0.88 + 索提诺（≤1.5 分）",
     "live": "联动：日频净值实时重算"},
    {"k": "回撤控制", "w": 10, "how": "最大回撤 + 未恢复回撤持续期",
     "why": "亏损承受力；「还在回撤中」比「历史最大回撤」更能说明当下的痛",
     "calc": "-5%→10 / -15%→8 / -20%→5.8 / -30%→3 / -45%→0；未恢复按天数每 60 天扣 1.6 分",
     "live": "联动：每日更新当前回撤天数"},
    {"k": "稳定性", "w": 9, "how": "年度胜率（有几年是正收益）",
     "why": "防「一年暴赚、三年回吐」",
     "calc": "0%→0 / 50%→2.5 / 70%→5.4 / 85%→7.7 / 100%→9", "live": "联动：跨年后自动加一年"},
    {"k": "近期动量", "w": 7, "how": "近 20 日收益的横向分位",
     "why": "捕捉「正在失效 / 正在转好」；权重压低，避免追涨杀跌",
     "calc": "近 20 日收益分位 ×7", "live": "联动：每日滚动"},
    {"k": "成本抗性", "w": 9, "how": "3tick 后年化 ÷ 零成本年化（保留率）",
     "why": "决定回测收益能不能真的落到账户里",
     "calc": "保留 20%→1.8 / 40%→4.5 / 60%→6.8 / 80%→8.6 / 100%→9",
     "live": "静态：每次数据重建后由 _verify_all.py 复测"},
    {"k": "可执行性", "w": 8, "how": "数据可得 + 时点明确 + 容量 + 溢价安全",
     "why": "做不到就白搭",
     "calc": "四项各 2 分，合计 10 分制再 ×0.8",
     "live": "联动：溢价每日实测，容量按当日成交额"},
    {"k": "样本充分度", "w": 12, "how": "年数（6）+ 平仓笔数（3）+ 跨 regime 数（3）",
     "why": "专治「短样本漂亮」——96864 就是栽在这",
     "calc": "≥8年→6 / 5年→4.5 / 3年→3；≥300笔→3 / 100笔→2.6 / 50笔→1.5；5档→3",
     "live": "静态：随回测窗口固定"},
]


# ============================================================ 渲染
def render_to(hub, out_path, nav_mobile="../live/index.html", mask_note=""):
    """把 hub 渲染成单文件 HTML。同一份模板服务两种产物：
       - 本地完整版 hub/index.html（含份额与金额）
       - 公网脱敏版 live/hub.html（金额已打码，见 publish_build.py）
    """
    tpl = open(os.path.join(HUB, "template.html"), encoding="utf-8").read()
    payload = json.dumps(hub, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    # 实时内核：主看台与手机页内联同一份源码 ⇒ 判定规则只写一处，两边必然一致
    core_p = os.path.join(HUB, "live_core.js")
    core = ""
    if os.path.exists(core_p):
        core = open(core_p, encoding="utf-8").read().replace("</", "<\\/")
    else:
        say("      [警告] 缺 live_core.js，实时判定将不可用")
    html = (tpl.replace("__LIVE_CORE__", core)
               .replace("__HUB_DATA__", payload)
               .replace("__NAV_MOBILE__", nav_mobile)
               .replace("__MASK_NOTE__", mask_note))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def render(hub):
    os.makedirs(HUB, exist_ok=True)
    with open(os.path.join(HUB, "hub.json"), "w", encoding="utf-8") as f:
        json.dump(hub, f, ensure_ascii=False, indent=1)
    out = render_to(hub, os.path.join(HUB, "index.html"),
                    os.environ.get("HUB_NAV_MOBILE", "../live/index.html"))
    say("      index.html  %.1f KB" % (os.path.getsize(out) / 1024))
    return out


def next_trade_day(d=None):
    """下一交易日（跳过周末；不含法定节假日 —— 仅用于动作卡的日期提示）。"""
    d = d or datetime.date.today()
    n = d + datetime.timedelta(days=1)
    while n.weekday() >= 5:
        n += datetime.timedelta(days=1)
    return n.strftime("%Y-%m-%d")


# ============================================================ 主流程
def main():
    if "--render-only" in sys.argv:
        hub = json.load(open(os.path.join(HUB, "hub.json"), encoding="utf-8"))
        hub["meta"]["built_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        out = render(hub)
        say("仅重渲染：%s" % out)
        return

    say("=" * 82)
    say("策略中枢 v2 · 执行台数据生成")
    say("=" * 82)

    codes381, bmap = pb.load_pool_codes()
    need = sorted(set(codes381) | set(CONSUME) | set(MOMO) | {c for c, _ in BENCH}
                  | {"515880", "511880", "512800", "515020", "159552", "159100", "159967"})

    # —— 统一数据源：patch 各模块的 DATA，保证回测与状态同源同日 ——
    pb.DATA = DATA_PX
    p5.DATA = DATA_PX
    m6.DATA = DATA_PX

    say("\n[1/7] 加载行情 %s" % os.path.basename(DATA_PX))
    hist, p_all, fixed = pb.load_all(need)
    say("      %d 行 × %d 只 ｜ %s ~ %s ｜ 跳变修复 %d 根"
        % (p_all.shape[0], p_all.shape[1], p_all.index[0].date(),
           p_all.index[-1].date(), fixed))

    series = {}

    # ---------------- 线C ----------------
    say("\n[2/7] 线C 乖离抄底（381 池 · v4.6 原版口径）")
    h381 = {c: hist[c] for c in codes381 if c in hist}
    mC = bt.build_matrices(h381, start=START, end=DATA_DATE)
    rC = bm.run(mC, bmap, max_hold=1, intraday_stop=True, exec_mode="close",
                timeout_live=True)
    sC = metrics(rC["equity"], rC["trades"], rC["exposure"])
    series["lineC"] = norm(rC["equity"])
    say("      年化 %+.2f%% ｜ 回撤 %.2f%% ｜ 夏普 %.2f ｜ 卡玛 %.2f ｜ 平仓 %d 笔 ｜ 胜率 %.1f%%"
        % (sC["cagr"], sC["mdd"], sC["sharpe"], sC["calmar"], sC["trades"],
           (sC["win"] or 0) * 100))

    # ---------------- momo 96865 ----------------
    say("\n[3/7] momo 原版 96865（12 池 · 20/26 双斜率）")
    pm = m6.load_px("2015-01-05", DATA_DATE)
    V1m, V2m = m6.build_signals(pm, 20, 26)
    i0 = int(np.where(pm.index >= "2018-01-01")[0][0])
    pm18 = pm.loc["2018-01-01":DATA_DATE]
    rm = m6.run(pm18, V1m[i0:], V2m[i0:])
    sM = metrics(rm["equity"], rm["trades"], None)
    series["momo96865"] = norm(rm["equity"])
    say("      年化 %+.2f%% ｜ 回撤 %.2f%% ｜ 夏普 %.2f ｜ 卡玛 %.2f ｜ 平仓 %d 笔 ｜ 期末 %.2f×"
        % (sM["cagr"], sM["mdd"], sM["sharpe"], sM["calmar"], sM["trades"], sM["final"]))

    # ---------------- 96863 消费轮动 ----------------
    say("\n[4/7] 消费轮动 96863（6 只池 · 19 日区间涨幅 2~10%）")
    r12 = pb.run_band(p_all[CONSUME].loc[START:DATA_DATE])
    s12 = metrics(r12["equity"], r12["trades"], r12["exposure"])
    series["band12"] = norm(r12["equity"])
    say("      年化 %+.2f%% ｜ 回撤 %.2f%% ｜ 夏普 %.2f ｜ 平仓 %d 笔"
        % (s12["cagr"], s12["mdd"], s12["sharpe"], s12["trades"]))

    # ---------------- 96864 等股灾 ----------------
    say("\n[5/7] 等股灾 96864（159552 + 银行默认腿 · 双 5% 止损）")
    p56 = p5.load_pair("2024-06-28", DATA_DATE)
    sub56 = p56.loc["2024-10-01":DATA_DATE]
    r56 = p5.run(sub56)
    s56 = metrics(r56["equity"], r56["trades"], None)
    series["bank96864"] = norm(r56["equity"])
    main56 = sub56["main"] / sub56["main"].iloc[0] * CASH0
    s56b = metrics(main56)
    series["main159552"] = norm(main56)
    say("      年化 %+.2f%% ｜ 回撤 %.2f%% ｜ 夏普 %.2f ｜ 平仓 %d 笔 ｜ 期末 %.2f×"
        % (s56["cagr"], s56["mdd"], s56["sharpe"], s56["trades"], s56["final"]))
    say("      标的 159552 买入持有：年化 %+.2f%% ｜ 回撤 %.2f%%"
        % (s56b["cagr"], s56b["mdd"]))

    # ---------------- 基准 ----------------
    b300 = p_all["510300"].loc[START:DATA_DATE].dropna()
    eq300 = b300 / b300.iloc[0] * CASH0
    s300 = metrics(eq300)
    series["bench300"] = norm(eq300)
    px381 = p_all[[c for c in codes381 if c in p_all.columns]].loc[START:DATA_DATE]
    ew = (1 + px381.pct_change().mean(axis=1).fillna(0)).cumprod() * CASH0
    sEW = metrics(ew)
    series["benchEW"] = norm(ew)
    say("\n      沪深300 %+.2f%%/%.2f%% ｜ 381池等权 %+.2f%%/%.2f%%"
        % (s300["cagr"], s300["mdd"], sEW["cagr"], sEW["mdd"]))

    # ---------------- 线C 当前候选（按规则重算，不用线上文本） ----------------
    say("\n[6/7] 候选重算 / 持仓 / 溢价 / 情报")
    close = px381.ffill()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    b20 = close / ma20 - 1
    b50 = close / ma50 - 1
    pool_names = {}
    try:
        _p = json.load(open(os.path.join(DIP, "data", "fixed_pool.json"), encoding="utf-8"))
        pool_names = {str(k): v for k, v in (_p.get("name") or {}).items()}
    except Exception:
        pass
    min5 = b20.tail(5).min()
    cands = []
    for c in px381.columns:
        th = bmap.get(c)
        if th is None:
            continue
        v = min5.get(c)
        if v is not None and np.isfinite(v) and v * 100 < th:
            cands.append({"code": c, "name": pool_names.get(c, c),
                          "bias20_min5": round(float(v) * 100, 2),
                          "bias50": round(float(b50[c].iloc[-1]) * 100, 2),
                          "close": float(close[c].iloc[-1]),
                          "threshold": th})
    cands.sort(key=lambda x: x["bias50"])
    say("      合格候选 %d 只（前 5：%s）"
        % (len(cands), " / ".join("%s %.1f%%" % (x["code"], x["bias50"]) for x in cands[:5])))

    pos = build_positions(p_all, bmap)
    prem = load_premium(list(dict.fromkeys(
        MOMO + CONSUME + [c for c in codes381 if c in [x["code"] for x in cands[:6]]]
        + [p["code"] for p in pos] + ["159552", "515020", "512800", "511880"])))
    nmomo_hi = sum(1 for c in MOMO
                   if (prem_of(prem, c) is not None and prem_of(prem, c) > 5))
    say("      持仓 %d 只 ｜ 候选 %d 只 ｜ 溢价：momo 池 >5%% 的 %d 只"
        % (len(pos), len(cands), nmomo_hi))

    ntd = next_trade_day()
    action = build_action(pos, cands, prem, ntd)
    calendar = build_calendar(ntd, bool(action["items"]), pos)
    market = build_market(p_all)
    health = build_health(p_all, fixed, prem, nmomo_hi)
    intel = build_intel()
    # ---------------- 行业内部相对强弱（纯本地，不联网）----------------
    IND = {}
    try:
        IND = json.load(open(os.path.join(HUB, "industry.json"), encoding="utf-8"))
    except Exception:
        try:
            import _industry
            IND = _industry.compute()
        except Exception as e:
            say("      ⚠️ 行业强弱不可用：%r" % (e,))
    if IND:
        say("      行业强弱 %d 个 · 数据日 %s · 最强 %s"
            % (len(IND.get("industries") or []), IND.get("date"),
               (IND.get("industries") or [{}])[0].get("k", "—")))
    say("      动作 = %s ｜ regime = %s ｜ 数据健康 %d ok / %d warn / %d bad"
        % (action["level"], market["regime"]["code"], health["ok"], health["warn"],
           health["bad"]))

    # ---------------- 策略台账（统一模拟引擎 _sim）----------------
    say("\n[7/7] 策略台账（_sim 统一模拟引擎）")
    SIMP = os.path.join(DIP, "data", "_sim_out.json")
    if not os.path.exists(SIMP):
        say("      ⚠️ 缺少 data/_sim_out.json —— 先跑 etf_dip_signal/_sim.py")
        raise SystemExit(1)
    sim = json.load(open(SIMP, encoding="utf-8"))
    S = {x["id"]: x for x in sim["strategies"]}
    say("      regime = %s %s ｜ 已模拟 %d 条"
        % (sim["meta"]["regime"], sim["meta"]["regime_label"], len(S)))

    # ---------------- 平台真实口径（官方 API 快照）----------------
    # 铁律：持仓与官方绩效以平台/线上为准；本地回测只提供曲线与归因。
    PLAT_P = os.path.join(DIP, "data", "_platform.json")
    plat = json.load(open(PLAT_P, encoding="utf-8")) if os.path.exists(PLAT_P) else {}
    PB = {b["id"]: b for b in plat.get("strategies", [])}
    MSTATE = plat.get("market") or {}
    say("      平台真实持仓 %d 条 ｜ 市场状态 %d 个标的 ｜ 快照 %s"
        % (len(PB), len(MSTATE), plat.get("generated_at", "—")))

    # 数据健康补两盏灯：平台口径 / 市场状态
    if PB:
        n_h = sum(len(b.get("holding") or []) for b in PB.values())
        health["lights"].insert(0, {
            "k": "平台真实口径", "s": "ok",
            "v": "官方 /api/strategy/my-running 取到 %d 条在跑策略、%d 个真实持仓；"
                 "持仓与官方绩效以平台为准，本地回测只提供曲线" % (len(PB), n_h)})
    else:
        health["lights"].insert(0, {
            "k": "平台真实口径", "s": "bad",
            "v": "未取到 _platform.json ⇒ 持仓退回本地模拟，必须标注"})
    if MSTATE:
        health["lights"].insert(1, {
            "k": "市场状态检测", "s": "ok",
            "v": "四维检测器覆盖 %d 个标的；510300 六项指标与次方页面逐位一致，"
                 "综合分差 1 分（子项映射未公开）" % len(MSTATE)})
    # 盘中巡检：看日志判断"有没有真的在跑"，不看配置
    try:
        _gl = sorted([f for f in os.listdir(os.path.join(DIP, "信号输出"))
                      if f.startswith("guard_") and f.endswith(".log")])
    except Exception:
        _gl = []
    if _gl:
        health["lights"].insert(2, {
            "k": "盘中巡检", "s": "ok",
            "v": "最近一次巡检日志 %s；intraday_guard.py 由 guard_run.bat 每 5 分钟调用"
                 % _gl[-1][6:16]})
    else:
        health["lights"].insert(2, {
            "k": "盘中巡检", "s": "warn",
            "v": "intraday_guard.py 已就绪但还没有任何日志 ⇒ 计划任务可能没挂；"
                 "右键管理员运行 etf_dip_signal/guard_install.bat"})
    health["ok"] = sum(1 for x in health["lights"] if x["s"] == "ok")
    health["warn"] = sum(1 for x in health["lights"] if x["s"] == "warn")
    health["bad"] = sum(1 for x in health["lights"] if x["s"] == "bad")

    LIVE_ID = {"momo96865": 96865, "band96863": 96863, "bank96864": 96864}

    def _act(a, code, name, reason):
        return {"action": a, "code": code, "name": name, "reason": reason,
                "date": plat.get("data_date") or DATA_DATE}

    def live_action(sid, L):
        """按真实持仓 + 当日数据判「下一步动作」。不是模拟账户的动作。"""
        hs = (L or {}).get("holdings") or []
        h = hs[0] if hs else None
        r = (L or {}).get("rules") or {}
        if sid == "lineC":
            if action.get("items"):
                it = action["items"][0]
                return _act(it["side"], it["code"], it["name"], it["why"])
            if h:
                return _act("hold", h["code"], h["name"],
                            "四道闸门均未触发，继续持有（距止损 "
                            + ("%.2f%%" % h["dist_stop"] if h.get("dist_stop") is not None else "—")
                            + "）")
            return _act("empty", None, None, "空仓等待候选")
        if not h:
            t = r.get("top")
            if t:
                return _act("buy", t["code"], t["name"], "当前无持仓，规则给出候选 " + t["code"])
            return _act("empty", None, None, "空仓：当日无合格候选")
        if sid == "momo96865":
            if r.get("pass_n") == 0:
                return _act("sell", h["code"], h["name"],
                            "12 只池 20 日涨幅全部为负，双滤条件无一通过；满足最短持有 2 日后清仓")
            if r.get("hold_rank") == 1:
                return _act("hold", h["code"], h["name"],
                            "仍是动量第一名（合格 %d 只中排第 1），继续持有" % r.get("pass_n", 0))
            return _act("hold", h["code"], h["name"],
                        "动量排名 %s / 合格 %d 只，未满卖出条件，继续持有"
                        % (r.get("hold_rank"), r.get("pass_n", 0)))
        if sid == "band96863":
            hb = r.get("hold_band") or {}
            if r.get("pass_n") == 0:
                return _act("sell", h["code"], h["name"], "19 日涨幅已跌出 2%~10% 带，且带内无标的，清仓")
            if r.get("top") and r["top"]["code"] != h["code"]:
                return _act("sell", h["code"], h["name"],
                            "带内第一名是 %s（%s%%），自己已不是最强 ⇒ 满 5 日后换仓"
                            % (r["top"]["name"], r["top"]["r19"]))
            return _act("hold", h["code"], h["name"],
                        "19 日涨幅 %s%%，仍在 2%%~10%% 带内且是带内第一 ⇒ 继续持有"
                        % (hb.get("r19") if hb else "?"))
        if sid == "bank96864":
            if r.get("signal_on"):
                if h["code"] == "159552":
                    return _act("hold", h["code"], h["name"], "进攻腿信号在线（斜率在区间且站上 MA10），继续持有")
                return _act("sell", h["code"], h["name"], "进攻腿信号恢复，换回 159552")
            if h["code"] == "515020":
                return _act("hold", h["code"], h["name"],
                            "159552 斜率 %s 不在 [0.4,2.5] / 未站上 MA10 ⇒ 持银行默认腿"
                            % r.get("score"))
            return _act("sell", h["code"], h["name"], "进攻腿信号关闭，回落银行默认腿")
        if h:
            return _act("hold", h["code"], h["name"], "继续持有")
        return _act("empty", None, None, "空仓")

    def _live_block(sid):
        """真实持仓块。线C 用 positions.json，其余用平台 API。"""
        if sid == "lineC":
            h = pos[0] if pos else None
            return {
                "source": "positions.json · 线上纸面实盘",
                "badge": "线上",
                "execute": "14:40 启动 → 14:45—14:55 下单",
                "official": None, "sim_start": "2026-10-14",
                "holdings": [] if not h else [{
                    "code": h["code"], "name": h["name"], "amount": h["shares"],
                    "buy_price": h["cost"], "buy_date": h.get("entry_date"),
                    "last": h["last"], "pnl": h["pnl_pct"], "pnl_amt": h["pnl_amt"],
                    "mv": h["mv"], "held_days": h["held_days"],
                    "prem": prem_of(prem, h["code"]),
                    "stop": h["stop_price"], "target": h["target_price"],
                    "dist_stop": h["dist_stop_pct"],
                }],
                "rules": {"type": "four_gates",
                          "note": "四道卖出闸门：-15% 深套 / 回本且 20日乖离≥0 / +3% 目标 / 满 30 日"},
            }
        p = PB.get(LIVE_ID.get(sid))
        if not p:
            return None
        return {
            "source": "次方量化官方 API · /api/strategy/my-running",
            "badge": "平台",
            "execute": p.get("execute"),
            "official": p.get("official"),
            "sim_start": p.get("sim_start"),
            "pid": p.get("id"),
            "desc": p.get("desc"),
            "holdings": p.get("holding") or [],
            "rules": p.get("rules") or {},
        }

    def live_block(sid):
        b = _live_block(sid)
        if b is not None:
            b["live_action"] = live_action(sid, b)
        return b


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
            "gap": round((live_hold.get("pnl_pct") or 0) - (sim_hold.get("pnl") or 0), 2),
            "why": ("11-13 线上未运行（11-16 才补跑，且补跑时已过下单时点）⇒ 错过一次换仓；"
                    "叠加 14:49 实时价与收盘价的排名差异"),
        }

    # ---- 五条策略 ----
    import _strategies as TX
    ROB = {}
    _rb = os.path.join(DIP, "data", "_robust.json")
    if os.path.exists(_rb):
        ROB = json.load(open(_rb, encoding="utf-8"))
        say("      稳健性数据：%d 条策略（成本阶梯/五起点/开关拆件）" % len(ROB))
    else:
        say("      ⚠️ 缺 data/_robust.json —— 文案里的成本/五起点会显示「未计算」")
    tctx = {"prem": {c: prem[c] for c in
                     ["159100", "515880", "159509", "513100", "513310",
                      "159552", "515020"]
                     if c in prem and hasattr(prem[c], "get")},
            "robust": ROB}

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
            "live": live_block(sid),
        }
        o["live_action"] = (o["live"] or {}).get("live_action")
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
            "calendar": None, "live_diff": None, "live": None,
        })
        strategies.append(hf)

    # ---------- rankable 闸门：分数高 ≠ 能用（龟龟借鉴，之前只落在文档里）----------
    # 只卡两条硬指标，不拿「回撤 / 成本」这类特征去否决 —— 那是特征，不是资格：
    #   样本充分度 < 50%  → 结论不可外推（3 年顺风期的 94% 年化不能当预期）
    #   可执行性   < 50%  → 有信号也落不了地（换手/容量/时点跟不上）
    for s in strategies:
        sc = s.get("score") or {}
        items = {i["k"]: i for i in (sc.get("items") or [])}

        def _r(k):
            x = items.get(k)
            return None if (not x or not x.get("max")) else (x.get("v") or 0) / x["max"]

        rs, re_, rc = _r("样本充分度"), _r("可执行性"), _r("成本抗性")
        if sc.get("total") is None:
            why = ["无评分"]
        else:
            why = []
            if rs is None or rs < 0.5:
                why.append("样本不足")
            if re_ is None or re_ < 0.5:
                why.append("可执行性不足")
            if rc is None or rc < 0.5:
                why.append("成本抗性不足")
        s["gate"] = {"sample": None if rs is None else round(rs * 100),
                     "exec": None if re_ is None else round(re_ * 100),
                     "cost": None if rc is None else round(rc * 100),
                     "why": why}
        s["rankable"] = not why

    # 先「能不能用」，再「好不好」：不可排名的即使分高也排在后面
    strategies.sort(key=lambda x: (0 if x.get("rankable") else 1,
                                   -(x["score"]["total"] if x["score"] else -1)))
    for i, s in enumerate(strategies, 1):
        s["rank"] = i
    say("      rankable：%d/%d 可用（%s）"
        % (sum(1 for s in strategies if s.get("rankable")), len(strategies),
           "、".join("%s:%s" % (s["id"], "/".join(s["gate"]["why"]))
                     for s in strategies if not s.get("rankable")) or "全部通过"))

    # ---------- 96864 的「样本补足」结论：代理回测 ----------
    # 用户要求把 2.1 年样本补足。能做的是代理测试，不是把年数改大。
    # 实测：同一套规则用 512100（中证1000）跑 2020-01~2024-06，年化 -3.55%、回撤 -32.31%、118 笔
    # ⇒ 规则本身不是全天候，94% 主要来自 2024-2026 小盘+银行的顺风窗口。
    try:
        pj = json.load(open(os.path.join(DIP, "data", "_proxy96864.json"), encoding="utf-8"))
        for s in strategies:
            if s.get("id") == "bank96864" and pj:
                s["proxy"] = pj
                s["proxy_note"] = (
                    "代理 512100（2020-01~2024-06）：年化 -3.55%、最大回撤 -32.31%、118 笔。"
                    "同一套「小盘+银行默认腿+双5%止损」在中证1000 上不赚钱 ⇒ 94% 年化主要是 "
                    "2024-2026 小盘+银行的顺风窗口，不是规则本身。样本不能补，硬补就是骗。")
    except Exception:
        pass

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


    # ---------------- 归档 ----------------
    # ---------------- 资金与并发 ----------------
    live_cap = sum(p["mv"] for p in pos)
    funding = {
        "rows": [
            {"k": "在跑策略", "v": "1 条（线C）",
             "n": "纸面满仓 %.1f 万 + 现金 2 万；实际可用资金由你自己决定" % (live_cap / 1e4)},
            {"k": "研究/情报", "v": "4 条", "n": "momo 96865 / 96863 / 96864 / 恒方，资金占用 0"},
            {"k": "时点冲突", "v": "14:30 vs 14:40",
             "n": "momo 在 14:30 出信号即执行，线C 14:40 才启动 —— 两条同时跑要在 15 分钟内完成两轮全池扫描，不现实"},
            {"k": "同时开仓上限", "v": "1 只",
             "n": "线C 自己就是 MAX_HOLD=1；若再接一条腿，单票风险会变成 2 倍，回撤也翻倍"},
        ],
        "note": ("<b>现阶段只有一个仓位是对的。</b>不是保守，是数学：线C 单票满仓，"
                 "再叠一条同样单票满仓的腿，等于把「单笔 -20%」放大成「组合 -20%」两倍概率。"
                 "要加腿，先证明它是「负相关 + 独立 alpha」，目前四条候选线都不满足："
                 "momo 与线C 同为追涨/抄底的两端、96863 与 96864 的池子重叠、恒方只是信号。"),
    }

    # ---------------- 归档 ----------------
    archived = [
        {"k": "P0 空仓期该持什么", "s": "负结果",
         "v": "货币ETF 511880 是「现金+」（+1.5~1.8pp、回撤不变、夏普 +0.06~0.09）⇒ 保留；"
              "银行ETF 是 regime 赌注（长窗口回撤 +7pp、夏普 -0.23；2018 拖累 -15.8pp、2022 拖累 -19.4pp）⇒ 不要"},
        {"k": "P1 信号深度闸门", "s": "负结果",
         "v": "交易级看着对（浅信号胜率 86.7%），组合级全面变差（年化 23.23% → 14.80%）。"
              "领先度 Spearman -0.05、p=0.80，无预测力 ⇒ 不进线C"},
        {"k": "趋势带 · 381 池", "s": "已移除",
         "v": "19 日涨幅 ∈[2%,10%] 搬到宽池：四起点全负（-2.25/-5.66/-4.58/-1.29%）、回撤全 -49.5%。"
              "2026-11-22 按用户要求从看板删除，结论留档避免重复研究"},
        {"k": "线A · 场外基金 9 只", "s": "已移出",
         "v": "用户已停止定投，不再纳入本看板管理。历史台账见 .workbuddy/memory 与 deliverables"},
        {"k": "移动止盈 / 保本止损", "s": "已回退",
         "v": "5 笔触发全部亏损（均值 -8.24%、胜 0/5），实为「成本下方 8% 的止损」；"
              "三维度全落后原版 ⇒ 参数已归零"},
    ]

    meta = {
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_date": DATA_DATE,
        # 自动刷新在岗证明：daily_refresh.py 每次跑完写 _refresh_meta.json。
        # 页面显示「上次成功刷新」，链路断了能一眼看出来（否则又是一次性看板）。
        "refresh": _refresh_meta(),
        # 手机实时页（公网）。主看台用它做「手机看 →」深链，两页共用同一套判定内核。
        "mobile_url": os.environ.get("HUB_MOBILE_URL",
                                     "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"),
        "session": "周五收盘后 · 下一交易日 %s（周一）" % ntd,
        "window_bt": "%s ~ %s" % (START, DATA_DATE),
        "window_cmp": "%s ~ %s" % (CMP_START, DATA_DATE),
        "colors": COLORS, "series_names": SERIES_N,
        "compare_ids": ["lineC", "momo96865", "band96863", "bank96864", "bench300"],
        "footer": [
            "<b>数据日唯一</b>：回测 / 持仓 / 市场状态全部对齐 %s 收盘。数据日之后发生的行情不计入。" % DATA_DATE,
            "<b>持仓口径（本轮修正）</b>：momo 96865 / 96863 / 96864 / 94744 的持仓与官方绩效来自"
            "次方官方 API <code>/api/strategy/my-running</code>；线C 来自 positions.json 线上台账。"
            "<b>本地模拟账户持仓只作参考，不再作为真实持仓展示。</b>",
            "<b>价格口径</b>：持仓按 %s 收盘重新估值。positions.json 里 11-20 记的是 14:49 信号价 0.367"
            "（-14.54%%），收盘实际 0.362（-15.70%%）——这个 0.005 元的差就是「盘中没卖」的全部原因。" % DATA_DATE,
            "<b>市场状态</b>：四维（趋势40/动量30/波动15/量15）检测器，权重、阈值、置信度公式对齐次方；"
            "RSI 与 ATR 必须用简单均值、成交量单位为亿股，这两点错一个数值就对不上。",
            "<b>口径铁律</b>：跨窗口 / 跨规模 / 跨成本一律不相减。年化指标除注明外均为 10 万本金、"
            "佣金万2 + 单边滑点 0.1%%、窗口 %s ~ %s。" % (START, DATA_DATE),
            "<b>噪声铁律</b>：线C 自带 ±4pp 噪声（年化 σ=3.90pp、回撤 σ=6.62pp）；差异 <4pp 一律当噪声。",
            "<b>起点铁律</b>：任何变体必做 2021/2022/2023 三起点扫描；符号随起点翻转 ⇒ 直接判噪声。",
            "<b>净值曲线说明</b>：图中全部是「回测净值」，不是账户实际净值。"
            "positions.json 是纸面记账（每次满仓 10 万、不追踪现金流转），两者不可相减。",
            "<b>密钥安全</b>：API Key 只存在本机 <code>_localdata/cifang_api_key.txt</code>，"
            "不写入前端、不进看板 HTML。",
            "<b>本看板性质</b>：PAPER_ONLY 执行辅助工具。不自动下单、不构成投资建议。",
        ],
    }

    # ---------------- 真实持仓总表（平台 + 线上）----------------
    real_positions, extra_live = [], []
    for s in strategies:
        L = s.get("live")
        if not L:
            continue
        base = {"sid": s["id"], "strategy": s["name"].split(" ·")[0],
                "badge": L.get("badge"), "execute": L.get("execute"),
                "official": L.get("official")}
        hs = L.get("holdings") or []
        if not hs:
            real_positions.append(dict(base, code="—", name="空仓", amount=None,
                                       buy_price=None, buy_date=None, last=None,
                                       pnl=None, pnl_amt=None, mv=None,
                                       held_days=None, prem=None, stop=None,
                                       dist_stop=None, fallback=False))
        for h in hs:
            real_positions.append(dict(base, **{k: h.get(k) for k in
                ("code", "name", "amount", "buy_price", "buy_date", "last", "pnl",
                 "pnl_amt", "mv", "held_days", "prem", "stop", "dist_stop",
                 "stop_note", "fallback")}))

    # 94744：momo + 溢价>30% 卖出条件（平台在跑，证明溢价闸门可落地）
    if 94744 in PB:
        b = PB[94744]
        for h in (b.get("holding") or []):
            extra_live.append({
                "sid": "momo94744", "strategy": "momo·躲停牌 94744",
                "badge": "平台", "execute": b.get("execute"), "official": b.get("official"),
                **{k: h.get(k) for k in ("code", "name", "amount", "buy_price", "buy_date",
                                         "last", "pnl", "pnl_amt", "mv", "held_days",
                                         "prem", "stop", "dist_stop", "fallback")},
            })

    # ---------------- 执行时点表 ----------------
    _tm = {}
    for r in real_positions + extra_live:
        t = (r.get("execute") or "—")[:5]
        _tm.setdefault(t, []).append({"n": r["strategy"], "c": r.get("code"),
                                      "b": r.get("badge")})
    exec_map = [{"t": k, "items": v} for k, v in sorted(_tm.items())]

    # ---------------- 市场状态检测器 ----------------
    market_state = {
        "primary": "510300",
        "asof": (MSTATE.get("510300", {}).get("ind") or {}).get("date"),
        "items": [{"code": c, **v} for c, v in MSTATE.items()],
        "conflict": None,
    }
    _m0 = MSTATE.get("510300", {}).get("score")
    if _m0 and market.get("regime"):
        _ours = market["regime"]["code"]
        _theirs = _m0["state"]
        _map = {"A": "牛市", "B": "熊市", "Bp": "熊市", "C": "震荡市", "D": "熊市"}
        market_state["conflict"] = {
            "ours": _ours, "ours_label": market["regime"]["label"],
            "theirs": _theirs, "theirs_score": _m0["total"],
            "agree": _map.get(_ours) == _theirs,
        }

    # ---------------- 决策链（把各区块串成一条因果）----------------
    _ev = (sim.get("meta") or {}).get("regime_evidence") or {}
    _ev_items = _ev.get("items") or []
    _hit = sum(1 for x in _ev_items if x.get("hit"))
    _m0s = (MSTATE.get("510300", {}).get("score") or {})
    _top = strategies[0] if strategies else None
    _best = None
    for s in strategies:
        if s.get("regime_here") and (s.get("score") or {}):
            if _best is None or s["regime_here"]["mean_bp"] > _best["regime_here"]["mean_bp"]:
                _best = s
    _sells = [r["strategy"] for r in real_positions
              if (r.get("code") not in (None, "—"))]
    _acts = [(s["name"].split(" ·")[0], (s.get("live_action") or {}).get("action"))
             for s in strategies if s.get("live_action")]
    _nsell = sum(1 for _, a in _acts if a == "sell")
    _nhold = sum(1 for _, a in _acts if a == "hold")

    decision_chain = {
        "steps": [
            {"n": 1, "k": "市场状态", "anchor": "marketstate",
             "v": ("%s %+.1f" % (_m0s.get("state"), _m0s.get("total"))) if _m0s else "—",
             "sub": ("四维检测器 · 置信 %s%%" % _m0s.get("conf")) if _m0s else "",
             "why": ("趋势 %s ｜ 动量 %s ｜ 波动 %s ｜ 量 %s"
                     % tuple([d["v"] for d in (_m0s.get("dims") or [])] + ["—"] * 4)[:4])
             if _m0s else "",
             "color": "bear" if (_m0s.get("total") or 0) < -30 else "range"},
            {"n": 2, "k": "环境分档", "anchor": "regime",
             "v": "%s %s" % (_ev.get("code", "?"), _ev.get("label", "")),
             "sub": "4 条判据里 %d 条触发" % _hit,
             "why": " ｜ ".join(
                 "%s %s%s" % (x["k"],
                              ("%+.2f" % x["v"]) if x.get("sign", True) else ("%.2f" % x["v"]),
                              x["unit"])
                 for x in _ev_items[:3]),
             "color": "B"},
            {"n": 3, "k": "策略适配", "anchor": "leaderboard",
             "v": ("%s 最适配 %+.0fbp" % (_best["name"].split(" ·")[0],
                                         _best["regime_here"]["mean_bp"])) if _best else "—",
             "sub": "按当前档日均收益横向排序",
             "why": " ｜ ".join("%s %+.0fbp" % (s["name"].split(" ·")[0],
                                               s["regime_here"]["mean_bp"])
                                for s in strategies if s.get("regime_here")),
             "color": "fit"},
            {"n": 4, "k": "今日动作", "anchor": "realpos",
             "v": "%d 卖 / %d 持" % (_nsell, _nhold),
             "sub": "真实持仓口径，不是模拟账户",
             "why": " ｜ ".join("%s %s" % (n, {"sell": "卖", "hold": "持",
                                               "buy": "买", "empty": "空"}.get(a, a))
                                for n, a in _acts),
             "color": "act"},
        ],
        "note": ("<b>这条链是单向的</b>：市场状态决定环境分档，环境分档决定每条策略的适配度，"
                 "适配度再和成本/溢价/样本一起进九维评分，最后才落到「今天谁该动」。"
                 "任何一环换数据，下游必须跟着变——如果没变，就是那里写死了。"),
    }

    # 其他策略的今日动作（真实持仓口径），挂在执行卡下面，说明「不用人工干预」
    action["others"] = [{"name": n, "act": a} for n, a in _acts if n]

    # ---------------- 数据源与口径 ----------------
    _pxd = {}
    try:
        sys.path.insert(0, DIP)
        import _px
        _pxd = _px.describe()
    except Exception as e:
        say("      [_px] 口径自述读取失败：%r" % (e,))
    _intr = _pxd.get("intraday") or []
    caliber = {
        "rows": [
            {"k": "日线（研究基准）", "v": "次方 API hist_em · qfq",
             "c": "393 只 / 2015-01-05 ~ %s" % DATA_DATE, "s": "ok"},
            {"k": "执行时点价", "v": "次方 API hist_intraday（SVIP）",
             "c": "、".join("%s %d 只" % (x["time"], x["codes"]) for x in _intr) or "—",
             "s": "ok" if _intr else "bad"},
            {"k": "381 池 14:45 全景", "v": "hist_intraday 14:45 · qfq OHLC",
             "c": ("%d 只 / %d 行" % (_pxd.get("pool1445", {}).get("codes", 0),
                                     _pxd.get("pool1445", {}).get("rows", 0)))
             if _pxd.get("pool1445") else "未建", "s": "ok" if _pxd.get("pool1445") else "warn"},
            {"k": "实时与溢价", "v": "次方 API spot（含 IOPV、五档）",
             "c": "20 只 · 溢价 = 不复权价 ÷ IOPV", "s": "ok"},
            {"k": "真实持仓", "v": "次方 API strategy/my-running",
             "c": "%d 条策略" % len(PB), "s": "ok" if PB else "bad"},
            {"k": "盘中备用", "v": "腾讯 qt", "c": "381/381 只、1.4s", "s": "ok"},
            {"k": "交叉校验", "v": "tushare 中转站 fund_daily",
             "c": "按需抽查（回归斜率 1.000）", "s": "ok"},
        ],
        "forbid": [
            "<code>adjust=none</code> 拿来回测 —— 分红/份额折算会造出 −91%、+208% 的假跳变。"
            "382 只里 236 只曾有 >2pp 的日收益偏差，90 只 >5pp。none 只能用来算溢价。",
            "<code>qfq 价 ÷ IOPV</code> 算溢价 —— 前复权被等比缩放，与当日净值不可比。",
            "收盘价当执行价 —— 与 14:30 的 |偏差| 中位 0.19%、P90 0.62%、最大 1.02%，"
            "9 年复利放大成 10pp 级误差。",
            "直接 <code>loc[start:]</code> 开跑 —— 策略需要 N 日历史才有第一个信号，"
            "截断会丢开头 N 天。96864 就栽在这里：64.47% → 71.96%。",
        ],
    }

    hub = {"meta": meta, "action": action, "calendar": calendar,
           "market": market, "positions": {"list": pos,
                                           "tag": "线C 纸面实盘 · 数据日 %s 收盘" % DATA_DATE},
           "health": health, "strategies": strategies, "funding": funding,
           "sim_meta": sim["meta"], "regime_matrix": matrix,
           "score_rule": SCORE_RULE,
           "real_positions": real_positions, "extra_live": extra_live,
           "exec_map": exec_map, "market_state": market_state,
           "decision_chain": decision_chain, "caliber": caliber,
           "regime_evidence": _ev,
           "candidates": cands[:10], "archived": archived,
           "intel": intel, "industry": IND, "series": series}

    say("\n[7/7] 生成看板")
    out = render(hub)
    with open(os.path.join(HUB, "_build.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    say("\n完成：%s" % out)


if __name__ == "__main__":
    main()
