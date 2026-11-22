# -*- coding: utf-8 -*-
"""_build_live.py —— 生成手机端实时页 live/index.html

为什么单独做一页
----------------
主看板 600 KB、信息密度极高，手机上不好看；它是「坐在电脑前做决策」的界面。
这一页是「出门在外只想看一眼」的版本：一屏看完持仓与今日动作。

与主看台的关系（v7 起的联动）
------------------------------
1. **判定同源**：两页都内联 hub/live_core.js 的 LC.judge() / LC.crosscheck()，
   所以「距止损多少、是否已破、限价还成不成立」两边算出来必然一致。
2. **数据同源**：都从 hub.json 抽，构建于同一次 refresh，标同一个数据日。
3. **双向可达**：主看台实时条与策略弹窗有「手机看 →」；本页每张卡可展开看
   「今日指令 / 九维强弱项 / 下一步触发」，并给出回主看台的说明。

行情用东方财富 push2（带 Access-Control-Allow-Origin: *），浏览器可直连
⇒ 纯静态页，不需要任何后端，手机点开就能看。
默认脱敏：不含份额、不含金额、不含总资产（成本价/止损价保留，否则算不出距止损）。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "live")

SHOW_AMOUNT = os.environ.get("LIVE_SHOW_AMOUNT", "0") == "1"


def caliber_warn():
    """读 _sim_out.json 里的口径退化记录（干净目录跑时会非空）。"""
    p = os.path.join(ROOT, "etf_dip_signal", "data", "_sim_out.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        return (d.get("meta") or {}).get("caliber_warn") or []
    except Exception:
        return []


def state_url():
    """云端 state.json 地址：环境变量 > hub/state_url.txt 一行 > 空（不请求）。"""
    u = (os.environ.get("LIVE_STATE_URL") or "").strip()
    if u:
        return u
    p = os.path.join(HERE, "state_url.txt")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return ""


# ---------------------------------------------------------------------------
# 视觉统一层（v2）
# ---------------------------------------------------------------------------
# 为什么在构建期改、而不是一条条改模板：
#   页面里大量字号/颜色是写在 JS 拼接字符串里的**行内样式**，
#   CSS 覆盖不到；模板里还有 200+ 处 `font-size:9px` 这种碎值。
#   构建期做一次「单通道重映射」，能保证整页只有一套字号阶梯、一套强调色，
#   而且改完可以整页回退（改这张表就行）。
FS_BUMP = {
    7: 8.5, 7.5: 8.5, 8: 9.5, 8.5: 10, 9: 10.5, 9.5: 11, 10: 11.5,
    10.5: 12, 11: 12, 11.5: 12.5, 12: 13, 12.5: 13.5, 13: 14,
    14: 15, 15: 16, 16: 17, 18: 19, 20: 21, 21: 22, 22: 23, 23: 24, 26: 28,
}
COLOR_MAP = {
    # 强调色只留一个（靛蓝），紫/亮蓝/天蓝全部收进来
    "#6d28d9": "#4f46e5", "#7c3aed": "#4f46e5",
    "#1d4ed8": "#4338ca", "#2563eb": "#4f46e5", "#0ea5e9": "#4f46e5",
    # 提示色统一到 amber-700
    "#b45309": "#b54708",
}

V2_CSS = """
/* ---------- v2 视觉层：一套字号阶梯 + 一个强调色 + 一致的圆角留白 ---------- */
body{-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;
  font-family:"PingFang SC","HarmonyOS Sans SC","Microsoft YaHei",-apple-system,
    BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:.1px}
