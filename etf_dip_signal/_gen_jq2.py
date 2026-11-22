# -*- coding: utf-8 -*-
"""生成聚宽版 v4.3：数据一次性预载 + 全内存计算（不再在每日循环里调取数接口）"""
import json
import os
import textwrap

BASE = os.path.dirname(os.path.abspath(__file__))
POOL = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'), encoding='utf-8'))
codes = POOL['codes']
bmap = {str(k): int(v) for k, v in POOL['bmap'].items()}

items = ['%s:%d' % (c, bmap.get(c, -16)) for c in codes]
pool_lines = textwrap.wrap(','.join(items), width=92,
                           break_on_hyphens=False, break_long_words=False)
POOL_RAW = '\n'.join('    "%s,"' % ln for ln in pool_lines)

TEMPLATE = r'''# -*- coding: utf-8 -*-
"""
聚宽回测版 v4.3 · ETF 乖离率抄底策略
================================================================
v4.2 在聚宽上「跑完但从不交易」的原因是取数：每交易日调一次 381 只的批量
get_price，返回结构随版本变化（Panel / MultiIndex 长表 / 宽表），一取错就全空。
v4.3 改为 **只在第一天取一次全量数据**，之后全部在内存里算 —— 数据接口只调 1 次，
取错了立刻报错，不会静默跑完 70 个月的空仓。

【本地基准（2021-01-04 ~ 2026-10-20）】
    保护位全开（默认）：年化 +40.74%  最大回撤 -18.38%  Calmar 2.22  胜率 82.2%
    保护位全关：        年化 +34.28%  最大回撤 -32.32%  Calmar 1.06  胜率 92.1%

【回测设置】
    · 初始资金 100000
    · 频率：**分钟**（m1）。日频下 get_current_data().last_price 未必是当日价，
      会整体滞后一天。分钟频慢一些，但这是唯一能对齐「14:50 决策」的方式。
    · 区间：2021-01-04 ~ 2026-10-20
    · 基准：510300.XSHG
    · 若嫌慢：先把 SMOKE_TEST 设成 60，1 分钟内验证链路，再改回 0 跑全池。
"""
import datetime
import numpy as np
import pandas as pd
import jqdata                      # noqa: F401  模板惯例，显式导入

# ==================================================================
# 参数
# ==================================================================
MAX_HOLD = 1
STOP_LOSS_PCT = 0.15
SELL_PROFIT_PCT = 0.03
SELL_BIAS_TH = 0.0
HOLD_MAX_DAYS = 30
BIAS_BUY_DAYS = 20
BIAS_SORT_DAYS = 50
OVERSOLD_LOOKBACK = 5

TRAIL_STOP_PCT = 0.08
BREAKEVEN_STOP_PCT = 0.03
ENABLE_TRAIL = True
ENABLE_BREAKEVEN = True
ENABLE_TJ = False

SMOKE_TEST = 0          # >0 只取前 N 只（快速验证链路，结果无意义）
DEBUG = False

WARMUP_CAL_DAYS = 140   # 预载时向前多取的日历天数（> 60 交易日即可）

# ==================================================================
# 固定池：381 只（code:阈值），2026-10-14 冻结
# 阈值：-16 = A股/港股/中概(339)  -11 = 跨境/商品/境外(32)  -5 = 红利低波(10)
# ==================================================================
_POOL_RAW = (
{POOL_RAW}
)


def _parse_pool(raw):
    d = {{}}
    for x in raw.replace('\n', '').split(','):
        x = x.strip()
        if not x or ':' not in x:
            continue
        c, t = x.split(':')
        d[c.strip()] = int(t)
    return d


def to_jq(code6):
    return code6 + ('.XSHG' if code6[0] == '5' else '.XSHE')


# ==================================================================
# 初始化
# ==================================================================
def initialize(context):
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    log.set_level('order', 'error')
    set_benchmark('510300.XSHG')

    set_slippage(PriceRelatedSlippage(0.001))
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                             open_commission=0.0002, close_commission=0.0002,
                             min_commission=5), type='fund')

    th_map = _parse_pool(_POOL_RAW)
    codes6 = list(th_map.keys())
    if SMOKE_TEST:
        codes6 = codes6[:SMOKE_TEST]
        log.warn('冒烟测试：仅前 %d 只，结果无意义' % len(codes6))

    g.th_map = th_map
    g.codes6 = codes6
    g.codes = [to_jq(c) for c in codes6]
    g.map2six = {{to_jq(c): c for c in codes6}}
    g.meta = {{}}                  # {code: {{date, peak, armed}}}
    g.stat = {{'sell': {{}}, 'days': 0, 'n_buy': 0}}
    g.loaded = False
    g.dates = None
    g.C = None                     # (T, N) 收盘矩阵，已 ffill
    g.B20 = None                   # (T, N) 历史 bias20（%），用实际收盘算
    g.MIN4 = None                  # (T, N) 近 4 日 bias20 最小值（不含当日）
    g.diag = ''

    run_daily(trade, time='14:50')
    log.info('池子 %d 只 ｜ TRAIL=%s BREAKEVEN=%s' % (
        len(g.codes), ENABLE_TRAIL, ENABLE_BREAKEVEN))


# ==================================================================
# 结构自适应：把 get_price 的各种返回统一成「日期 × 证券」宽表
# ==================================================================
def _normalize_px(px, code_set):
    if px is None:
        return None
    if isinstance(px, dict):
        px = px.get('close', px)
    if type(px).__name__ == 'Panel':
        try:
            px = px['close']
        except Exception:
            try:
                px = px.to_frame()
            except Exception:
                return None
    if hasattr(px, 'columns') and any(c in code_set for c in list(px.columns)[:50]):
        return px
    idx = getattr(px, 'index', None)
    if idx is not None and getattr(idx, 'nlevels', 1) > 1:
        for lv in range(idx.nlevels):
            try:
                vals = list(idx.get_level_values(lv)[:300])
            except Exception:
                continue
            if any(v in code_set for v in vals):
                try:
                    ser = px.iloc[:, 0] if getattr(px, 'shape', (0, 0))[1] >= 1 else px
                    w = ser.unstack(level=lv)
                    if getattr(w.columns, 'nlevels', 1) > 1:
                        w.columns = [c[0] if isinstance(c, tuple) else c for c in w.columns]
                    return w
                except Exception:
                    continue
    return None


# ==================================================================
# 一次性预载（整个回测只调这一次数据接口）
# ==================================================================
def _preload(context):
    end = context.previous_date
    start = end - datetime.timedelta(days=WARMUP_CAL_DAYS)
    code_set = set(g.codes)
    wide = None
    mode = None

    # 主路径：一次批量取
    for panel in (False, True):
        try:
            raw = get_price(g.codes, start_date=start, end_date=end,
                            frequency='daily', fields=['close'], fq='pre',
                            skip_paused=False, panel=panel)
        except Exception as e:
            g.diag += '批量 panel=%s 异常 %s:%s; ' % (panel, type(e).__name__, str(e)[:50])
            continue
        g.diag += '批量 panel=%s 返回 %s 行层=%s 列数=%s; ' % (
            panel, type(raw).__name__,
            getattr(getattr(raw, 'index', None), 'nlevels', 1),
            getattr(raw, 'shape', ('?', '?'))[-1])
        w = _normalize_px(raw, code_set)
        if w is not None and len(w.columns) >= max(1, int(len(g.codes) * 0.5)):
            wide = w
            mode = 'batch(panel=%s)' % panel
            break

    # 备路径：逐只 get_price（单只允许 skip_paused=True，最接近模板的 attribute_history 写法）
    if wide is None:
        g.diag += '批量失败，改逐只 get_price; '
        ser = {{}}
        for jq in g.codes:
            try:
                s = get_price(jq, start_date=start, end_date=end,
                              frequency='daily', fields=['close'],
                              fq='pre', skip_paused=True)
            except Exception:
                continue
            if s is None or len(s) == 0:
                continue
            try:
                if hasattr(s, 'columns'):
                    s = s.iloc[:, 0]
            except Exception:
                continue
            ser[jq] = s
        if ser:
            wide = pd.DataFrame(ser)
            mode = 'per-code(%d 只)' % len(ser)

    if wide is None:
        log.error('❌ 预载失败，无法回测。诊断：%s' % g.diag)
        g.loaded = True
        return

    wide = wide.reindex(columns=[c for c in g.codes if c in wide.columns])
    wide = wide.sort_index().ffill()
    g.codes = list(wide.columns)
    g.map2six = {{c: g.map2six.get(c, c) for c in g.codes}}
    g.dates = list(wide.index)
    g.C = wide.values.astype(float)
    _build_indicators()
    g.loaded = True
    log.info('[预载] 模式=%s ｜ 日期 %s ~ %s ｜ 标的 %d 只 ｜ %s'
             % (mode, str(g.dates[0])[:10], str(g.dates[-1])[:10],
                g.C.shape[1], g.diag))


def _build_indicators():
    """预计算历史 bias20 矩阵与「近4日最小值」，避免每天重算。"""
    C = g.C
    if C.ndim != 2 or C.shape[0] < BIAS_SORT_DAYS:
        g.B20 = None
        g.MIN4 = None
        return
    df = pd.DataFrame(C)
    ma20 = df.rolling(BIAS_BUY_DAYS, min_periods=BIAS_BUY_DAYS).mean().values
    with np.errstate(divide='ignore', invalid='ignore'):
        B20 = (C / ma20 - 1.0) * 100.0
    B20[~np.isfinite(B20)] = np.nan
    g.B20 = B20
    # 近 4 日（含第 i 日、不含今日）bias20 最小值。
    # 决策日 t 的历史下标 i = t-1，bmin5 = min(B20[i-3..i], bias20_today)
    # ⇒ 这里必须是「不 shift」的 4 日滚动最小，shift 会整体错开一根。
    g.MIN4 = pd.DataFrame(B20).rolling(OVERSOLD_LOOKBACK - 1,
                                       min_periods=OVERSOLD_LOOKBACK - 1).min().values


def signals_at(C, B20, MIN4, i, P):
    """在历史下标 i（= 上一交易日）与今日实时价 P 上，算 b20 / b50 / bmin5。

    关键口径：均线要「含当日」。做法是把窗口里最老的一根换成今日价：
        含当日 50 日均线 = (C[i-48..i] 之和 + P) / 50
    等价于 C[i-49..i] 之和 - C[i-49] + P。20 日同理。
    """
    t50 = C[i - BIAS_SORT_DAYS + 1: i + 1]
    t20 = C[i - BIAS_BUY_DAYS + 1: i + 1]
    s50 = t50.sum(axis=0) - t50[0] + P
    s20 = t20.sum(axis=0) - t20[0] + P
    with np.errstate(divide='ignore', invalid='ignore'):
        ma50 = s50 / BIAS_SORT_DAYS
        ma20 = s20 / BIAS_BUY_DAYS
        b50 = (P / ma50 - 1.0) * 100.0
        b20 = (P / ma20 - 1.0) * 100.0
    b50[~np.isfinite(b50)] = np.nan
    b20[~np.isfinite(b20)] = np.nan
    with np.errstate(invalid='ignore'):
        bmin5 = np.fmin(MIN4[i], b20)
    bmin5[~np.isfinite(bmin5)] = np.nan
    return b20, b50, bmin5


# ==================================================================
# 每日
# ==================================================================
def trade(context):
    g.stat['days'] += 1
    if not g.loaded:
        try:
            _preload(context)
        except Exception as e:
            log.error('预载异常：%s: %s' % (type(e).__name__, e))
            g.loaded = True
    if g.C is None or g.B20 is None:
        return

    # 定位「上一交易日」在矩阵中的行号
    prev = context.previous_date
    i = -1
    for k in range(len(g.dates) - 1, -1, -1):
        if str(g.dates[k])[:10] <= str(prev)[:10]:
            i = k
            break
    if i < BIAS_SORT_DAYS - 1:
        return

    C = g.C
    cd = get_current_data()
    n = C.shape[1]
    P = np.full(n, np.nan)
    for k, jq in enumerate(g.codes):
        try:
            d = cd[jq]
            if d.paused:
                continue
            p = d.last_price
            if p and p == p and p > 0:
                P[k] = float(p)
        except Exception:
            continue

    b20, b50, bmin5 = signals_at(C, g.B20, g.MIN4, i, P)

    if g.stat['days'] == 1:
        ok = int(np.isfinite(P).sum())
        log.info('[首日诊断] 标的 %d ｜ 有价 %d ｜ 可用乖离 %d ｜ 矩阵 %s ｜ %s'
                 % (n, ok, int(np.isfinite(bmin5).sum()), C.shape, g.diag))
        if ok < n * 0.5:
            log.error('⚠️ 过半标的无实时价，检查回测频率是否选成了日频（应为分钟）')

    # ---------------- 候选池 ----------------
    th = np.array([g.th_map.get(g.map2six.get(jq, jq), -16) for jq in g.codes],
                  dtype=float)
    with np.errstate(invalid='ignore'):
        cand_mask = np.isfinite(bmin5) & (bmin5 < th) & np.isfinite(b50)
    cand_idx = np.where(cand_mask)[0]
    top_i = -1
    if len(cand_idx):
        top_i = int(cand_idx[np.argsort(b50[cand_idx])[0]])
    top = g.codes[top_i] if top_i >= 0 else None

    if DEBUG:
        log.info('[候选] %d 只 首位=%s' % (len(cand_idx),
                                         g.map2six.get(top, '-') if top else '-'))

    # ---------------- 卖出 ----------------
    sold = set()
    today = context.current_dt.strftime('%Y-%m-%d')
    for jq in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[jq]
        if pos.total_amount <= 0:
            continue
        if jq not in g.codes:
            continue
        k = g.codes.index(jq)
        p = P[k]
        if not np.isfinite(p) or p <= 0:
            continue
        ret = p / pos.avg_cost - 1.0 if pos.avg_cost > 0 else 0.0
        meta = g.meta.setdefault(jq, {{'date': today, 'peak': pos.avg_cost or p,
                                       'armed': False}})

        # 保护类（不受「候选第一」否决）
        if ENABLE_TRAIL:
            peak = max(meta.get('peak') or pos.avg_cost or p, p)
            meta['peak'] = peak
            if peak > 0 and p / peak - 1.0 <= -TRAIL_STOP_PCT and ret > -STOP_LOSS_PCT:
                _sell(context, jq, '移动止盈')
                sold.add(jq)
                continue
        if ENABLE_BREAKEVEN:
            if ret >= BREAKEVEN_STOP_PCT:
                meta['armed'] = True
            if meta.get('armed') and 0 >= ret > -STOP_LOSS_PCT:
                _sell(context, jq, '保本止损')
                sold.add(jq)
                continue

        b = b20[k]
        held = _held_days(context, meta.get('date'))
        reason = None
        if ret <= -STOP_LOSS_PCT:
            reason = '深套止损'
        elif np.isfinite(b) and b >= SELL_BIAS_TH and ret >= 0 and top != jq:
            reason = '回本止盈'
        elif ret >= SELL_PROFIT_PCT and top != jq:
            reason = '目标收益'
        elif held >= HOLD_MAX_DAYS:
            if top and top != jq:
                reason = '到期换仓'
            elif (not top) and _tj() == 'flat':
                reason = '到期清仓'
        if reason:
            _sell(context, jq, reason)
            sold.add(jq)

    # ---------------- 买入 ----------------
    hold_n = len([c for c, q in context.portfolio.positions.items()
                  if q.total_amount > 0])
    if hold_n < MAX_HOLD and top is not None and top not in sold:
        val = context.portfolio.total_value * 0.995
        if val > 1000:
            order_target_value(top, val)
            pos = context.portfolio.positions.get(top)
            if pos and pos.total_amount > 0:
                g.meta[top] = {{'date': today,
                                'peak': pos.avg_cost or P[top_i],
                                'armed': False}}
                g.stat['n_buy'] += 1
                log.info('[买入] %s %s bias50=%.2f' % (
                    g.map2six.get(top, top), top, b50[top_i]))
            else:
                log.warn('[买入未成交] %s（涨停/停牌/资金不足）'
                         % g.map2six.get(top, top))

    # ---------------- 进度 ----------------
    if g.stat['days'] % 20 == 0:
        log.info('[进度] 净值 %.4f 持仓 %d ｜ 有价 %d ｜ 候选 %d ｜ 累计买入 %d ｜ %s'
                 % (context.portfolio.total_value / 100000.0, hold_n,
                    int(np.isfinite(P).sum()), len(cand_idx),
                    g.stat['n_buy'], str(g.stat['sell'])))
    if g.stat['days'] == 20 and g.stat['n_buy'] == 0:
        log.error('⚠️ 20 个交易日零买入。若候选恒为 0，把 DEBUG 改 True 看逐日候选。')


def _tj():
    return 'unpublished'


def _sell(context, jq, reason):
    order_target_value(jq, 0)
    g.stat['sell'][reason] = g.stat['sell'].get(reason, 0) + 1
    g.meta.pop(jq, None)
    if DEBUG:
        log.info('[卖出] %s %s' % (g.map2six.get(jq, jq), reason))


def _held_days(context, entry_date):
    if not entry_date:
        return 0
    try:
        ds = get_trade_days(start_date=entry_date, end_date=context.current_dt)
        return max(len(ds) - 1, 0)
    except Exception:
        return 0


# ==================================================================
# 口径说明（对不上时先看这里）
# ==================================================================
# 1) 必须是**分钟频**回测。日频下 get_current_data().last_price 未必是当日价，
#    整条信号会滞后一天，结果会明显偏低。
# 2) 前复权用 fq='pre'（动态前复权）。乖离率是比值指标，等比缩放不影响结果。
# 3) 本地另有一个「用当日 low 触发的盘中止损」，聚宽日/分钟回测都难以精确复现；
#    实测该机制 5.8 年只触发 1 次（2021-07-28 513360 跳空 -19.14%），影响很小。
# 4) 停牌处理：预载时 ffill；若某标的近 5 日价格完全不变，视为停牌填充不参与选股。
# 5) 池子 2026-10-14 冻结，2021 年起点只有 76 只在世 —— 存在存活者偏差，结论偏乐观。
# 6) 卖出当天不回补（sold 集合），与本地引擎一致。
'''

out = TEMPLATE.replace('{POOL_RAW}', POOL_RAW)
out = out.replace('{{', '{').replace('}}', '}')

path = os.path.join(os.path.dirname(BASE), 'deliverables', 'jq_etf_dip_v43.py')
with open(path, 'w', encoding='utf-8') as f:
    f.write(out)
print('已生成 %s  %d 行' % (path, out.count(chr(10)) + 1))
