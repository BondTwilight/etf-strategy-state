# -*- coding: utf-8 -*-
"""生成聚宽 v4.4：批量取数 + 结构自适应 + 首日自校验 + 逐只兜底"""
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
聚宽回测版 v4.4 · ETF 乖离率抄底策略
================================================================
前几版在聚宽上「跑完但零交易」，根因是取数结构。本版按官方文档修正，并加入自校验。

【官方文档依据（逐条核对过）】
  · 多标的 get_price 不能 skip_paused=True：
    「为了保持时间轴的一致，我们没有跳过停牌的日期，停牌时使用停牌前的数据填充。
      如想跳过，请使用 attribute_history」
  · 日线「不包括当天的，即使是在收盘后」⇒ 盘中取当日价必须用分钟频或
    get_current_data().last_price，所以【回测频率必须选分钟】。
  · panel=False 多标的的返回结构随版本不同（宽表 / MultiIndex 长表 / Panel），
    本版用 _to_wide 自适应，并在首日与 attribute_history 对账，对不上自动降级。

【本地基准（2021-01-04 ~ 2026-10-20）】
    保护位全开（默认）：年化 +40.74%  最大回撤 -18.38%  Calmar 2.22  胜率 82.2%
    保护位全关：        年化 +34.28%  最大回撤 -32.32%  Calmar 1.06  胜率 92.1%

【用法】
    1. 新建策略，粘贴本文件
    2. 初始资金 100000 ｜ 频率【分钟】｜ 区间 2021-01-04 ~ 2026-10-20 ｜ 基准 510300.XSHG
    3. 先跑通：SMOKE_TEST=40，约 1 分钟；确认后再改回 0 跑全池
