# -*- coding: utf-8 -*-
"""生成聚宽（JoinQuant）可回测版本：把本地 v4.2-local 的逻辑原样搬过去。

输出：deliverables/jq_etf_dip_v42.py
"""
import json
import os
import textwrap

BASE = os.path.dirname(os.path.abspath(__file__))
POOL = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'), encoding='utf-8'))

codes = POOL['codes']
bmap = {str(k): int(v) for k, v in POOL['bmap'].items()}

# 压缩池子：code:阈值，按行折叠
items = ['%s:%d' % (c, bmap.get(c, -16)) for c in codes]
pool_lines = textwrap.wrap(','.join(items), width=96,
                           break_on_hyphens=False, break_long_words=False)
POOL_RAW = '\n'.join('    "%s,"' % ln for ln in pool_lines)

TEMPLATE = '''# -*- coding: utf-8 -*-
"""
聚宽回测版 · ETF 乖离率抄底策略 v4.2-local
================================================================
由本地 etf_dip_signal/ 版本一比一移植，用于在聚宽上交叉验证。

【本地回测基准（2021-01-04 ~ 2026-10-20，5.8 年，381 只冻结池）】
    保护位全开（本文件默认）：年化 +40.74%  最大回撤 -18.38%  Calmar 2.22  胜率 82.2%
    保护位全关（原包逻辑）：年化 +34.28%  最大回撤 -32.32%  Calmar 1.06  胜率 92.1%
  若你在聚宽跑出的数字与上述差距 >5pp，先看文件末尾「口径差异」清单，不要急着改参数。

【策略一句话】
    381 只 ETF 里找「跌得最不理性」的那只（按 50 日乖离率排序），买入；
    持有期间六道闸门决定卖出——止盈类可被「候选第一还是自己」否决（让利润奔跑），
    保护类（移动止盈/保本/深止损）不可否决。

【在聚宽怎么用】
    1. 新建策略 → 粘贴本文件全部内容
    2. 回测设置：初始资金 100000，频率「每天」，区间 2021-01-04 ~ 2026-10-20
    3. 基准建议选 510300.XSHG（与本地一致；换 000852 也合理，但不可直接对比）
    4. 运行。首次跑 381 只 × 62 根日线，约需数分钟
    5. ⚠️ 若「性能分析」面板提示「暂无相关内容，请确认使用 enable_profile()」——
       那是该面板的空状态，**不是回测失败**。回测结果看「回测详情 / 收益概览」。
       要用性能分析排查耗时，把 ENABLE_PROFILE 改成 True。
    6. 想先验证能不能跑通：把 SMOKE_TEST 改成 30，30 秒内出结果（数字无意义）。
"""
import numpy as np

# ==================================================================
# 参数（与本地 config.py 对齐）
# ==================================================================
INIT_CASH = 100000          # 聚宽在回测设置里填，这里仅用于说明
MAX_HOLD = 1                # 最大持仓数（原包为 1，单票满仓）
STOP_LOSS_PCT = 0.15        # 深套止损
SELL_PROFIT_PCT = 0.03      # 目标收益
SELL_BIAS_TH = 0.0          # 回本止盈：20 日乖离 >= 0
HOLD_MAX_DAYS = 30          # 满 N 个交易日触发换仓判断
BIAS_BUY_DAYS = 20          # 判断超卖用的乖离窗口
BIAS_SORT_DAYS = 50         # 排序用的乖离窗口
OVERSOLD_LOOKBACK = 5       # 近 N 根取最小

TRAIL_STOP_PCT = 0.08       # 移动止盈：自持仓期最高收盘回撤 8%
BREAKEVEN_STOP_PCT = 0.03   # 保本止损：浮盈曾达 3% 后回落至成本价即卖

ENABLE_TRAIL = True         # ← 想复现原包 34.28%，把这两个改成 False
ENABLE_BREAKEVEN = True     # ←
ENABLE_TJ = False           # 天基营（聚宽回测无外网，见文末说明）

ENABLE_PROFILE = False      # True 则在 initialize 第一行调用 enable_profile()
                            # —— 只有开了它，「性能分析」面板才会有内容。注意会增加耗时。
SMOKE_TEST = 0              # >0 则只取前 N 只标的跑（用于 30 秒内验证能跑通，结果无意义）

WARMUP = BIAS_SORT_DAYS + 12      # 每次取的日线根数
DEBUG = False                     # True 则打印每日候选与卖出原因

# ==================================================================
# 固定池：381 只，2026-10-14 冻结（code:阈值）
# 阈值分档：-16 = A股/港股/中概(339只)  -11 = 跨境/商品/纯境外(32只)  -5 = 红利低波(10只)
# ==================================================================
_POOL_RAW = (
{POOL_RAW}
)


def _parse_pool(raw):
    d = {{}}
    for x in raw.replace('\\n', '').split(','):
        x = x.strip()
        if not x or ':' not in x:
            continue
        c, t = x.split(':')
        d[c.strip()] = int(t)
    return d


def to_jq(code6):
    """6 位代码 → 聚宽代码。5 开头（51/56/58）沪市，1 开头（15）深市。"""
    return code6 + ('.XSHG' if code6[0] == '5' else '.XSHE')


def initialize(context):
    # ★ 若要使用聚宽「性能分析」面板，必须在这里（initialize 第一行）开启 profiling。
    #   不开的话，性能分析面板会显示「暂无相关内容」，那是面板的空状态，不是回测失败。
    if ENABLE_PROFILE:
        enable_profile()

    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    log.set_level('order', 'error')
    set_benchmark('510300.XSHG')

    # 与本地一致：佣金万 2、最低 5 元；滑点按价格 0.1%
    set_order_cost(OrderCost(open_commission=0.0002, close_commission=0.0002,
                             close_today_commission=0, min_commission=5),
                   type='fund')
    set_slippage(PriceRelatedSlippage(0.001))

    g.th_map = _parse_pool(_POOL_RAW)              # {6位: 阈值}
    g.codes6 = list(g.th_map.keys())
    if SMOKE_TEST:
        g.codes6 = g.codes6[:SMOKE_TEST]
        log.warn('⚠️ 冒烟测试：仅取前 %d 只标的，结果无意义，只用于验证能否跑通'
                 % len(g.codes6))
    g.codes_jq = [to_jq(c) for c in g.codes6]
    g.map_jq2_6 = {{to_jq(c): c for c in g.codes6}}
    g.meta = {{}}                                  # {jq: {{date, peak, armed}}}
    g.stat = {{'sell': {{}}, 'days': 0, 'n_buy': 0}}
    g.px_mode = None                               # get_price 的 panel 模式，首日自动探测

    run_daily(trade, time='14:50')
    log.info('池子 %d 只，保护位 TRAIL=%s BREAKEVEN=%s' % (
        len(g.codes_jq), ENABLE_TRAIL, ENABLE_BREAKEVEN))


# ==================================================================
# 指标
# ==================================================================
def _bias_bundle(closes):
    """返回 (bias20, bias50, bmin5)。closes 为升序 numpy 数组。"""
    n = len(closes)
    if n < BIAS_SORT_DAYS:
        return None
    last = closes[-1]
    ma20 = closes[-BIAS_BUY_DAYS:].mean()
    ma50 = closes[-BIAS_SORT_DAYS:].mean()
    if ma20 <= 0 or ma50 <= 0:
        return None
    b20 = (last / ma20 - 1.0) * 100.0
    b50 = (last / ma50 - 1.0) * 100.0
    mins = []
    for k in range(OVERSOLD_LOOKBACK):
        idx = n - OVERSOLD_LOOKBACK + k
        if idx < BIAS_BUY_DAYS - 1:
            continue
        seg = closes[:idx + 1]
        m = seg[-BIAS_BUY_DAYS:].mean()
        if m > 0:
            mins.append((seg[-1] / m - 1.0) * 100.0)
    bmin5 = min(mins) if mins else 999.0
    return b20, b50, bmin5


def _normalize_px(px, code_set):
    """把 get_price 的任意返回结构统一成「index=日期, columns=证券代码」的宽表。

    聚宽在不同版本/参数下会给四种结构，不能靠猜：
      ① dict{{'close': DataFrame}}        —— 多字段
      ② Panel（三维）                      —— 老版本默认
      ③ 宽表（columns=证券）               —— panel=False + 单标的，或部分版本
      ④ 长表（行索引 = MultiIndex(时间, 证券), 列=['close']）
                                            —— panel=False + 多标的（本次遇到的）
    """
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
        if getattr(px.index, 'nlevels', 1) > 1:
            px = px.iloc[:, 0] if getattr(px, 'shape', (0,))[1] >= 1 else px

    if not hasattr(px, 'columns'):
        # 可能是 Series（唯一一列被压缩掉）→ 仍按 MultiIndex 行处理
        idx = getattr(px, 'index', None)
        if idx is not None and getattr(idx, 'nlevels', 1) > 1:
            for lv in range(idx.nlevels):
                try:
                    vals = list(idx.get_level_values(lv)[:300])
                except Exception:
                    continue
                if any(v in code_set for v in vals):
                    try:
                        w = px.unstack(level=lv)
                        if getattr(w.columns, 'nlevels', 1) > 1:
                            w.columns = [c[0] if isinstance(c, tuple) else c
                                         for c in w.columns]
                        return w
                    except Exception:
                        continue
        return None

    # ③ 宽表：列里已经出现证券代码
    try:
        if any(c in code_set for c in list(px.columns)[:50]):
            return px
    except Exception:
        pass

    # ④ 长表：找「哪一层是证券」，unstack 到列
    idx = getattr(px, 'index', None)
    if idx is not None and getattr(idx, 'nlevels', 1) > 1:
        for lv in range(idx.nlevels):
            try:
                vals = list(idx.get_level_values(lv)[:300])
            except Exception:
                continue
            if any(v in code_set for v in vals):
                try:
                    ser = px.iloc[:, 0] if px.shape[1] >= 1 else px
                    w = ser.unstack(level=lv)
                    if getattr(w.columns, 'nlevels', 1) > 1:
                        w.columns = [c[0] if isinstance(c, tuple) else c
                                     for c in w.columns]
                    return w
                except Exception:
                    continue
    return None


def _fetch_close(context):
    """取截至「上一交易日」的前复权收盘价，返回 ({{jq: (closes, 最后一根日期)}}, diag)。

    三个踩过的坑：
    ① `skip_paused` 必须 False —— 多标的取数禁止跳过停牌，否则 ParamsError。
    ② 返回结构有四种（见 _normalize_px），必须自适应；否则 `px[code]` 直接 KeyError。
    ③ 异常绝不能静默吞 —— 否则「取数全失败」和「本来没信号」在日志里完全同形。
    """
    diag = {{'total': len(g.codes_jq), 'ok': 0, 'bad': 0, 'short': 0, 'flat': 0,
             'err': '', 'struct': '', 'mode': None}}
    code_set = set(g.codes_jq)

    # 首日两种 panel 模式都试一次，选出可用的那个并记住，之后不再重试
    modes = [g.px_mode] if g.px_mode is not None else [False, True]
    wide = None
    for mode in modes:
        try:
            raw = get_price(g.codes_jq, count=WARMUP, end_date=context.previous_date,
                            frequency='daily', fields=['close'], fq='pre',
                            skip_paused=False, panel=mode)
        except Exception as e:
            diag['err'] = 'get_price(%s): %s: %s' % (mode, type(e).__name__, str(e)[:70])
            continue
        diag['struct'] = '%s 行层=%s 列数=%s 列样例=%s' % (
            type(raw).__name__,
            getattr(getattr(raw, 'index', None), 'nlevels', 1),
            (getattr(raw, 'shape', None) or ('?',))[-1] if hasattr(raw, 'shape') else '?',
            str(list(getattr(raw, 'columns', [])[:3])))
        w = _normalize_px(raw, code_set)
        if w is not None and len(w.columns) > 0:
            wide = w
            g.px_mode = mode
            diag['mode'] = mode
            break
        if not diag['err']:
            diag['err'] = '结构无法识别（见 struct 字段）'

    if wide is None:
        diag['bad'] = diag['total']
        return {{}}, diag

    out = {{}}
    for jq in g.codes_jq:
        try:
            s = wide[jq].dropna()
        except Exception as e:
            diag['bad'] += 1
            if not diag['err']:
                diag['err'] = '%s: %s' % (type(e).__name__, str(e)[:70])
            continue
        if len(s) < BIAS_SORT_DAYS:
            diag['short'] += 1
            continue
        v = np.asarray(s.values, dtype=float).reshape(-1)
        if len(v) < BIAS_SORT_DAYS:
            diag['short'] += 1
            continue
        # 近 5 日价格完全不变 → 大概率是停牌填充，跳过
        if len(v) >= 5 and np.allclose(v[-5:], v[-5]):
            diag['flat'] += 1
            continue
        out[jq] = (v, str(s.index[-1])[:10])
    diag['ok'] = len(out)
    return out, diag


def _tj_signal(context):
    """天基营信号。聚宽回测无外网，默认返回 unpublished（不参与决策）。"""
    if not ENABLE_TJ:
        return 'unpublished'
    d = context.current_dt.strftime('%Y-%m-%d')
    return TJ_TABLE.get(d, 'unpublished')


# 如需启用天基营，把 ENABLE_TJ 改 True 并填入日期→信号（'long' / 'flat'）
TJ_TABLE = {{}}


# ==================================================================
# 主逻辑
# ==================================================================
def trade(context):
    g.stat['days'] += 1
    close_hist, diag = _fetch_close(context)
    cur = get_current_data()
    today = context.current_dt.strftime('%Y-%m-%d')
    tj = _tj_signal(context)

    # ---------- 0. 首日诊断：把「取数失败」和「没有候选」区分开 ----------
    if g.stat['days'] == 1:
        log.info('[首日诊断] 全池 %d 只 ｜ 可用 %d ｜ 取数异常 %d ｜ 历史不足 %d ｜ '
                 '疑似停牌 %d ｜ 采用 panel=%s' % (
                     diag['total'], diag['ok'], diag['bad'], diag['short'],
                     diag['flat'], diag['mode']))
        log.info('[首日诊断·结构] %s' % (diag['struct'] or '未取到'))
        if diag['err']:
            log.warn('[首日诊断·异常] %s' % diag['err'])
        if diag['bad'] > diag['total'] * 0.5:
            log.error('⚠️ 超过半数标的取数失败，策略不可能产生信号，请检查 get_price 返回结构')

    # ---------- 1. 算全池乖离（含当日实时价） ----------
    info = {{}}
    prev_date = str(context.previous_date)[:10]
    skipped = 0
    for jq, (hist, last_d) in close_hist.items():
        if last_d != prev_date:
            skipped += 1
            continue          # 上一交易日未交易 → 跳过，避免造假跳变
        cd = cur[jq]
        if cd.paused:
            continue
        p = cd.last_price
        if p is None or p != p or p <= 0:
            continue
        # 日线末根是「上一交易日」；若实时价与它相同（盘前/停牌）不追加，否则追加为当日
        closes = hist if abs(p - hist[-1]) < 1e-9 else np.append(hist, float(p))
        b = _bias_bundle(closes)
        if b is None:
            continue
        info[jq] = {{'b20': b[0], 'b50': b[1], 'bmin5': b[2], 'px': float(p)}}
    if DEBUG and skipped:
        log.info('[跳过] 上一交易日无行情 %d 只' % skipped)

    # ---------- 2. 候选池：bmin5 < 自身阈值；按 50 日乖离升序 ----------
    cands = []
    for jq, v in info.items():
        c6 = g.map_jq2_6[jq]
        if v['bmin5'] < g.th_map.get(c6, -16):
            cands.append(jq)
    cands.sort(key=lambda x: info[x]['b50'])
    top = cands[0] if cands else None

    if DEBUG:
        log.info('[候选] %d 只 首位=%s 天基营=%s' % (
            len(cands), g.map_jq2_6.get(top, '-'), tj))

    # ---------- 3. 卖出 ----------
    sold_jq = set()           # ★ 当日已卖出的，当天不再回补（否则白付两趟手续费）
    for jq in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[jq]
        if pos.total_amount <= 0 or jq not in info:
            continue
        px = info[jq]['px']
        ret = px / pos.avg_cost - 1.0 if pos.avg_cost > 0 else 0.0
        meta = g.meta.setdefault(jq, {{'date': today, 'peak': pos.avg_cost or px,
                                       'armed': False}})

        # 3.1 保护类（不受「候选第一」否决）
        if ENABLE_TRAIL:
            peak = max(meta.get('peak') or pos.avg_cost or px, px)
            meta['peak'] = peak
            if peak > 0 and px / peak - 1.0 <= -TRAIL_STOP_PCT and ret > -STOP_LOSS_PCT:
                _sell(context, jq, '移动止盈', px)
                continue
        if ENABLE_BREAKEVEN:
            if ret >= BREAKEVEN_STOP_PCT:
                meta['armed'] = True
            if meta.get('armed') and 0 >= ret > -STOP_LOSS_PCT:
                _sell(context, jq, '保本止损', px)
                continue

        # 3.2 四道闸门（除深套止损外，均可被「候选第一仍是自己」否决）
        b20 = info[jq]['b20']
        held = _held_days(context, meta.get('date'))
        reason = None
        if ret <= -STOP_LOSS_PCT:
            reason = '深套止损'
        elif b20 >= SELL_BIAS_TH and ret >= 0 and top != jq:
            reason = '回本止盈'
        elif ret >= SELL_PROFIT_PCT and top != jq:
            reason = '目标收益'
        elif held >= HOLD_MAX_DAYS:
            if top and top != jq:
                reason = '到期换仓'
            elif (not top) and tj == 'flat':
                reason = '到期清仓'
        if reason:
            _sell(context, jq, reason, px)
            sold_jq.add(jq)

    # ---------- 4. 买入 ----------
    hold_n = len([s for s, p in context.portfolio.positions.items()
                  if p.total_amount > 0])
    if hold_n < MAX_HOLD and top is not None and top not in sold_jq:
        cash = context.portfolio.available_cash
        if cash > 1000:
            order_target_value(top, cash * 0.995)
            pos = context.portfolio.positions.get(top)
            if pos and pos.total_amount > 0:
                g.meta[top] = {{'date': today,
                                'peak': pos.avg_cost or info[top]['px'],
                                'armed': False}}
                g.stat['n_buy'] = g.stat.get('n_buy', 0) + 1
                log.info('[买入] %s %s bias50=%.2f' % (
                    g.map_jq2_6[top], top, info[top]['b50']))
            else:
                log.warn('[买入未成交] %s（可能涨停/停牌/资金不足）'
                         % g.map_jq2_6.get(top, top))

    # ---------- 5. 进度与健康检查 ----------
    if g.stat['days'] % 20 == 0:
        log.info('[进度] 净值 %.4f 持仓 %d ｜ 可算乖离 %d 只 ｜ 候选 %d 只 ｜ '
                 '累计买入 %d ｜ 卖出分布 %s'
                 % (context.portfolio.total_value / INIT_CASH, hold_n,
                    len(info), len(cands), g.stat.get('n_buy', 0),
                    str(g.stat['sell'])))
    if g.stat['days'] == 20 and g.stat.get('n_buy', 0) == 0:
        log.error('⚠️ 前 20 个交易日一次都没买入。若「候选」长期为 0，'
                  '多半是取数维度或阈值单位问题，把 DEBUG 改 True 看逐日候选数。')


def _sell(context, jq, reason, px):
    order_target_value(jq, 0)
    g.stat['sell'][reason] = g.stat['sell'].get(reason, 0) + 1
    g.meta.pop(jq, None)
    if DEBUG:
        log.info('[卖出] %s %s' % (g.map_jq2_6.get(jq, jq), reason))


def _held_days(context, entry_date):
    if not entry_date:
        return 0
    try:
        ds = get_trade_days(start_date=entry_date, end_date=context.current_dt)
        return max(len(ds) - 1, 0)
    except Exception:
        return 0


def after_trading_end(context):
    pass


# ==================================================================
# 口径差异清单（跑出来对不上时先看这里）
# ==================================================================
# 1) 成交时点：聚宽日线回测是「收盘价成交」，对应本地 V1/V2 收盘口径。
#    本地另有一个 V3「次日开盘」口径，年化只有 +25.78% —— 若聚宽结果明显低于 34%，
#    先确认不是选成了分钟级、或滑点/佣金设置不同。
#
# 2) 前复权：聚宽 fq='pre' 是「动态前复权」（每次按最新价重算）。因为是整体等比缩放，
#    乖离率这类比值指标不受影响，所以不影响结果，但绝对价格会与本地快照不同 —— 正常。
#
# 3) 盘中止损：本地有一个用当日 low 触发的盘中止损，聚宽日线回测无法模拟。
#    实测该机制 5.8 年只触发 1 次（2021-07-28 513360 跳空 -19.14%），影响很小。
#    若你要严格复现，可用分钟级回测 + 条件单，但会慢很多。
#
# 4) 池子成分：本地是 2026-10-14 冻结的 381 只。2021 年时其中只有 76 只有行情、
#    2016 年只有 28 只 —— 这是「存活者偏差」，会让早期收益偏高。聚宽上同样存在，
#    不需要修，但要知道结论偏乐观。
#
# 5) 数据缺失：本地对单日涨跌 >30% 的脏 K 线做过前缀等比缩放修复
#    （381 只里 55 只、116 根）。聚宽如果数据干净就不需要；若发现某只 ETF 出现
#    离谱的单日跳变，那是数据问题不是策略问题。
#
# 6) 天基营：聚宽回测无外网，默认关闭（ENABLE_TJ=False），此时它只在
#    「满 30 日 + 无候选」时不起作用，对结果影响极小。若要启用，手动填 TJ_TABLE。
#
# 7) 最小交易单位：聚宽对 ETF 按 100 份取整，与本地一致。
#
# 8) 停牌持仓：若持仓标的「上一交易日无成交」，当日不参与卖出判断（无法定价），
#    复牌后继续按六道闸门处理。这是有意的保守设计，本地同样如此。
#
# 9) 性能：每个交易日一次 381 只 × 62 根的批量取数。若回测超时：
#      · 先把 WARMUP 从 62 降到 55（仍大于 BIAS_SORT_DAYS=50，结果不变）
#      · 再不行就缩短区间（先跑 2024-01 ~ 2026-10 验证跑通，再全区间跑）
#
# 10) 卖出当天不回补：本地引擎与线上都禁止「当日卖出后当天再买回同一只」，
#     本文件用 sold_jq 集合实现。若去掉会白付两趟手续费，且回测会虚高。
#
# 11) 若「候选池恒为 0 只」或「候选数与本地差异很大」：把 DEBUG 改成 True，#     看日志里的候选数与首位。若候选长期为 0，说明 `get_current_data().last_price`
#     在日线模式下取到的是前一日价格（不同聚宽版本行为有差异），此时把
#     `p = cd.last_price` 改为：
#         _df = get_price(jq, count=1, end_date=context.current_dt,
#                         frequency='daily', fields=['close'], fq='pre')
#         p = float(_df['close'].iloc[-1])
#     其余逻辑不用动。
#
# 12) 【已修】`get_price 取多只股票数据时, 为了对齐日期, 不能跳过停牌`
#     多标的取数禁止 skip_paused=True。本文件已改为 False，并额外用
#     「近 5 日价格完全不变 ⇒ 疑似停牌填充」来过滤长期停牌标的。
'''

out = TEMPLATE.replace('{POOL_RAW}', POOL_RAW)
for k, v in (('{{', '{'), ('}}', '}')):
    out = out.replace(k, v)

path = os.path.join(os.path.dirname(BASE), 'deliverables', 'jq_etf_dip_v42.py')
with open(path, 'w', encoding='utf-8') as f:
    f.write(out)
print('已生成 %s  %d 字节  %d 行' % (path, len(out.encode('utf-8')),
                                    out.count(chr(10)) + 1))