.hd{background:#0f172a;border-bottom:1px solid rgba(255,255,255,.05)}
.hd h1{letter-spacing:.2px}
.wrap{padding:14px 14px 30px}
.hero,.wx,.chn,.mx,.acc,.card{border-radius:14px;
  box-shadow:0 1px 2px rgba(16,24,40,.05)}
.grp{letter-spacing:1.1px;margin:18px 2px 9px}
.grp::after{background:#e9eef5}
.navx{padding:8px 14px}
.navx a{padding:5px 11px}
/* 头部那行：刷新按钮 + 云端状态，必须一行放下；状态太长就省略号，不许换行错位 */
.hd .hubnav{flex-wrap:nowrap}
.hd .hubnav .hint{flex:1 1 auto;min-width:0;text-align:right;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.sheet{border-radius:18px 18px 0 0}
.sheet h4{margin:16px 0 9px}
/* AI 解读 */
.ain{background:linear-gradient(180deg,#f7f8ff,#fff 60%);border:1px solid #e5e8f5;
  border-radius:14px;padding:13px 14px;margin-bottom:12px;
  box-shadow:0 1px 2px rgba(16,24,40,.05)}
.ain-h{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:750;color:#312e81}
.ain-h .tag{font-size:9px;padding:1px 5px;border-radius:4px;background:#eef0fe;
  color:#4338ca;font-weight:700}
.ain-h .rt{margin-left:auto;font-size:9.5px;color:#94a3b8;font-weight:600}
.ain ul{margin:9px 0 0;padding-left:15px;color:#334155}
.ain li{font-size:11.5px;line-height:1.85;margin:3px 0}
.ain-n{font-size:9.5px;color:#94a3b8;margin-top:8px;padding-top:7px;
  border-top:1px dashed #e8eaf6;line-height:1.7}
"""


V3_CSS = """
/* ---------- v3 设计系统 ----------
   目标：像一份「机构研报」而不是「行情软件」。
   手法：白底顶栏 + 一个强调色 + 极细描边 + 靠留白分层，不用重阴影和大色块。 */
body{background:#f6f7f9;color:#0f172a}

/* 顶栏：白底、细线、品牌色小竖条。原来是深蓝渐变，和卡片不是一套材质 */
.hd{background:#fff;color:#0f172a;border-bottom:1px solid #e9edf3;
  box-shadow:0 1px 0 rgba(16,24,40,.02)}
.hd h1{font-size:17px;font-weight:750;color:#0f172a;letter-spacing:-.2px}
.hd h1::before{content:'';display:inline-block;width:6px;height:17px;border-radius:3px;
  background:#4f46e5;margin-right:9px;vertical-align:-2px}
.hd .live{color:#98a2b3;font-size:10.5px}
.hd .dot{background:#cbd5e1;box-shadow:none}
.hd .dot.on{background:#12b76a;box-shadow:0 0 0 3px rgba(18,183,106,.16)}
.hd .row{gap:6px;margin-top:10px;flex-wrap:nowrap;overflow-x:auto;
  scrollbar-width:none;-ms-overflow-style:none;
  -webkit-mask-image:linear-gradient(90deg,#000 90%,transparent);
  mask-image:linear-gradient(90deg,#000 90%,transparent)}
.hd .row::-webkit-scrollbar{display:none}
.hd .pill{background:#fff;border:1px solid #e9edf3;color:#667085;
  font-size:10.5px;padding:3px 8px;border-radius:8px}
.hd .pill b{color:#0f172a;font-weight:750}
.hd .sub{color:#98a2b3;font-size:10px;margin-top:8px}
.hd .chk{margin-top:8px;font-size:10px;padding:0;border:0;background:none;color:#667085;
  line-height:1.7}
.hd .chk.ok{background:none;border:0;color:#067647}
.hd .chk.bad{background:none;border:0;color:#b42318}
.hd .hubnav{margin-top:11px;gap:10px}
/* 刷新做成「幽灵按钮」：白底细边，别用黑块 —— 它不是主操作，主操作是首屏那张卡 */
.hd .hubnav .rbtn{background:#fff;border:1px solid #e9edf3;color:#344054;
  border-radius:9px;padding:5px 11px;font-size:11.5px;font-weight:650;
  box-shadow:0 1px 1px rgba(16,24,40,.03)}
.hd .hubnav .rbtn:active{background:#f8fafc}
.hd .hubnav .hint{color:#98a2b3;font-size:9.5px;letter-spacing:0}

/* 导航：胶囊 → 下划线标签，当前项一条靛蓝线 */
.navx{background:rgba(255,255,255,.95);border-bottom:1px solid #e9edf3;
  padding:0 10px;gap:0;
  -webkit-mask-image:linear-gradient(90deg,#000 93%,transparent);
  mask-image:linear-gradient(90deg,#000 93%,transparent)}
.navx a{background:none!important;border:0!important;border-radius:0!important;
  padding:11px 11px 9px!important;font-size:12px!important;color:#667085!important;
  border-bottom:2px solid transparent!important;font-weight:650}
.navx a.on{color:#0f172a!important;border-bottom-color:#4f46e5!important;font-weight:750!important}

/* 首屏英雄卡：白底 + 左侧 4px 色条。卖=红、买=靛蓝、不动=灰 */
.hero{background:#fff!important;border:1px solid #e9edf3!important;
  border-left:4px solid #98a2b3!important;border-radius:16px!important;
  padding:16px!important;box-shadow:0 1px 2px rgba(16,24,40,.04)!important}
.hero.must{border-left-color:#d92d20!important}
.hero.buy{border-left-color:#4f46e5!important}
.hero-k{color:#98a2b3!important;font-size:10.5px!important;letter-spacing:.5px}
.hero-t{color:#0f172a!important;font-size:20px!important;letter-spacing:-.4px;
  margin:6px 0 8px!important}
.hero.buy .hero-t,.hero.none .hero-t{color:#0f172a!important}
.hero-p{color:#344054!important;font-size:13px!important}
.hero-w{color:#667085!important;font-size:10.5px!important}
.hero summary{color:#4f46e5!important}
.hero .an{color:#98a2b3!important}
.hero .arow{border-bottom-color:#f2f4f7!important}

/* 卡片：描边 + 极淡阴影；标题 14 / 数值 26，层级靠字号不靠色块 */
.card,.wx,.chn,.mx,.acc{background:#fff;border:1px solid #e9edf3;
  border-radius:16px;box-shadow:0 1px 2px rgba(16,24,40,.03)}
.card{padding:15px 16px;margin-bottom:12px}
.card .st{font-size:14px;font-weight:750;color:#0f172a;letter-spacing:-.1px}
.card .top{gap:7px;margin-bottom:10px}
.chip{border-radius:999px;font-size:10.5px;padding:3px 9px;border:1px solid transparent}
.chip.hold{background:#eef2ff;color:#4338ca;border-color:#e0e7ff}
.chip.sell{background:#fef3f2;color:#b42318;border-color:#fee4e2}
.chip.buy{background:#eef2ff;color:#4338ca;border-color:#e0e7ff}
.chip.empty{background:#f2f4f7;color:#667085;border-color:#e9edf3}
.badge{border-radius:999px;font-size:9.5px;padding:2px 8px;background:#f2f4f7;
  color:#667085;border:1px solid #e9edf3;font-weight:650}
.badge.live{background:#ecfdf3;color:#027a48;border-color:#d1fadf}
.badge.fb{background:#fffaeb;color:#b54708;border-color:#fef0c7}
.price .nm{font-size:11px;color:#98a2b3}
.price .p{font-size:26px;font-weight:750;letter-spacing:-.6px}
.price .c{font-size:12px;font-weight:700}
.grid{gap:8px;margin-top:11px}
.grid>div{background:#fafbfc;border:1px solid #f2f4f7;border-radius:10px;padding:8px 10px}
.grid .k{font-size:10px;color:#98a2b3}
.grid .v{font-size:14px;font-weight:750}

/* 分组标题：小字 + 细线，不再整行重横线 */
.grp{margin:20px 2px 9px;font-size:10.5px;color:#98a2b3;letter-spacing:1.2px}
.grp::after{background:#f0f2f6}

/* 弹层与页脚 */
.sheet{background:#fff;border-radius:20px 20px 0 0;box-shadow:0 -8px 32px rgba(16,24,40,.14)}
.sheet h4{font-size:11.5px;color:#344054}
.sheet .g8>div,.sheet .kv div{background:#fafbfc;border:1px solid #f2f4f7;border-radius:10px}
.sheet .g8 .k,.sheet .kv .k{color:#98a2b3}
.sheet .g8 .v,.sheet .kv .v{color:#0f172a}
.ft{color:#98a2b3;font-size:10px}
.ft b{color:#667085}
"""


def restyle(html):
    """整页字号/色彩重映射 + 追加 v2 样式层。只动样式，不碰文本。"""
    import re as _re

    def _fs(m):
        v = float(m.group(1))
        nv = FS_BUMP.get(int(v) if v == int(v) else v, v)
        return "font-size:%gpx" % nv

    html = _re.sub(r"font-size:\s*([\d.]+)px", _fs, html)
    for old, new in COLOR_MAP.items():
        html = html.replace(old, new)
        html = html.replace(old.upper(), new)
    if "</style>" in html:
        html = html.replace("</style>", V2_CSS + V3_CSS + "</style>", 1)
    return html

# ---------------------------------------------------------------------------
# 云服务（applicationId wbapp_0IGUTa3OCaUcqBq3LO8nCh）
# 下面三个值来自 workbuddy_cloud_service 的 publicConfig，可以进前端 ——
# publishableKey 只标识「哪个应用」，本身不带权限，服务端还会做 Origin 精确匹配。
# endpoint 必须与发布域名一致，否则数据面会拒绝（这也是不能换域名重发布的原因）。
# ---------------------------------------------------------------------------
CLOUD = {
    "endpoint": os.environ.get("LIVE_CLOUD_ENDPOINT",
                               "https://etf-strategy-live.app.workbuddy.host"),
    "oauthRelayBaseUrl": "https://www.workbuddy.cn/v2/as/genie-baas/oauth",
    "publishableKey": os.environ.get(
        "LIVE_CLOUD_KEY", "wbpk_0IGUTa3OCaUcqBq3LO8nCh_Hr6PbpGFTOR1UAnttE3rYi9wKl8nxzwI"),
}


def load_kline_map(codes, n=90):
    """把预测要用到的收盘价序列在构建时算好，内嵌进页面。

    为什么不用浏览器联网取：2026-11-22 实测三家全都不稳定 ——
      腾讯 ifzq 对 https 发布域直接不放行；
      次方 hist_em 的 CORS 时有时无（同一个请求两次结果不同）；
      东财 push2his 单次 146ms 很快，但 20 只并发跑下来只成功 4 只（限流）。
    预测只需要收盘价（斜率、涨幅、乖离全用 close），80 个点 × 20 只约 10KB，
    内嵌进页面最可靠：0 网络、0 延迟、不会因为对方限流而算出错结论。
    实时价仍从腾讯 qt 取，用来替换最后一根 —— 决定当天的是现价，不是历史。
    """
    p = os.path.join(ROOT, "etf_dip_signal", "data", "all_etf_1120.parquet")
    if not os.path.exists(p):
        print("[警告] 缺 all_etf_1120.parquet，预测将退回联网取 K 线（不稳定）")
        return {}, ""
    try:
        import pandas as pd
        df = pd.read_parquet(p, columns=["code", "date", "close"])
        df["code"] = df["code"].astype(str)
        df = df[df["code"].isin(set(codes))].sort_values(["code", "date"])
        out, last_date = {}, ""
        for c, g in df.groupby("code"):
            v = g["close"].dropna().tail(n).tolist()
            if len(v) < 30:
                continue
            out[c] = [round(float(x), 4) for x in v]
            d = str(g["date"].max())[:10]
            if d > last_date:
                last_date = d
        return out, last_date
    except Exception as e:
        print("[警告] 读 K 线失败：%r" % (e,))
        return {}, ""


# 环境判据要 800 根（创业板波动分位用的是 rolling(750, min_periods=250)）
SCORE_CLOSE = ["510300", "159915", "510880"]
# 市场状态检测器要 OHLCV（ATR 用 high/low、布林用 close、量比用 volume）
# 除基准 510300/159915 外，把四条策略的持仓标的也覆盖上 —— 用户要能看自己拿的票
SCORE_OHLCV = ["510300", "159915", "515450", "515880", "513290", "515020"]
# 多市场广度：A股 / 港股 / 美股 / 欧洲 / 日本 / 商品。
# 用户批评得对 —— 只看一只 ETF 的均线排列会被骗线，要看「多少个市场在涨」。
# 这些只需要 20 日涨幅，给 90 根足够（成本约 4KB）。
BREADTH_CLOSE = ["159920", "513100", "159509", "513030", "513520", "518880", "162411"]
BREADTH_NAME = {"159920": "恒生ETF", "513100": "纳指100", "159509": "纳指科技",
                "513030": "德国30", "513520": "日经225", "518880": "黄金ETF",
                "162411": "油气LOF", "510300": "沪深300", "159915": "创业板",
                "510880": "红利ETF"}


def load_score_data(n_close=800, n_ohlcv=260):
    """把「实时评分 + 环境判据」需要的序列内嵌进页面。

    为什么要这么长：
      环境判据里的「创业板 20 日波动分位」= 当前年化波动在过去 750 个观测中的分位
      （rolling(750, min_periods=250)），少于 ~770 根就算不出来。
    为什么内嵌而不是页面联网拉：
      2026-11-22 实测三家源在 https 发布域下全都不稳定（腾讯 ifzq 不放行、
      东财 20 只并发只成 4 只、次方 CORS 抖动）。评分错一次就是配错仓，
      不能用会抖的源。内嵌 3×800 个 close 约 20KB，换 0 网络 0 延迟。
    """
    p = os.path.join(ROOT, "etf_dip_signal", "data", "all_etf_1120.parquet")
    if not os.path.exists(p):
        print("[警告] 缺 all_etf_1120.parquet，实时评分不可用")
        return {}
    try:
        import pandas as pd
        need = sorted(set(SCORE_CLOSE) | set(SCORE_OHLCV) | set(BREADTH_CLOSE))
        df = pd.read_parquet(p, columns=["code", "date", "open", "close",
                                         "high", "low", "volume"])
        df["code"] = df["code"].astype(str)
        df = df[df["code"].isin(set(need))].sort_values(["code", "date"])
        close_map, ohlcv_map = {}, {}
        dates = None
        for c, g in df.groupby("code"):
            g = g.dropna(subset=["close"])
            if len(g) < 120:
                print("      [评分] %s 只有 %d 根，跳过" % (c, len(g)))
                continue
            # 判据标的要长序列；广度标的算 20 日涨幅，90 根足够（省钱）
            take = n_close if c in SCORE_CLOSE else 90
            gc = g.tail(take)
            close_map[c] = [round(float(x), 3) for x in gc["close"].tolist()]
            if c in SCORE_OHLCV:
                go = g.tail(n_ohlcv)
                ohlcv_map[c] = [[round(float(a), 3), round(float(b), 3),
                                 round(float(d), 3), round(float(e), 3),
                                 int(f)]
                                for a, b, d, e, f in zip(go["open"], go["high"],
                                                         go["low"], go["close"],
                                                         go["volume"])]
                ds = [str(x)[:10] for x in go["date"].tolist()]
                if dates is None or len(ds) > len(dates):
                    dates = ds
        out = {"close": close_map, "ohlcv": ohlcv_map,
               "dates": dates or [], "date": (dates or [""])[-1]}
        print("      评分数据：close %d 只 × 最多 %d 根 ｜ OHLCV %d 只 × 最多 %d 根 ｜ 数据日 %s"
              % (len(close_map), max([len(v) for v in close_map.values()] or [0]),
                 len(ohlcv_map), max([len(v) for v in ohlcv_map.values()] or [0]),
                 out["date"]))
        return out
    except Exception as e:
        print("[警告] 读评分数据失败：%r" % (e,))
        return {}


def _cifang_key():
    """次方 API Key。实测其 CORS 完全放行（预检允许 x-api-key），所以可以进前端。
    风险边界：该账号 trading/list 为空（未开通自动交易），Key 只能读行情，不能下单。"""
    if os.environ.get("LIVE_NO_CF_KEY") == "1":
        return ""
    p = os.path.join(ROOT, "_localdata", "cifang_api_key.txt")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read().strip()
    return os.environ.get("CIFANG_API_KEY", "")


CLOUD["cifangKey"] = _cifang_key()

ACT = {"hold": "持有", "sell": "卖出", "buy": "买入", "empty": "空仓", "none": "—"}


def norm_sid(x):
    """策略名 → 与 hub.strategies[].id 对齐用的键"""
    n = str(x or "")
    if "等股灾" in n:
        return "bank96864"
    if "线C" in n or "乖离" in n:
        return "lineC"
    if "消费轮动" in n:
        return "band96863"
    if "躲停牌" in n or "94744" in n:
        return "momo94744"
    if "momo" in n or "线B" in n:
        return "momo96865"
    return ""


def score_brief(s):
    """九维里挑最强 3 项、最弱 2 项 —— 手机上不铺 9 行"""
    sc = (s or {}).get("score") or {}
    items = sc.get("items") or []
    if not items:
        return None
    def ratio(x):
        mx = x.get("max") or 1
        return (x.get("v") or 0) / mx
    rk = sorted(items, key=ratio, reverse=True)
    return {
        "total": sc.get("total"), "max": sc.get("max") or 100,
        "rk": bool((s or {}).get("rankable")),
        "why": ((s or {}).get("gate") or {}).get("why") or [],
        "top": [{"k": x["k"], "v": round(x["v"], 1), "max": x["max"]} for x in rk[:3]],
        "weak": [{"k": x["k"], "v": round(x["v"], 1), "max": x["max"]} for x in rk[-2:]],
    }


def main():
    hub = json.load(open(os.path.join(HERE, "hub.json"), encoding="utf-8"))
    meta = hub.get("meta") or {}
    ms = (hub.get("market_state") or {}).get("items") or []
    m0 = None
    for x in ms:
        if x.get("code") == (hub.get("market_state") or {}).get("primary"):
            m0 = x
    if m0 is None and ms:
        m0 = ms[0]

    ev = hub.get("regime_evidence") or {}
    S = {s["id"]: s for s in (hub.get("strategies") or [])}
    plans = {}
    for it in ((hub.get("action") or {}).get("items") or []):
        if it.get("code"):
            plans[it["code"]] = it

    def pack(r, is_extra=False):
        sid = r.get("sid") or norm_sid(r.get("strategy"))
        s = S.get(sid) or {}
        la = s.get("live_action") or {}
        p = plans.get(r.get("code"))
        return {
            "sid": sid,
            "s": r.get("strategy"), "badge": r.get("badge"), "code": r.get("code"),
            "name": r.get("name"),
            "cost": r.get("buy_price"), "last": r.get("last"),
            "stop": r.get("stop"), "dist": r.get("dist_stop"),
            "stop_note": r.get("stop_note"),
            "pnl": r.get("pnl"), "held": r.get("held_days"), "prem": r.get("prem"),
            "fb": bool(r.get("fallback")),
            "act": la.get("action") or ("hold" if not is_extra else None),
            "act_reason": la.get("reason"),
            "next": s.get("next_trigger"),
            "score": score_brief(s),
            "plan": None if not p else {
                "side": p.get("side"), "shares": p.get("shares") if SHOW_AMOUNT else None,
                "ref": p.get("ref"), "limit": p.get("limit"), "when": p.get("when"),
                "why": p.get("why"), "after": p.get("after"),
            },
        }

    items, seen = [], set()
    for r in (hub.get("real_positions") or []):
        if r.get("code") in (None, "—") or r["code"] in seen:
            continue
        seen.add(r["code"])
        items.append(pack(r))

    extra = []
    for r in (hub.get("extra_live") or []):
        if r.get("code") in (None, "—"):
            continue
        # 同一标的被多条策略持有（momo96865 与 94744 都持 513290）：
        # 合并成「另有 XX 同持」，不再重复占一张卡
        hit = next((x for x in items if x["code"] == r["code"]), None)
        if hit:
            hit.setdefault("also", []).append(r.get("strategy"))
            continue
        if r["code"] in seen:
            continue
        seen.add(r["code"])
        extra.append(pack(r, True))

    codes = sorted({x["code"] for x in items} | {x["code"] for x in extra})

    # ---- 恒方量化 11 个产品（情报，随页面走）----
    # 除了信号本身，必须把「这份信号是哪天生成的、抓取于何时、落后本地几天」
    # 一起带出去 —— 手机页要能在不重建的情况下直连 Gitee 刷新并当场比对。
    it = hub.get("intel") or {}
    hp = []
    for p in (it.get("products") or []):
        legs = p.get("legs") or []
        l0 = legs[0] if legs else None
        pfx = str(p.get("prefix") or "")
        hp.append({
            "name": p.get("name"),
            "annual": p.get("annual"), "sharpe": p.get("sharpe"), "mdd": p.get("mdd"),
            "tgt": None if not l0 else (l0.get("eff") or l0.get("target")),
            "act": None if not l0 else l0.get("action"),
            "grade": None if not l0 else l0.get("grade"),
            "def": None if not l0 else bool(l0.get("defensive")),
            "n": len(legs),
            "key": p.get("signal_key"),
            "pfx": pfx[3:] if pfx.startswith("dt_") else pfx,
            "sd": p.get("trade_date"),
            "gen": p.get("gen"),
            "st": p.get("status"),
            "lag": p.get("lag_td"),
            "hhmm": p.get("sig_hhmm"),
            "ty": p.get("rtype"),
            "chg": p.get("chg"),
        })
    intel = {
        "date": it.get("trade_date"), "n": it.get("n_product"),
        "n_sig": it.get("n_product_sig"), "risk_on": it.get("risk_on_pct"),
        "products": hp,
        "gen": it.get("generated_at"), "fetched": it.get("fetched_at"),
        "lag": it.get("lag_td"), "data_date": it.get("data_date"),
        "n_stale": it.get("n_stale"), "source": it.get("source"),
        "n_chg": it.get("n_chg"), "prev_date": it.get("prev_date"),
    }

    # ---- 行业内部相对强弱（纯本地日线，随页面走）----
    # 手机上只带聚合数字 + 每组最强/最弱 3 只，不带全部 381 只成分（会把页面撑大 10 倍）。
    ind0 = hub.get("industry") or {}
    # 持仓 → 所属行业的广度：这是「行业强弱」唯一真正和策略串联的地方。
    # 不做这一步，它只是一张漂亮的表；做了，才能在持仓卡里回答
    # 「这笔亏损是它自己的问题，还是整个行业都在跌」。
    ind_map = {}
    for _g in ((ind0.get("industries") or []) + (ind0.get("regions") or [])
               + (ind0.get("wide") or [])):
        for _m in (_g.get("members") or []):
            if _m.get("c"):
                ind_map[_m["c"]] = {"k": _g.get("k"), "br": _g.get("br20"),
                                    "st": _g.get("state")}

    def _trim(x):
        return {
            "k": x.get("k"), "n": x.get("n"), "r5": x.get("r5"), "r20": x.get("r20"),
            "r60": x.get("r60"), "ex20": x.get("ex20"), "br20": x.get("br20"),
            "n_ma": x.get("n_ma"), "d5": x.get("d5"), "disp": x.get("disp"),
            "lead": x.get("lead"), "score": x.get("score"), "state": x.get("state"),
            "mom": x.get("mom"),
            "top": [{"c": m.get("c"), "n": m.get("n"), "r20": m.get("r20")}
                    for m in (x.get("top") or [])[:3]],
            "bot": [{"c": m.get("c"), "n": m.get("n"), "r20": m.get("r20")}
                    for m in (x.get("bot") or [])[:3]],
        }
    industry = {
        "date": ind0.get("date"), "bench20": ind0.get("bench20"),
        "summary": ind0.get("summary"),
        "industries": [_trim(x) for x in (ind0.get("industries") or [])],
        "regions": [_trim(x) for x in (ind0.get("regions") or [])],
        "wide": [_trim(x) for x in (ind0.get("wide") or [])],
    } if ind0 else {}

    # ---- 今日怎么做（手机首屏）：把 hub.action 的「怎么做」原样搬到最上面 ----
    # 这是用户真正会照着做的东西：代码 / 方向 / 限价 / 时段 / 为什么 / 之后怎么办。
    # 以前它藏在持仓卡的「依据与今日指令」里，要展开两次才看得到 —— 等于没有。
    act = hub.get("action") or {}
    act_out = {
        "level": act.get("level"), "head": act.get("head"),
        "next_td": act.get("next_td"),
        "items": [{
            "side": it.get("side"), "code": it.get("code"), "name": it.get("name"),
            "shares": it.get("shares") if SHOW_AMOUNT else None,
            "limit": it.get("limit"), "when": it.get("when"),
            "why": it.get("why"), "after": it.get("after"),
        } for it in (act.get("items") or [])],
    }

    # ---- 策略详情（次方式）：每张卡点进去看的完整一页 ----
    # 数据全部来自 _sim 的同一份账本：净值/指标/年度/月历/调仓/配置。
    # 净值降采样到 ≤240 点（手机画不下 2000 点，也没必要）。
    strat_pack = []
    for s in (hub.get("strategies") or []):
        if not s.get("score"):
            continue
        eq = s.get("equity") or []
        step = max(1, len(eq) // 240)
        eqs = eq[::step]
        if eqs and eq and eqs[-1] != eq[-1]:
            eqs.append(eq[-1])
        cal = s.get("calendar") or {}
        months = sorted(cal)[-3:]
        strat_pack.append({
            "id": s.get("id"), "name": s.get("name"),
            "badge": s.get("badge"), "badge_text": s.get("badge_text"),
            "oneline": s.get("oneline"), "rankable": s.get("rankable"),
            "gate": s.get("gate"), "score": (s.get("score") or {}).get("total"),
            "ret": s.get("ret"), "metrics": s.get("metrics"),
            "by_year": s.get("by_year"), "exec": s.get("exec"),
            "today": s.get("today"),
            "live_action": s.get("live_action"),
            "calendar": {m: cal[m] for m in months},
            "trades": (s.get("trades") or [])[-12:],
            "params": s.get("params"),
            "equity": eqs,
        })

    # ---- 全池溢价（次方 spot 的 IOPV，腾讯没有这个字段）----
    # 来源：hub.json 里各策略的规则排名，以及持仓本身。高溢价是跨境标的的真风险：
    # 159509 溢价 +36.84%、513100 +16.99%，买进去等于先亏掉这部分。
    prem_map = {}
    for it0 in (hub.get("real_positions") or []):
        c, v = it0.get("code"), it0.get("prem")
        if c and c != "—" and v is not None:
            prem_map[c] = round(float(v), 2)
    for s in (hub.get("strategies") or []):
        for r0 in (((s.get("live") or {}).get("rules") or {}).get("rank") or []):
            c, v = r0.get("code"), r0.get("prem")
            if c and v is not None and c not in prem_map:
                prem_map[c] = round(float(v), 2)

    # ---- 预测要用的收盘价序列：构建时算好内嵌，页面不再联网取 K 线 ----
    PRED_CODES = sorted(set(
        ['518880', '159509', '588000', '501225', '513100', '513310',
         '159915', '162719', '159985', '513030', '513290', '513520']      # momo 池
        + ['162411', '161128', '162415', '515450']                        # 96863 池
        + ['159552', '515020']                                            # 96864 两条腿
        + [x['code'] for x in items] + [x['code'] for x in extra]         # 持仓
    ))
    kmap, kdate = load_kline_map(PRED_CODES)
    sdata = load_score_data()

    # 统一账本（_book.py 产出）：四条策略同一口径的净值/持仓/交易/六问
    books = {}
    try:
        bp = os.path.join(ROOT, "etf_dip_signal", "data", "_books.json")
        books = json.load(open(bp, encoding="utf-8"))
    except Exception as e:
        print("[警告] 读 _books.json 失败：%r（账本区块将不显示）" % (e,))

    # 评分标的的名称：优先从真实持仓里取，缺的用固定表兜底（这几只都是主流标的）
    SCORE_NAMES = {"510300": "沪深300ETF", "159915": "创业板ETF", "510880": "红利ETF",
                   "515450": "红利低波ETF", "515880": "通信ETF国泰",
                   "513290": "纳指生物科技", "515020": "银行ETF华夏"}
    SCORE_NAMES.update(BREADTH_NAME)
    for _r in (items + extra):
        if _r.get("code") and _r.get("name"):
            SCORE_NAMES[_r["code"]] = _r["name"]

    data = {
        "data_date": meta.get("data_date"),
        "built_at": meta.get("built_at"),
        "session": meta.get("session"),
        "mobile_url": meta.get("mobile_url"),
        "regime": {"code": ev.get("code"), "label": ev.get("label"),
                   "hits": sum(1 for x in (ev.get("items") or []) if x.get("hit")),
                   "n": len(ev.get("items") or [])},
        "market": None if not m0 else {
            "state": m0["score"]["state"], "score": m0["score"]["total"],
            "conf": m0["score"]["conf"]},
        "n_strategy": len((hub.get("strategies") or [])),
        "items": items, "extra": extra, "codes": codes,
        # 单页合并：这四块以前只在桌面看台里有，手机上看不到
        "chain": hub.get("decision_chain"),
        "health": ((hub.get("health") or {}).get("lights") or []),
        "rules": hub.get("score_rule"),
        "caliber": hub.get("caliber"),
        "intel": intel, "premMap": prem_map,
        "industry": industry, "indMap": ind_map,
        "action": act_out, "strats": strat_pack,
        "refresh": meta.get("refresh") or {},
        "kline": kmap, "klineDate": kdate,
        "score": sdata,
        "scoreNames": SCORE_NAMES,
        "books": books,
        # 实时评分要用的两块：策略基线分（九维 + 每维原始依据）与 regime 适配矩阵
        # 九维的 n 是「这一分怎么来的」—— 用户明确要求点开能看到，必须带上
        "slimStrategies": [{"id": s["id"], "name": s["name"],
                            "short": (s.get("short") or s["name"]),
                            "score": {"total": s["score"]["total"],
                                      "max": s["score"].get("max", 100),
                                      "items": [{"k": i["k"], "max": i["max"], "v": i["v"],
                                                 "n": i.get("n") or ""}
                                                for i in s["score"]["items"]]}}
                           for s in (hub.get("strategies") or [])
                           if s.get("score")],
        "matrix": hub.get("regime_matrix"),
        "hide_amount": not SHOW_AMOUNT,
        # GitHub Actions 每天产出 state.json，页面 fetch 它覆盖内嵌快照。
        # 没配就留空 —— 页面不会发请求，也就不会刷 404。
        # 口径退化（云端跑时常出现）：线C/momo/96863 缺分时库会退回收盘价，
        # 年化能差 2~3pp。页面必须把这件事写在右上角，不能装作没发生。
        "caliberWarn": caliber_warn(),
        "stateUrl": state_url(),
        "cloud": CLOUD,
    }

    # 可选：把「页面要用的同一份数据」落成 state.json。
    # 由 GitHub Actions 调用（LIVE_STATE_OUT=data/state.json），提交到仓库后
    # 页面直连 raw 拉取 ⇒ 电脑关着也能天天更新。
    # 形状与内嵌 D 完全一致（去掉 kline/score 这些历史序列），merge 时直接覆盖。
    _so = os.environ.get("LIVE_STATE_OUT")
    if _so:
        try:
            _out = {k: v for k, v in data.items()
                    if k not in ("kline", "score", "scoreNames", "cloud",
                                 "endpoint", "oauthRelayBaseUrl", "publishableKey")}
            _out["v"] = 1
            _d = os.path.dirname(os.path.abspath(_so))
            if _d:
                os.makedirs(_d, exist_ok=True)
            with open(_so, "w", encoding="utf-8") as _f:
                json.dump(_out, _f, ensure_ascii=False, separators=(",", ":"))
            print("状态快照 %s（%.0f KB）" % (_so, os.path.getsize(_so) / 1024.0))
        except Exception as _e:
            print("[警告] 写 state 失败：%r" % (_e,))

    core_p = os.path.join(HERE, "live_core.js")
    core = open(core_p, encoding="utf-8").read() if os.path.exists(core_p) else ""
    if not core:
        print("[警告] 缺 live_core.js，手机页将无法判定")
    pred_p = os.path.join(HERE, "predict_core.js")
    pred = open(pred_p, encoding="utf-8").read() if os.path.exists(pred_p) else ""
    if not pred:
        print("[警告] 缺 predict_core.js，调仓预测不可用")
    cf_p = os.path.join(HERE, "cf_api.js")
    cf = open(cf_p, encoding="utf-8").read() if os.path.exists(cf_p) else ""
    if not cf:
        print("[警告] 缺 cf_api.js，次方直连不可用")
    sc_p = os.path.join(HERE, "score_core.js")
    sc = open(sc_p, encoding="utf-8").read() if os.path.exists(sc_p) else ""
    if not sc:
        print("[警告] 缺 score_core.js，实时评分不可用")

    os.makedirs(OUT_DIR, exist_ok=True)
    # 2026-11-22：手机页改成「单页到底」，模板由 _merge_page.py 从 live_template.html
    # 生成 app_template.html（去掉 iframe、补上决策链/矩阵/健康/评分标准/口径五块）。
    # 回退方式：删掉 app_template.html，自动用回 live_template.html。
    src_t = os.path.join(HERE, "live_template.html")
    tpl_t = os.path.join(HERE, "app_template.html")
    if (os.path.exists(src_t)
            and (not os.path.exists(tpl_t) or os.path.getmtime(tpl_t) < os.path.getmtime(src_t))):
        # 模板改过但没重新合并 —— 自动补一次，避免每日链路一直在用旧模板
        try:
            import subprocess
            import sys
            subprocess.run([sys.executable, "_merge_page.py"], cwd=HERE,
                           check=True, capture_output=True)
            print("      [模板] live_template 有更新，已重新合并 app_template")
        except Exception as _e:
            print("      [模板] 合并失败，改用 live_template：%r" % (_e,))
            tpl_t = ""
    _tpl = tpl_t if (tpl_t and os.path.exists(tpl_t)) else src_t
    tpl = open(_tpl, encoding="utf-8").read()
    html = (tpl.replace("__LIVE_CORE__", core)
               .replace("__PREDICT_CORE__", pred)
               .replace("__CF_API__", cf)
               .replace("__SCORE_CORE__", sc)
               .replace("__LIVE_DATA__", json.dumps(data, ensure_ascii=False)))
    html = restyle(html)
    p = os.path.join(OUT_DIR, "index.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(html)
    print("写出 %s（%.1f KB）｜ 持仓 %d 个 ｜ 监控 %d 只 ｜ 内核 %d+%d+%d+%d 行 ｜ 次方Key %s"
          % (p, os.path.getsize(p) / 1024, len(items), len(codes),
             core.count("\n") + 1, pred.count("\n") + 1, cf.count("\n") + 1,
             sc.count("\n") + 1,
             "已注入" if CLOUD.get("cifangKey") else "未注入"))


if __name__ == "__main__":
    main()