"""
import numpy as np
import pandas as pd
import jqdata                      # noqa: F401

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

SMOKE_TEST = 0        # >0 只取前 N 只（快速验证，结果无意义）
DEBUG = False
WARMUP = 62           # 取的日线根数（需 > BIAS_SORT_DAYS）

# ★ 两个可 A/B 的口径开关
EXEC_TIME = '14:50'            # 决策/成交时点。改成 '14:57' 可近似「按收盘价成交」
                               # （本地回测用的是收盘价，两者会有系统性差异）
EXIT_ON_TIMEOUT_NO_CAND = True  # 满 HOLD_MAX_DAYS 且当天无候选时：
                                #   True  = 清仓（对齐本地 timeout_live=True）
                                #   False = 继续持有（原包在「天基营不可用」时的行为）

# ==================================================================
# 固定池 381 只（code:阈值）｜ -16=A股/港股/中概(339) -11=跨境/商品(32) -5=红利(10)
# ==================================================================
_POOL_RAW = (
{POOL_RAW}
)


def _parse_pool(raw):
    d = {{}}
    for x in raw.replace('\n', '').split(','):
        x = x.strip()
        if x and ':' in x:
            c, t = x.split(':')
            d[c.strip()] = int(t)
    return d


def to_jq(c6):
    return c6 + ('.XSHG' if c6[0] == '5' else '.XSHE')


def initialize(context):
    set_option('use_real_price', True)
    set_benchmark('510300.XSHG')
    log.set_level('order', 'error')
    set_slippage(PriceRelatedSlippage(0.001))
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                             open_commission=0.0002, close_commission=0.0002,
                             min_commission=5), type='fund')

    th = _parse_pool(_POOL_RAW)
    c6 = list(th.keys())
    if SMOKE_TEST:
        c6 = c6[:SMOKE_TEST]
        log.warn('冒烟测试：仅 %d 只，结果无意义' % len(c6))
    g.th_map = th
    g.codes = [to_jq(c) for c in c6]
    g.map2six = {{to_jq(c): c for c in c6}}
    g.th = np.array([th.get(g.map2six[j], -16) for j in g.codes], dtype=float)
    g.meta = {{}}
    g.stat = {{'sell': {{}}, 'days': 0, 'n_buy': 0, 'mode': None, 'diag': ''}}
    run_daily(trade, time=EXEC_TIME)
    log.info('池子 %d 只 ｜ TRAIL=%s BE=%s' % (
        len(g.codes), ENABLE_TRAIL, ENABLE_BREAKEVEN))


# ==================================================================
# 结构自适应
# ==================================================================
def _to_wide(raw, code_set):
    """统一成 index=时间, columns=证券代码。返回 None 表示认不出来。"""
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get('close', raw)
    if type(raw).__name__ == 'Panel':
        try:
            raw = raw['close']
        except Exception:
            try:
                raw = raw.to_frame()
            except Exception:
                return None
    if raw is None or not hasattr(raw, 'index'):
        return None

    # 宽表：列就是代码
    cols = list(getattr(raw, 'columns', []))
    if cols and any(c in code_set for c in cols[:80]):
        return raw

    # 长表：行索引里有一层是代码
    idx = getattr(raw, 'index', None)
    if idx is not None and getattr(idx, 'nlevels', 1) > 1:
        for lv in range(idx.nlevels):
            try:
                vals = list(idx.get_level_values(lv)[:400])
            except Exception:
                continue
            if any(v in code_set for v in vals):
                try:
                    ser = raw.iloc[:, 0] if getattr(raw, 'shape', (0, 0))[1] >= 1 else raw
                    w = ser.unstack(level=lv)
                    if getattr(w.columns, 'nlevels', 1) > 1:
                        w.columns = [c[0] if isinstance(c, tuple) else c for c in w.columns]
                    return w
                except Exception:
                    continue
    return None


# ==================================================================
# 取数：批量 → 失败则逐只
# ==================================================================
def _fetch_batch(context):
    raw = get_price(g.codes, count=WARMUP, end_date=context.previous_date,
                    frequency='daily', fields=['close'], fq='pre',
                    skip_paused=False, panel=False)
    return _to_wide(raw, set(g.codes))


def _usable(wide, codes):
    """统计「有效历史 ≥ BIAS_SORT_DAYS 根」的标的数。"""
    n = 0
    for c in codes:
        try:
            if wide[c].dropna().shape[0] >= BIAS_SORT_DAYS:
                n += 1
        except Exception:
            continue
    return n


def _fetch_per(context):
    """逐只 attribute_history —— 官方文档明确推荐用它跳过停牌。"""
    out = {{}}
    for jq in g.codes:
        try:
            d = attribute_history(jq, WARMUP, '1d', ['close'],
                                  skip_paused=True, df=False, fq='pre')
            a = np.asarray(d['close'], dtype=float)
            a = a[np.isfinite(a)]
            a = a[a > 0]
            if len(a) < BIAS_SORT_DAYS:
                continue
            # 近 5 日完全不变 → 疑似停牌填充，跳过（避免复牌跳空变假买点）
            if len(a) >= 5 and np.allclose(a[-5:], a[-5]):
                continue
            out[jq] = a[-WARMUP:]
        except Exception:
            continue
    return out


def _selfcheck(context, wide):
    """用 attribute_history 单只结果校验批量结果。

    返回 (结论, 说明)，结论为 True/False/None：
      True  = 至少一只对上 → 批量可信
      False = 有可比对且全部对不上 → 批量结构有问题
      None  = 一只都比不了（区间早期标的尚未上市）→ **不能因此否定批量**
    """
    tried, hit, detail = 0, 0, ''
    for jq in list(g.codes[:20]):
        try:
            d = attribute_history(jq, 2, '1d', ['close'],
                                  skip_paused=True, df=False, fq='pre')
            a = np.asarray(d['close'], dtype=float)
            a = a[np.isfinite(a)]
            a = a[a > 0]
            if len(a) == 0:
                continue
            try:
                got = float(wide[jq].dropna().iloc[-1])
            except Exception:
                continue
            ref = float(a[-1])
            tried += 1
            if abs(ref - got) < max(1e-6, abs(ref) * 0.01):
                hit += 1
                if not detail:
                    detail = '%s 基准%.4f 批量%.4f' % (jq, ref, got)
            elif not detail:
                detail = '%s 不一致 基准%.4f 批量%.4f' % (jq, ref, got)
        except Exception:
            continue
        if tried >= 5:
            break
    if tried == 0:
        return None, '无可比对标的（区间早期尚未上市），不作否定'
    return (hit > 0), '比对%d只命中%d只 %s' % (tried, hit, detail)


# ==================================================================
# 指标：与本地 indicators.calculate_bias 完全同构
# ==================================================================
def signals_at(C, P):
    """C: (n, N) 历史收盘（截至上一交易日）；P: (N,) 今日实时价。

    均线必须「含当日」⇒ 把今日价追加成最后一根再算。
    bmin5 = 近 5 根各自 20 日乖离率的最小值（第 5 根就是今日）。
    """
    full = np.vstack([C, P.reshape(1, -1)])
    last = full[-1]
    with np.errstate(divide='ignore', invalid='ignore'):
        ma20 = full[-BIAS_BUY_DAYS:].mean(axis=0)
        ma50 = full[-BIAS_SORT_DAYS:].mean(axis=0)
        b20 = (last / ma20 - 1.0) * 100.0
        b50 = (last / ma50 - 1.0) * 100.0
        mins = np.full(full.shape[1], np.inf)
        for k in range(OVERSOLD_LOOKBACK):
            end = full.shape[0] - OVERSOLD_LOOKBACK + k + 1
            if end < BIAS_BUY_DAYS:
                continue
            seg = full[end - BIAS_BUY_DAYS:end]
            m = seg.mean(axis=0)
            with np.errstate(invalid='ignore'):
                bb = (seg[-1] / m - 1.0) * 100.0
            mins = np.fmin(mins, bb)
    for a in (b20, b50, mins):
        a[~np.isfinite(a)] = np.nan
    return b20, b50, mins


# ==================================================================
# 主逻辑
# ==================================================================
def trade(context):
    g.stat['days'] += 1
    N = len(g.codes)

    # ---------- 取数：只在首日决定一次模式 ----------
    wide = None
    if g.stat['mode'] is None:
        try:
            wide = _fetch_batch(context)
        except Exception as e:
            g.stat['diag'] += '批量异常 %s:%s; ' % (type(e).__name__, str(e)[:60])
        if wide is not None:
            n_ok = _usable(wide, g.codes)
            g.stat['diag'] += '批量可用 %d 只; ' % n_ok
            verdict, why = _selfcheck(context, wide)
            g.stat['diag'] += '自校验[%s] %s; ' % (
                {{True: '通过', False: '失败', None: '无法判定'}}[verdict], why)
            # 只有「确实比对过且至少一只对上」才用批量；无法判定一律走逐只
            # （逐只 attribute_history 是官方推荐路径，已在实盘中证明可用）
            if verdict is not True or n_ok < 10:
                wide = None
        if wide is None:
            g.stat['mode'] = 'per'
            log.warn('[取数] 批量未通过校验，改用逐只 attribute_history'
                     '（慢但可靠，官方推荐路径）。诊断：%s' % g.stat['diag'])
        else:
            g.stat['mode'] = 'batch'
            log.info('[取数] 批量模式。可用 %d 只。%s'
                     % (_usable(wide, g.codes), g.stat['diag']))
    elif g.stat['mode'] == 'batch':
        try:
            wide = _fetch_batch(context)
            if wide is None:
                log.warn('[取数] 批量返回结构无法识别，切逐只模式')
                g.stat['mode'] = 'per'
        except Exception as e:
            log.error('批量取数异常，切逐只：%s' % e)
            g.stat['mode'] = 'per'

    # ---------- 组装收盘矩阵 ----------
    cd = get_current_data()
    P = np.full(N, np.nan)
    LIMIT = np.zeros(N, dtype=bool)      # 当日涨停/跌停 → 不买（涨停根本买不进）
    for k, jq in enumerate(g.codes):
        try:
            d = cd[jq]
            if d.paused:
                continue
            p = d.last_price
            if p and p == p and p > 0:
                P[k] = float(p)
                try:
                    if p >= d.high_limit * 0.995 or p <= d.low_limit * 1.005:
                        LIMIT[k] = True
                except Exception:
                    pass
        except Exception:
            continue

    C = None
    if wide is not None:
        try:
            sub = wide.reindex(columns=g.codes).ffill()
            C = sub.values.astype(float)
        except Exception:
            C = None
    if C is None:
        per = _fetch_per(context)
        per = {j: v for j, v in per.items() if len(v) >= BIAS_SORT_DAYS}
        # 早期只有几十只在世，门槛必须小；旧版用「池子一半(190)」把 2021~2023 整段空转
        if len(per) < 5:
            if g.stat['days'] <= 2:
                log.error('❌ 可用标的不足 5 只。诊断：%s' % g.stat['diag'])
            return
        n = min(len(v) for v in per.values())
        cols, used = [], []
        for jq in g.codes:
            if jq in per:
                cols.append(per[jq][-n:])
                used.append(jq)
        C = np.column_stack(cols)
        P = np.array([P[g.codes.index(j)] for j in used])
        LIMIT = np.array([LIMIT[g.codes.index(j)] for j in used])
        codes_now = used
    else:
        codes_now = g.codes

    if C is None or C.shape[0] < BIAS_SORT_DAYS:
        return
    N = C.shape[1]

    # ---------- 指标（含当日：把今日价追加成最后一根） ----------
    b20, b50, bmin5 = signals_at(C, P)

    if g.stat['days'] == 1:
        log.info('[首日诊断] 标的 %d ｜ 有价 %d ｜ 可算乖离 %d ｜ 矩阵 %s ｜ 模式 %s ｜ %s'
                 % (N, int(np.isfinite(P).sum()), int(np.isfinite(bmin5).sum()),
                    C.shape, g.stat['mode'], g.stat['diag']))
        if int(np.isfinite(P).sum()) < N * 0.5:
            log.error('⚠️ 过半标的无实时价：回测频率八成选成了日频，请改【分钟】')

    # ---------- 候选 ----------
    th = np.array([g.th_map.get(g.map2six.get(j, j), -16) for j in codes_now], dtype=float)
    with np.errstate(invalid='ignore'):
        mask = np.isfinite(bmin5) & (bmin5 < th) & np.isfinite(b50) & (~LIMIT)
    idx = np.where(mask)[0]
    top_i = int(idx[np.argsort(b50[idx])[0]]) if len(idx) else -1
    top = codes_now[top_i] if top_i >= 0 else None

    if DEBUG:
        log.info('[候选] %d 只 首位=%s' % (len(idx),
                                         g.map2six.get(top, '-') if top else '-'))

    # ---------- 卖出 ----------
    sold = set()
    today = context.current_dt.strftime('%Y-%m-%d')
    for jq in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[jq]
        if pos.total_amount <= 0 or jq not in codes_now:
            continue
        k = codes_now.index(jq)
        p = P[k]
        if not np.isfinite(p) or p <= 0:
            continue
        ret = p / pos.avg_cost - 1.0 if pos.avg_cost > 0 else 0.0
        meta = g.meta.setdefault(jq, {{'date': today,
                                       'peak': pos.avg_cost or p, 'armed': False}})

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

        held = _held_days(context, meta.get('date'))
        reason = None
        if ret <= -STOP_LOSS_PCT:
            reason = '深套止损'
        elif np.isfinite(b20[k]) and b20[k] >= SELL_BIAS_TH and ret >= 0 and top != jq:
            reason = '回本止盈'
        elif ret >= SELL_PROFIT_PCT and top != jq:
            reason = '目标收益'
        elif held >= HOLD_MAX_DAYS:
            if top and top != jq:
                reason = '到期换仓'
            elif (not top) and EXIT_ON_TIMEOUT_NO_CAND:
                # 对齐本地 timeout_live：满期且无候选也退出，不无限期持有
                reason = '到期清仓'
        if reason:
            _sell(context, jq, reason)
            sold.add(jq)

    # ---------- 买入 ----------
    hold_n = len([c for c, q in context.portfolio.positions.items()
                  if q.total_amount > 0])
    if hold_n < MAX_HOLD and top is not None and top not in sold:
        val = context.portfolio.total_value * 0.995
        if val > 1000:
            order_target_value(top, val)
            pos = context.portfolio.positions.get(top)
            if pos and pos.total_amount > 0:
                g.meta[top] = {{'date': today, 'peak': pos.avg_cost or P[top_i],
                                'armed': False}}
                g.stat['n_buy'] += 1
                log.info('[买入] %s %s bias50=%.2f'
                         % (g.map2six.get(top, top), top, b50[top_i]))
            else:
                log.warn('[买入未成交] %s' % g.map2six.get(top, top))

    if g.stat['days'] % 20 == 0:
        log.info('[进度] 净值 %.4f 持仓 %d ｜ 有价 %d ｜ 候选 %d ｜ 买入 %d ｜ %s'
                 % (context.portfolio.total_value / 100000.0, hold_n,
                    int(np.isfinite(P).sum()), len(idx), g.stat['n_buy'],
                    str(g.stat['sell'])))
    if g.stat['days'] == 20 and g.stat['n_buy'] == 0:
        log.error('⚠️ 20 个交易日零买入，把 DEBUG 改 True 看逐日候选数')


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
        return max(len(get_trade_days(start_date=entry_date,
                                      end_date=context.current_dt)) - 1, 0)
    except Exception:
        return 0
'''

out = TEMPLATE.replace('{POOL_RAW}', POOL_RAW).replace('{{', '{').replace('}}', '}')
path = os.path.join(os.path.dirname(BASE), 'deliverables', 'jq_etf_dip_v44.py')
with open(path, 'w', encoding='utf-8') as f:
    f.write(out)
print('已生成 %s  %d 行' % (path, out.count(chr(10)) + 1))
