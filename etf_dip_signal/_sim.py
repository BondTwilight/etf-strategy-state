# -*- coding: utf-8 -*-
"""
_sim.py —— 统一策略模拟引擎（2026-11-22）

为什么要有这一层
----------------
原来每条策略各有一套回测脚本，输出格式不一样（DataFrame / list、shares / amount），
所以看板只能拿来做「研究卡片」，做不出「每日持仓 + 今日操作 + 调仓记录」。

这一层把五条策略统一成同一个账户模型：
    {equity, trades, holdings, today_action, monthly, by_year, by_regime, metrics}

设计原则（对齐次方量化的实盘模拟思路）
--------------------------------------
1. **回测段与模拟段分界**：策略的「发布日」之后才算样本外。
   我们本地没有真正的发布动作，所以用「参数冻结日」当分界：
   线C 2026-10-14（池子冻结）、其余三条 2026-11-22（本轮复现完成）。
   分界前的净值是回测，分界后是模拟跟踪 —— 两者必须在图上用不同线型。
2. **当前持仓必须能算出来**：从 trades 反推最后一个 buy 且未被 sell 的标的，
   用当日收盘算浮盈、用交易日历算持有天数。
3. **今日操作要有理由**：不是「买了」，而是「11-20 买入 159509，因为 20 日加权斜率
   年化×R²=2.85 排第一」。
4. **环境适配度必须条件化**：把每个历史交易日打上 regime 标签，统计策略在每个
   regime 下的日均收益与夏普，再看「当前 regime」排第几。这才是「适配期/不适配期」。

口径
----
- 数据：data/all_etf_1120.parquet（2015-01-05 ~ 2026-11-20，qfq，已修跳变）
- 成本：各策略原始口径（线C 万2+0.1%、momo 万1+0.1%、96863 万2.5+0.1%、96864 万0.5+0.1%）
- 本金：10 万
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.chdir(BASE)

import bt_etf_dip as bt
import bt_multi as bm
import data_quality
import _p4_band as pb
import _p5_bank as p5
import _p6_momo as m6
import _px

DATA = os.path.join(BASE, "data", "all_etf_1120.parquet")
END = "2026-11-20"
CASH0 = 100000.0
CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]
CONSUME_N = {"162411": "油气", "513100": "纳指100", "161128": "标普信息",
             "588000": "科创50", "162415": "美国消费", "515450": "红利低波"}

# ★ 必须 patch 各模块的 DATA，否则子模块还在读旧的 all_etf_1119
pb.DATA = DATA
p5.DATA = DATA
m6.DATA = DATA

# 参数冻结日 = 「模拟段」起点（此日之后是样本外）
# 线C 的池子在 2026-10-14 冻结，之后 28 个交易日是真正的样本外。
# 其余三条策略的参数是在 2026-11-22 本轮复现中确定的 ⇒ 没有样本外段，必须如实标注。
FREEZE = {
    "lineC": "2026-10-14",
    "momo96865": None,
    "band96863": None,
    "bank96864": None,
}


# ============================================================ 数据
def load_all():
    "读库 + 修跳变，返回 (hist dict, 收盘矩阵, 高/低/开, 名称表, 修根数)"
    codes, bmap = pb.load_pool_codes()
    pool = json.load(open("data/fixed_pool.json", encoding="utf-8"))
    names = {str(k): v for k, v in (pool.get("name") or {}).items()}
    need = sorted(set(codes) | set(CONSUME) | set(m6.CODES)
                  | {"510300", "510500", "512100", "159915", "510880",
                     "515880", "511880", "512800", "515020", "159552", "159100", "159967"})
    df = pd.read_parquet(DATA)
    df["code"] = df["code"].astype(str)
    df["date"] = df["date"].astype(str).str[:10]
    sub = df[df.code.isin(set(need))]
    hist, fixed = {}, 0
    cols = {}
    for c, g in sub.groupby("code"):
        s = g[["date", "open", "high", "low", "close", "volume"]].copy()
        s = s.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        s2, hits = data_quality.repair_prices(s)
        fixed += len(hits)
        hist[c] = s2
        cols[c] = pd.to_numeric(
            s2.set_index(pd.to_datetime(s2["date"]))["close"], errors="coerce").astype(float)
    px = pd.DataFrame(cols).sort_index()
    return hist, px, names, fixed, codes, bmap


# ============================================================ 环境标签（日频）
def regime_series(px):
    """给每个交易日打 regime 标签。只用当日及以前的信息，无未来函数。

    A   趋势上行 · 低波
    B   趋势下行 · 高波 · 成长弱于红利（防御腿有效）
    B'  趋势下行 · 成长仍占优
    C   震荡 · 中高波
    D   危机 · 无差别去杠杆
    """
    hs = px["510300"].ffill()
    cy = px["159915"].ffill()
    dv = px["510880"].ffill()

    ma200 = hs.rolling(200, min_periods=120).mean()
    below = hs < ma200
    dev = hs / ma200 - 1

    r20_cy = cy.pct_change(20)
    r20_dv = dv.pct_change(20)
    gmd = r20_cy - r20_dv

    vol = cy.pct_change().rolling(20).std() * np.sqrt(252)
    # 滚动 3 年分位（无未来函数：只用过去 750 个观测）
    vp = vol.rolling(750, min_periods=250).apply(lambda a: float((a[:-1] < a[-1]).mean()), raw=True)

    out = pd.Series(index=px.index, dtype=object)
    out[~np.isfinite(vol)] = None
    m = np.isfinite(vol) & np.isfinite(dev) & np.isfinite(gmd)
    for d in px.index[m]:
        b = bool(below.loc[d])
        v = float(vp.loc[d]) if np.isfinite(vp.loc[d]) else 0.5
        g = float(gmd.loc[d])
        dr = float(r20_dv.loc[d]) if np.isfinite(r20_dv.loc[d]) else 0.0
        if b and v >= 0.85 and dr < -0.05:
            out.loc[d] = "D"
        elif b and g < 0:
            out.loc[d] = "B"
        elif b:
            out.loc[d] = "Bp"
        elif v < 0.50:
            out.loc[d] = "A"
        else:
            out.loc[d] = "C"
    return out, dev, vp, gmd


REGIME_LABEL = {
    "A": "趋势上行·低波", "B": "趋势下行·防御有效", "Bp": "趋势下行·成长占优",
    "C": "震荡·中高波", "D": "危机·无差别去杠杆",
}


def regime_evidence(px, dev, vp, gmd, reg):
    """「为什么是这一档」的四条判据 —— 给看板做可查的归因，全部取最后一个数据日。

    判定树（顺序即优先级）：
        below = 沪深300 < MA200
        D  : below 且 创业板波动分位≥85% 且 红利20日 < -5%
        B  : below 且 成长−红利20日差 < 0
        B' : below（成长仍占优）
        A  : 未破 MA200 且 创业板波动分位 < 50%
        C  : 其余（未破 MA200 但波动偏高）
    """
    d = reg.dropna().index[-1]
    hs = px["510300"].ffill()
    dv = px["510880"].ffill()
    ma200h = hs.rolling(200, min_periods=120).mean()
    ma200d = dv.rolling(200, min_periods=120).mean()
    r20dv = dv.pct_change(20)
    below = bool(hs.loc[d] < ma200h.loc[d])
    v = float(vp.loc[d]) if np.isfinite(vp.loc[d]) else 0.5
    g = float(gmd.loc[d]) if np.isfinite(gmd.loc[d]) else 0.0
    dr = float(r20dv.loc[d]) if np.isfinite(r20dv.loc[d]) else 0.0
    code = str(reg.loc[d])

    items = [
        {"k": "沪深300 距 MA200", "v": round(float(dev.loc[d]) * 100, 2),
         "unit": "%", "sign": True, "th": "< 0 ⇒ 趋势向下", "hit": below,
         "w": "第一层：决定「上行 / 下行」"},
        {"k": "创业板 20 日波动分位", "v": round(v * 100, 1),
         "unit": "%", "sign": False, "th": "≥ 85% 且 红利 20 日 < −5% ⇒ D 危机",
         "hit": bool(v >= 0.85 and dr < -0.05),
         "w": "第二层：决定是否「无差别去杠杆」"},
        {"k": "成长 − 红利 20 日差", "v": round(g * 100, 2),
         "unit": "pp", "sign": True, "th": "< 0 ⇒ B（防御腿有效）；≥ 0 ⇒ B′",
         "hit": bool(g < 0), "w": "第三层：决定 B 还是 B′"},
        {"k": "红利 距 MA200", "v": round(float(dv.loc[d] / ma200d.loc[d] - 1) * 100, 2),
         "unit": "%", "sign": True, "th": "> 0 说明防御腿自己还在趋势上（B 档的佐证）",
         "hit": bool(dv.loc[d] > ma200d.loc[d]),
         "w": "佐证：B 档「防御有效」不是猜的"},
    ]
    return {"date": d.strftime("%Y-%m-%d"), "code": code,
            "label": REGIME_LABEL.get(code, ""), "items": items}


# ============================================================ 交易标准化
def std_trades(raw):
    """把 DataFrame / list 统一成 [{date, action, code, price, shares, reason, ret}]"""
    if raw is None:
        return []
    if isinstance(raw, pd.DataFrame):
        rows = raw.to_dict("records")
    elif isinstance(raw, list):
        rows = raw
    else:
        return []
    out = []
    for t in rows:
        d = str(t.get("date"))[:10]
        if not d or d == "None":
            continue
        act = str(t.get("action") or "")
        if act not in ("buy", "sell", "stop"):
            continue
        sh = t.get("shares", t.get("amount", 0))
        try:
            sh = float(sh)
        except Exception:
            sh = 0.0
        try:
            px_ = float(t.get("price") or 0)
        except Exception:
            px_ = 0.0
        try:
            rt = float(t.get("ret"))
        except Exception:
            rt = np.nan
        out.append({"date": d, "action": act, "code": str(t.get("code") or ""),
                    "price": round(px_, 4), "shares": int(sh),
                    "reason": str(t.get("reason") or ""),
                    "ret": None if not np.isfinite(rt) else round(rt * 100, 2)})
    out.sort(key=lambda x: x["date"])
    return out


def positions_from_trades(trades, px, names, end=END):
    """从调仓记录反推期末持仓。返回 [{code,name,cost,shares,last,pnl,entry_date,held_days,mv}]"""
    pos, meta = {}, {}
    for t in trades:
        if t["action"] == "buy":
            pos[t["code"]] = t["shares"]
            meta[t["code"]] = {"entry_date": t["date"], "cost": t["price"],
                               "name": t.get("name") or names.get(t["code"]) or t["code"]}
        elif t["action"] in ("sell", "stop"):
            pos.pop(t["code"], None)
            meta.pop(t["code"], None)
    cal = px.index
    out = []
    for c, sh in pos.items():
        if c not in px.columns or sh <= 0:
            continue
        s = px[c].dropna()
        if not len(s):
            continue
        last = float(s.iloc[-1])
        cost = float(meta[c]["cost"])
        ed = meta[c]["entry_date"]
        try:
            held = int(len(cal[cal >= pd.Timestamp(ed)])) - 1
        except Exception:
            held = 0
        out.append({
            "code": c, "name": meta[c].get("name") or names.get(c, c), "shares": int(sh),
            "cost": round(cost, 4), "last": round(last, 4),
            "pnl": round((last / cost - 1) * 100, 2) if cost > 0 else None,
            "pnl_amt": round((last - cost) * sh, 0),
            "mv": round(last * sh, 0),
            "entry_date": ed, "held_days": held,
        })
    return out


# ============================================================ 指标
def perf(eq, trades=None):
    eq = pd.Series(eq).dropna()
    if len(eq) < 3:
        return {}
    yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    ddser = eq / eq.cummax() - 1
    mdd = float(ddser.min())
    dr = eq.pct_change().dropna()
    vol = float(dr.std() * np.sqrt(252))
    sharpe = float(dr.mean() * 252 / vol) if vol > 0 else np.nan
    dn = dr[dr < 0]
    dvol = float(dn.std() * np.sqrt(252)) if len(dn) > 1 else np.nan
    sortino = float(dr.mean() * 252 / dvol) if dvol and dvol > 0 else np.nan
    calmar = float(cagr / abs(mdd)) if mdd < 0 else np.nan

    # 回撤持续期与恢复时间
    in_dd = ddser < -1e-9
    longest, cur, start = 0, 0, None
    recov = None
    peak_val = None
    for d, v in eq.items():
        if not in_dd.loc[d]:
            if start is not None and recov is None:
                recov = int((d - start).days)
            cur, start = 0, None
        else:
            if start is None:
                start = d
            cur += 1
            longest = max(longest, cur)
    # 未恢复的回撤
    cur_dd_days = 0
    if in_dd.iloc[-1]:
        last_peak = eq[~in_dd].index[-1] if (~in_dd).any() else eq.index[0]
        cur_dd_days = int((eq.index[-1] - last_peak).days)

    # 上行/下行捕获（vs 沪深300）——留接口，主流程里填
    up_cap = dn_cap = np.nan

    closed = [t for t in (trades or []) if t["action"] in ("sell", "stop")]
    rets = [t["ret"] / 100 for t in closed if t["ret"] is not None]
    win = float(np.mean([r > 0 for r in rets])) if rets else np.nan
    pl = (float(np.mean([r for r in rets if r > 0]) / abs(np.mean([r for r in rets if r < 0])))
          if rets and any(r > 0 for r in rets) and any(r < 0 for r in rets) else np.nan)

    return {
        "cagr": round(cagr * 100, 2), "mdd": round(mdd * 100, 2),
        "sharpe": round(sharpe, 2) if np.isfinite(sharpe) else None,
        "sortino": round(sortino, 2) if np.isfinite(sortino) else None,
        "calmar": round(calmar, 2) if np.isfinite(calmar) else None,
        "vol": round(vol * 100, 2),
        "n": len(closed),
        "win": round(win, 4) if np.isfinite(win) else None,
        "pl": round(pl, 2) if np.isfinite(pl) else None,
        "final": round(float(eq.iloc[-1] / CASH0), 2),
        "dd_days": int(longest), "recover_days": recov, "cur_dd_days": cur_dd_days,
    }


def window_ret(eq, start, end=END):
    s = pd.Series(eq).dropna()
    s = s.loc[start:end]
    if len(s) < 2:
        return None
    return round((s.iloc[-1] / s.iloc[0] - 1) * 100, 2)


def by_year(eq):
    s = pd.Series(eq).dropna()
    out = {}
    for y, g in s.groupby(s.index.year):
        if len(g) < 2:
            continue
        out[str(y)] = round((g.iloc[-1] / g.iloc[0] - 1) * 100, 2)
    return out


def by_regime(eq, reg):
    """按 regime 分组统计：日均收益(bp)、胜率、样本天数、累计贡献"""
    s = pd.Series(eq).dropna()
    r = s.pct_change()
    df = pd.DataFrame({"r": r, "reg": reg.reindex(s.index)}).dropna()
    out = {}
    for k, g in df.groupby("reg"):
        if len(g) < 10:
            continue
        out[str(k)] = {
            "n": int(len(g)),
            "mean_bp": round(float(g["r"].mean()) * 1e4, 1),
            "win": round(float((g["r"] > 0).mean()), 3),
            # 有波动日胜率：剔除空仓/持平的 0 收益日，才是「出手时的胜率」
            "win_act": (round(float((g["r"] > 0).sum() / (g["r"].abs() > 1e-9).sum()), 3)
                        if (g["r"].abs() > 1e-9).sum() else None),
            "flat": round(float((g["r"].abs() <= 1e-9).mean()), 3),
            "sum": round(float((1 + g["r"]).prod() - 1) * 100, 1),
        }
    return out


def drawdown_calendar(eq):
    """盈亏日历：{YYYY-MM: {DD: 日收益%}}"""
    s = pd.Series(eq).dropna()
    r = s.pct_change().dropna() * 100
    out = {}
    for d, v in r.items():
        ym = d.strftime("%Y-%m")
        out.setdefault(ym, {})[d.strftime("%d")] = round(float(v), 2)
    return out


# ============================================================ 五条策略
# 口径（2026-11-22 v2）：全部改用**执行时点价**，并保留预热段。
#   线C     14:45（线上 14:40 启动 / 14:49 出邮件 / 14:45—14:55 下单）
#   momo    14:30（平台 execute_time 14:30:00，分时版动量）
#   96863   14:50（平台 execute_time 14:50:00）
#   96864   14:30（平台 execute_time 14:30:00）
# 预热段：策略需要 N 日历史才有第一个信号；直接 loc[start:] 会丢掉开头 N 天的信号，
# 96864 就栽在这里（64.47% → 71.96%，差 7.5pp）。现在统一「先跑预热、再截统计窗」。

CALIBER_WARN = []          # 口径退化记录（干净目录跑时会出现），要写进 meta


def run_lineC(hist, px, names, codes, bmap):
    h45 = _px.hist_1445()
    # 381 池的 14:45 库（all_etf_1445.parquet）只有本机有；干净目录里只剩 21 只，
    # 覆盖率不足就退回日线收盘 —— 口径变了必须留痕，否则云端和本机会给出两个年化。
    if h45 and len(h45) < 100:
        CALIBER_WARN.append("线C 用收盘价兜底（缺 381 池 14:45 库，仅 %d 只）" % len(h45))
        print("[口径] 线C 的 14:45 库只有 %d 只，退回收盘价" % len(h45))
        h45 = None
    use = {c: h45[c] for c in codes if c in h45} if h45 else \
          {c: hist[c] for c in codes if c in hist}
    m = bt.build_matrices(use, start="2020-06-01", end=END)
    r = bm.run(m, bmap, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True)
    eq = pd.Series(r["equity"]).dropna()
    eq = eq.loc["2021-01-04":]
    tr = std_trades(r["trades"])
    for t in tr:
        if t["action"] == "sell" and not t["reason"]:
            t["reason"] = "四道闸门之一"
    return eq, tr, "2021-01-04"


def run_momo(px, names):
    p = _px.wide("1430")
    if p is None or (hasattr(p, "columns") and m6.CODES[0] not in p.columns):
        # 干净目录（GitHub Actions）没有 14:30 分时库时用日线收盘兜底。
        # 口径从「14:30 执行价」退化成「收盘价」，已知 −1.9pp 级差异 ——
        # 写进 caliber_warn，不许假装没发生。
        p = px
        CALIBER_WARN.append("momo 模拟用收盘价兜底（缺 14:30 分时库）")
        print("[口径] momo 缺 1430 分时库，用收盘价兜底（−1.9pp 级差异）")
    pm = p[m6.CODES]
    V1, V2 = m6.build_signals(pm, 20, 26)
    i0 = int(np.where(pm.index >= "2018-01-01")[0][0])
    r = m6.run(pm.iloc[i0:], V1[i0:], V2[i0:])
    eq = pd.Series(r["equity"]).dropna()
    tr = std_trades(r["trades"])
    for t in tr:
        t.setdefault("reason", "")
    return eq, tr, "2018-01-01"


def run_band(px, names):
    w = _px.wide("1450")
    if w is None or (hasattr(w, "columns") and CONSUME[0] not in w.columns):
        w = px
        CALIBER_WARN.append("96863 模拟用收盘价兜底（缺 14:50 分时库）")
        print("[口径] 96863 缺 1450 分时库，用收盘价兜底")
    p = w[CONSUME]
    r = pb.run_band(p.loc["2019-06-03":END])       # 19 日预热
    eq = pd.Series(r["equity"]).dropna().loc["2020-01-01":]
    tr = std_trades(r["trades"])
    return eq, tr, "2020-01-01"


def run_bank(px, names):
    p = _px.pair("1430")
    r = p5.run(p.loc["2024-06-28":END])            # 10 日预热 + 平台起始日之前先跑
    eq = pd.Series(r["equity"]).dropna().loc["2024-10-01":]
    tr = std_trades(r["trades"])
    # ★ _p5_bank 内部用 "main"/"bank" 代号，必须映射成真实代码，
    #   否则 positions_from_trades 找不到价格、持仓恒为空。
    MAP = {"main": ("159552", "中证2000增强"), "bank": ("515020", "银行ETF华夏"),
           "159552": ("159552", "中证2000增强"), "515020": ("515020", "银行ETF华夏")}
    for t in tr:
        if t["code"] in MAP:
            t["code"], t["name"] = MAP[t["code"]]
    return eq, tr, "2024-10-01"


# ============================================================ 成本抗性
# 不再手写：一律从 data/_robust.json 读（由 _robust.py 用执行时点价重算）。
# 手写的数字会过期，过期就是口径错误。
def _load_cost():
    p = os.path.join(BASE, "data", "_robust.json")
    fallback = {
        "lineC": {"zero": None, "now": None, "t3": None, "tag": "万2+0.1%"},
        "momo96865": {"zero": None, "now": None, "t3": None, "tag": "万1+0.1%"},
        "band96863": {"zero": None, "now": None, "t3": None, "tag": "万2.5+0.1%"},
        "bank96864": {"zero": None, "now": None, "t3": None, "tag": "万0.5+0.1%"},
    }
    if not os.path.exists(p):
        return fallback
    try:
        d = json.load(open(p, encoding="utf-8"))
        out = {}
        for k, v in d.items():
            c = v.get("cost") or {}
            out[k] = {"zero": c.get("zero"), "now": c.get("now"),
                      "t3": c.get("t3"), "h5": c.get("h5"), "tag": ""}
        for k in fallback:
            if k not in out or not out[k]["zero"] or not out[k]["t3"]:
                out[k] = fallback[k]
        return out
    except Exception:
        return fallback


COST_SENS = _load_cost()


# ============================================================ 评分（100 分制）
def _lin(x, pts):
    """分段线性打分：pts = [(阈值, 分), ...] 从低到高"""
    if x is None or not np.isfinite(x):
        return 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return float(ys[i - 1] + t * (ys[i] - ys[i - 1]))
    return float(ys[-1])


def score_strategy(s, reg_rank, m_rank, near_rank, cost_key, years=0.0, ntr=0, nreg=0):
    """九维 100 分制。每一项都可复算，口径写在返回值里。

    权重设计（为什么这么分）：
      当前环境适配 18 —— 用户的核心问题就是「现在这个环境该信谁」，权重最高
      本月表现     14 —— 用户明确要求把「本月模拟收益」作为重要指标
      风险调整     13 —— 专业评价的通用基准（夏普/索提诺）
      回撤控制     10 —— 亏损承受力，含「当前是否仍在回撤中」
      稳定性        9 —— 年度胜率，防「一年暴赚、三年回吐」
      近期动量      7 —— 捕捉「正在失效/正在转好」，权重不高以免追涨杀跌
      成本抗性      9 —— 3tick 后的保留率，决定能不能真的赚到
      可执行性      8 —— 数据/时点/容量/溢价，做不到就白搭
      样本充分度   12 —— 年数 + 笔数 + 跨 regime 数，专治「短样本漂亮」
    """
    items = []

    # 1 当前环境适配 18（reg_rank = 该 regime 下「日均收益+胜率」的综合分位，1=最好）
    v = 18 * reg_rank
    items.append({"k": "当前环境适配", "max": 18, "v": round(v, 1),
                  "n": "当前 regime 下日均收益+胜率综合分位 %.0f%%" % (reg_rank * 100)})

    # 2 本月表现 14（11 月收益横向分位）
    v = 14 * m_rank
    items.append({"k": "本月表现", "max": 14, "v": round(v, 1),
                  "n": "11 月收益横向分位 %.0f%%" % (m_rank * 100)})

    # 3 风险调整 13（夏普为主，索提诺为辅）
    sh = s.get("sharpe")
    so = s.get("sortino")
    v_sh = _lin(sh, [(0, 0), (0.5, 3.5), (1.0, 7), (1.5, 10), (2.0, 11.8), (2.5, 13)])
    v_so = _lin(so, [(0.5, 0), (1.0, 0.6), (1.5, 1.2), (2.0, 1.5)])
    v = min(13.0, v_sh * 0.88 + v_so)
    items.append({"k": "风险调整", "max": 13, "v": round(v, 1),
                  "n": "夏普 %s ｜ 索提诺 %s" % (s.get("sharpe"), s.get("sortino"))})

    # 4 回撤控制 10
    v = _lin(-abs(s.get("mdd") or 45), [(-45, 0), (-35, 1.5), (-30, 3), (-20, 5.8),
                                        (-15, 8), (-10, 9.2), (-5, 10)])
    if s.get("cur_dd_days"):
        v = max(0.0, v - min(1.6, s["cur_dd_days"] / 60))   # 未恢复回撤扣分
    items.append({"k": "回撤控制", "max": 10, "v": round(v, 1),
                  "n": "最大回撤 %.1f%%%s" % (s.get("mdd") or 0,
                                             "，当前仍在回撤中 %d 天" % s["cur_dd_days"]
                                             if s.get("cur_dd_days") else "")})

    # 5 稳定性 9（年度胜率）
    yw = s.get("_year_win")
    v = _lin(yw, [(0, 0), (0.5, 2.5), (0.7, 5.4), (0.85, 7.7), (1.0, 9)])
    items.append({"k": "稳定性", "max": 9, "v": round(v, 1),
                  "n": "年度胜率 %s" % ("—" if yw is None else "%.0f%%" % (yw * 100))})

    # 6 近期动量 7
    v = 7 * near_rank
    items.append({"k": "近期动量", "max": 7, "v": round(v, 1),
                  "n": "近 20 日收益横向分位 %.0f%%" % (near_rank * 100)})

    # 7 成本抗性 9（3tick / 零成本）
    cs = COST_SENS.get(cost_key, {})
    keep = (cs.get("t3", 0) / cs["zero"]) if cs.get("zero") else 0
    v = _lin(keep, [(0, 0), (0.2, 1.8), (0.4, 4.5), (0.6, 6.8), (0.8, 8.6), (1.0, 9)])
    items.append({"k": "成本抗性", "max": 9, "v": round(v, 1),
                  "n": "3tick 后保留 %.0f%%（%.1f%% vs 零成本 %.1f%%）"
                       % (keep * 100, cs.get("t3", 0), cs.get("zero", 0))})

    # 8 可执行性 8
    ex = s.get("_exec") or 0
    v = 8 * (ex / 10.0)
    items.append({"k": "可执行性", "max": 8, "v": round(v, 1),
                  "n": s.get("_exec_note") or ""})

    # 9 样本充分度 12（年数 6 + 笔数 3 + 跨 regime 3）
    v_y = _lin(years, [(0, 0), (1, 0.5), (3, 3), (5, 4.5), (8, 6)])
    v_n = _lin(ntr, [(0, 0), (20, 0.5), (50, 1.5), (100, 2.6), (300, 3)])
    v_r = _lin(nreg, [(1, 0), (2, 1), (3, 2), (4, 2.6), (5, 3)])
    v = v_y + v_n + v_r
    items.append({"k": "样本充分度", "max": 12, "v": round(v, 1),
                  "n": "%.1f 年 ｜ %d 笔平仓 ｜ 跨 %d 个 regime" % (years, ntr, nreg)})

    total = sum(x["v"] for x in items)
    return {"total": round(total, 1), "max": 100, "items": items}


# ============================================================ 主流程
def build():
    hist, px, names, fixed, codes, bmap = load_all()
    reg, dev, vp, gmd = regime_series(px)
    cur_reg = str(reg.dropna().iloc[-1])
    print("数据 %d 行 × %d 列 ｜ 修跳变 %d 根 ｜ 当前 regime = %s %s"
          % (len(px), px.shape[1], fixed, cur_reg, REGIME_LABEL.get(cur_reg, "")))

    pack = {}
    for key, fn in [("lineC", lambda: run_lineC(hist, px, names, codes, bmap)),
                    ("momo96865", lambda: run_momo(px, names)),
                    ("band96863", lambda: run_band(px, names)),
                    ("bank96864", lambda: run_bank(px, names))]:
        eq, tr, w0 = fn()
        tr_win = [t for t in tr if str(t.get("date", ""))[:10] >= w0]
        s = perf(eq, tr_win)
        s["_year_win"] = (float(np.mean([v > 0 for v in by_year(eq).values()]))
                          if by_year(eq) else None)
        pack[key] = {"eq": eq, "trades": tr, "metrics": s}
        print("  %-11s 年化 %+7.2f%% ｜ 回撤 %7.2f%% ｜ 夏普 %5s ｜ 平仓 %3d ｜ 本月 %s%%"
              % (key, s["cagr"], s["mdd"], s["sharpe"], s["n"],
                 window_ret(eq, "2026-10-31")))

    # ---------- 横向排名（只在四条本地策略间做）----------
    regstats = {k: by_regime(v["eq"], reg) for k, v in pack.items()}
    cur_bp = {}
    cur_win = {}
    for k, rs in regstats.items():
        r = rs.get(cur_reg)
        cur_bp[k] = r["mean_bp"] if r else -99
        cur_win[k] = r["win"] if r else 0
    ks = list(pack.keys())
    rk_bp = pd.Series(cur_bp).rank(ascending=True, pct=True)       # 越大越好
    rk_win = pd.Series(cur_win).rank(ascending=True, pct=True)
    reg_rank = {k: float(0.6 * rk_bp[k] + 0.4 * rk_win[k]) for k in ks}

    nov = {k: (window_ret(v["eq"], "2026-10-31") or -99) for k, v in pack.items()}
    m_rank = pd.Series(nov).rank(ascending=True, pct=True).to_dict()

    near = {k: (window_ret(v["eq"], "2026-10-21") or -99) for k, v in pack.items()}
    near_rank = pd.Series(near).rank(ascending=True, pct=True).to_dict()

    # ---------- 可执行性（数据/时点/容量/溢价，0-10）----------
    # 🔴 2026-11-22 改成「算出来的」：四项各 2 分，数据来自 _exec_audit.py 实测。
    # 旧版把手写备注当依据，其中「无 14:30 分时价」已经过期 —— 我们 11-22 就建好了
    # intraday_1430 分时库，四个池子覆盖率都是 100%。过期的依据比没有依据更糟。
    EXEC = {
        "lineC": (8.0, "数据 2/2（14:30 全覆盖）｜时点 2/2（14:30→14:31）｜容量 2/2（日均 30.6 亿）｜溢价 2/2"),
        "momo96865": (6.0, "数据 2/2（14:30 全覆盖）｜时点 2/2｜容量 1/2（最小 0.25 亿）｜溢价 1/2（2/12 >5%）⇒ 卡的是成本不是数据"),
        "band96863": (6.0, "数据 2/2｜时点 2/2（14:50）｜容量 1/2（最小 0.11 亿，最薄）｜溢价 1/2（2/6 >5%）"),
        "bank96864": (8.0, "数据 2/2｜时点 2/2（14:55）｜容量 2/2（1.75 亿）｜溢价 2/2 ⇒ 执行没问题，卡在样本"),
    }
    # 四项明细，给弹窗用（不要再让用户看一句没有依据的备注）
    EXEC_PARTS = {
        "lineC": [("数据", 2), ("时点", 2), ("容量", 2), ("溢价", 2)],
        "momo96865": [("数据", 2), ("时点", 2), ("容量", 1), ("溢价", 1)],
        "band96863": [("数据", 2), ("时点", 2), ("容量", 1), ("溢价", 1)],
        "bank96864": [("数据", 2), ("时点", 2), ("容量", 2), ("溢价", 2)],
    }
    for k in ks:
        ex, note = EXEC[k]
        pack[k]["metrics"]["_exec"] = ex
        pack[k]["metrics"]["_exec_note"] = note
        pack[k]["metrics"]["_exec_parts"] = EXEC_PARTS[k]

    # ---------- 评分 ----------
    # 年数从净值序列实测，不再手写（手写会在换窗口后悄悄过期）
    YEARS = {k: round((pack[k]["eq"].index[-1] - pack[k]["eq"].index[0]).days / 365.25, 1)
             for k in ks}

    # ---------- 次方式明细：最大连续亏损 / 月均交易 / 最大回撤区间 ----------
    # 这三项之前页面没有，用户拿次方策略页来对比，缺的就是这些。
    for k in ks:
        tr = pack[k].get("trades") or []
        cur = mx = 0
        for t in tr:
            # 只看平仓（sell）那一笔；buy 的 ret 是 None，不能拿来重置连亏计数
            if str(t.get("action")) != "sell":
                continue
            if (t.get("ret") or 0) < 0:
                cur += 1
                mx = max(mx, cur)
            else:
                cur = 0
        m = pack[k]["metrics"]
        m["max_consec_loss"] = mx
        nsell = sum(1 for t in tr if str(t.get("action")) == "sell")
        m["trades_per_month"] = round(nsell / max(1.0, YEARS.get(k, 1) * 12), 1)
        eq = pack[k]["eq"]
        try:
            ddser = eq / eq.cummax() - 1
            trough = ddser.idxmin()
            peak = eq.loc[:trough].idxmax()
            m["mdd_peak"] = str(peak)[:10]
            m["mdd_trough"] = str(trough)[:10]
            m["mdd"] = round(float(ddser.min()) * 100, 2)
        except Exception:
            pass

    NREG = {"lineC": 5, "momo96865": 5, "band96863": 5, "bank96864": 3}
    for k in ks:
        pack[k]["score"] = score_strategy(
            pack[k]["metrics"], reg_rank[k], m_rank[k], near_rank[k], k,
            years=YEARS.get(k, 0),
            ntr=pack[k]["metrics"].get("n") or 0,
            nreg=NREG.get(k, 0))

    # 把「环境适配」那一维的说明换成原始数据：当前档日均 bp + 横截面名次 + 出手日胜率
    for k in ks:
        r = regstats[k].get(cur_reg) or {}
        rank = 1 + sum(1 for j in ks if j != k and cur_bp.get(j, -99) > cur_bp.get(k, -99))
        for it in pack[k]["score"]["items"]:
            if it["k"] == "当前环境适配":
                it["n"] = ("%s 档日均 %+.0f bp（%d 条里第 %d）｜ 出手日胜率 %.0f%%"
                           % (cur_reg, r.get("mean_bp", 0), len(ks), rank,
                              (r.get("win_act") or 0) * 100))

    out = []
    for k in ks:
        v = pack[k]
        eq = v["eq"]
        s = v["metrics"]
        tr = v["trades"]
        fz = FREEZE.get(k)
        # 模拟段：参数冻结日之后重算净值（归一化到 100），这段才是「样本外」
        sim = None
        if fz:
            sim_eq = eq.loc[fz:]
            if len(sim_eq) >= 2:
                sim = {
                    "start": fz,
                    "days": int(len(sim_eq)),
                    "ret": round(float(sim_eq.iloc[-1] / sim_eq.iloc[0] - 1) * 100, 2),
                    "trades": [t for t in tr if t["date"] >= fz],
                    "equity": [[d.strftime("%Y-%m-%d"), round(float(x / sim_eq.iloc[0] * 100), 2)]
                               for d, x in sim_eq.items()],
                }
        # 今日（数据日）当天做了什么
        tod = [t for t in tr if t["date"] == END]
        hold_now = positions_from_trades(tr, px, names)
        today = {"date": END, "action": "none", "code": "", "name": "", "reason": ""}
        if tod:
            t = tod[-1]
            today.update({"action": t["action"], "code": t["code"],
                          "name": names.get(t["code"], t["code"]),
                          "reason": t["reason"] or "规则触发"})
        elif hold_now:
            h = hold_now[0]
            today.update({"action": "hold", "code": h["code"], "name": h["name"],
                          "reason": "持有第 %d 天，未触发换仓/卖出条件" % h["held_days"]})
        else:
            today.update({"action": "empty", "reason": "空仓：无合格标的"})

        out.append({
            "id": k,
            "today": today,
            "metrics": {x: s.get(x) for x in
                        ("cagr", "mdd", "sharpe", "sortino", "calmar", "vol", "n",
                         "win", "pl", "final", "dd_days", "recover_days", "cur_dd_days",
                         # 次方式明细：最大回撤区间 / 最大连续亏损 / 月均交易
                         "mdd_peak", "mdd_trough", "max_consec_loss", "trades_per_month")},
            "score": v["score"],
            "regime_here": regstats[k].get(cur_reg),
            "regime_all": regstats[k],
            "by_year": by_year(eq),
            "ret": {
                "mtd": window_ret(eq, "2026-10-31"),
                "wtd": window_ret(eq, "2026-11-13"),
                "m1": window_ret(eq, "2026-10-21"),
                "m3": window_ret(eq, "2026-08-20"),
                "ytd": window_ret(eq, "2025-12-31"),
                "all": round(float(eq.iloc[-1] / eq.iloc[0] - 1) * 100, 2),
            },
            "equity": [[d.strftime("%Y-%m-%d"), round(float(x), 2)] for d, x in eq.items()],
            "trades": tr[-14:],
            "n_trades": len(tr),
            "holdings": positions_from_trades(tr, px, names),
            "calendar": drawdown_calendar(eq.loc["2026-01-01":]),
            "sim": sim,
            "freeze": FREEZE.get(k),
        })

    meta = {
        "data_date": END, "regime": cur_reg,
        "regime_label": REGIME_LABEL.get(cur_reg, ""),
        "regime_note": "沪深300 %+.2f%% vs MA200 ｜ 创业板波动分位 %.0f%% ｜ 成长−红利 20日 %+.1fpp"
                       % (dev.dropna().iloc[-1] * 100,
                          (vp.dropna().iloc[-1] if np.isfinite(vp.dropna().iloc[-1]) else 0) * 100,
                          gmd.dropna().iloc[-1] * 100),
        "regime_days": {str(k): int(v) for k, v in reg.value_counts().items()},
        "regime_hist": {str(d): str(g) for d, g in reg.dropna().tail(750).items()},
        "regime_evidence": regime_evidence(px, dev, vp, gmd, reg),
        "caliber": {
            "lineC": {"time": "14:45", "src": "data/all_etf_1445.parquet（SVIP 分时，qfq）",
                      "note": "线上 14:40 启动 / 14:49 出邮件 / 14:45—14:55 下单"},
            "momo96865": {"time": "14:30", "src": "data/intraday_1430.parquet（SVIP 分时，qfq）",
                          "note": "平台 execute_time 14:30:00，分时版动量"},
            "band96863": {"time": "14:50", "src": "data/intraday_1450.parquet（SVIP 分时，qfq）",
                          "note": "平台 execute_time 14:50:00"},
            "bank96864": {"time": "14:30", "src": "data/intraday_1430.parquet（SVIP 分时，qfq）",
                          "note": "平台 execute_time 14:30:00"},
        },
        "caliber_warn": CALIBER_WARN,
        "built": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
    }
    return {"meta": meta, "strategies": out}


if __name__ == "__main__":
    r = build()
    p = os.path.join(BASE, "data", "_sim_out.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False)
    print("\n写出 %s（%.1f MB）" % (p, os.path.getsize(p) / 1024 / 1024))
    print("\n%-12s %6s  %-14s %8s %8s %8s %8s" %
          ("策略", "总分", "当前环境", "本月", "近20日", "年化", "回撤"))
    for s in sorted(r["strategies"], key=lambda x: -x["score"]["total"]):
        print("%-12s %6.1f  %-14s %+7.2f%% %+7.2f%% %+7.2f%% %7.2f%%"
              % (s["id"], s["score"]["total"],
                 REGIME_LABEL.get(r["meta"]["regime"], ""),
                 s["ret"]["mtd"] or 0, s["ret"]["m1"] or 0,
                 s["metrics"]["cagr"] or 0, s["metrics"]["mdd"] or 0))

