# -*- coding: utf-8 -*-
"""
engine.py —— 双引擎（抄底 + 外部情绪）交易决策
完全对应聚宽策略的：
  should_sell           -> should_sell()
  compute_signals       -> compute_signals()
  execute_trades        -> execute_trades()
  fetch_external_signal -> fetch_external_signal()
  _held_days            -> held_days()
"""

import os
import json
import urllib.request
import urllib.error
import datetime as _dt

import numpy as np
import pandas as pd

import config as cfg
import indicators as ind
from tdx_api import get_realtime, get_trade_dates

# 外部信号缓存
_external_signal_cache = {}


# ==================================================
# 账户模拟（替代 context.portfolio）
# ==================================================
class Portfolio:
    """极简账户：支持 order_target_value、持仓成本、可用资金。"""

    def __init__(self, cash=cfg.INIT_CASH):
        self.init_cash = float(cash)
        self.available_cash = float(cash)
        self.positions = {}   # code -> {'total_amount', 'avg_cost'}
        self.trades = []      # 成交记录
        self._reason = ''     # ★ 当前动作的原因，由 execute_trades 在调用前设置

    def position(self, code):
        return self.positions.get(code)

    def total_value(self, rt_price_map):
        v = self.available_cash
        for code, p in self.positions.items():
            px = rt_price_map.get(code, p['avg_cost'])
            v += p['total_amount'] * px
        return v

    def _buy(self, code, price, value):
        """按金额买入。"""
        exec_price = price * (1 + cfg.SLIPPAGE)
        amount = int(value / exec_price // cfg.LOT_SIZE * cfg.LOT_SIZE)
        if amount <= 0:
            return 0
        cost = amount * exec_price
        commission = max(cost * cfg.COMMISSION, cfg.MIN_COMMISSION)
        if cost + commission > self.available_cash:
            amount -= cfg.LOT_SIZE
            if amount <= 0:
                return 0
            cost = amount * exec_price
            commission = max(cost * cfg.COMMISSION, cfg.MIN_COMMISSION)
        self.available_cash -= (cost + commission)

        pos = self.positions.get(code)
        if pos:
            total_cost = pos['avg_cost'] * pos['total_amount'] + cost
            pos['total_amount'] += amount
            pos['avg_cost'] = total_cost / pos['total_amount']
        else:
            self.positions[code] = {'total_amount': amount, 'avg_cost': exec_price}
        self.trades.append({
            'date': _dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'code': code, 'side': 'buy', 'price': exec_price,
            'amount': amount, 'value': cost, 'reason': self._reason,
        })
        return amount

    def _sell(self, code, price, amount=None):
        pos = self.positions.get(code)
        if not pos or pos['total_amount'] <= 0:
            return 0
        if amount is None:
            amount = pos['total_amount']
        amount = min(amount, pos['total_amount'])
        exec_price = price * (1 - cfg.SLIPPAGE)
        gross = amount * exec_price
        commission = max(gross * cfg.COMMISSION, cfg.MIN_COMMISSION)
        self.available_cash += (gross - commission)
        pos['total_amount'] -= amount
        if pos['total_amount'] <= 0:
            self.positions.pop(code, None)
        self.trades.append({
            'date': _dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'code': code, 'side': 'sell', 'price': exec_price,
            'amount': amount, 'value': gross, 'reason': self._reason,
        })
        return amount

    def set_reason(self, reason):
        """标记下一笔成交的原因（execute_trades 在下单前调用）。"""
        self._reason = reason or ''

    def order_target_value(self, code, target_value, rt_price_map, reason=None):
        """目标市值下单，对应聚宽 order_target_value。

        reason 不为 None 时覆盖当前标记，便于调用点就近说明原因。
        """
        if reason is not None:
            self.set_reason(reason)
        if target_value <= 0:
            px = rt_price_map.get(code)
            if px and px > 0:
                self._sell(code, px)
            return
        px = rt_price_map.get(code)
        if not px or px <= 0:
            return
        pos = self.positions.get(code)
        cur_value = (pos['total_amount'] * px) if pos else 0.0
        diff = target_value - cur_value
        if diff > 0:
            self._buy(code, px, diff)
        elif diff < 0:
            amount = int(abs(diff) / px // cfg.LOT_SIZE * cfg.LOT_SIZE)
            if amount > 0:
                self._sell(code, px, amount)


# ==================================================
# 状态容器（替代 g）
# ==================================================
class G:
    def __init__(self):
        self.etf_pool = []
        self.etf_class_map = {}
        self.etf_buy_bias_th_map = {}
        self.last_pool_refresh_month = 0
        self.position_info = {}
        self.position_source = {}
        self.pending_signals = None
        # ★ v4.2.0：最近一次止损日（跨天持久化在 cfg.STOP_STATE_FILE）
        self.last_stop_date = load_last_stop_date()


# ==================================================
# ★ v4.2.0 止损状态持久化（盘中止损 + 冷却的跨天依据）
# ==================================================
def _stop_state_path():
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, cfg.STOP_STATE_FILE)


def load_last_stop_date():
    """读取最近一次止损日（YYYY-MM-DD），无记录返回 None。"""
    try:
        with open(_stop_state_path(), 'r', encoding='utf-8') as f:
            return (json.load(f) or {}).get('last_stop_date') or None
    except Exception:
        return None


def mark_stop_date(date_str):
    """记录止损日（同时写文件，供次日/盘中脚本读取）。"""
    try:
        with open(_stop_state_path(), 'w', encoding='utf-8') as f:
            json.dump({'last_stop_date': date_str}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print('[止损状态] 写入失败: %s' % e)


def trade_days_between(start_date, end_date):
    """两个日期之间的交易日数（含首尾则减 1，返回「相差几个交易日」）。

    ★ 健壮性（v4.2.0）：get_trade_dates 底层是「近 800 根上证日线」，
      若区间超出该窗口或取数失败会返回空列表。
      旧实现 max(len-1,0) 会把空列表夹成 0 → 冷却判定被永久卡死（策略再也买不进）。
      现改为：同日=0；区间取不到日历=None（上层据此 fail-open，不判冷却）。
    """
    if not start_date or not end_date:
        return None
    if str(start_date) >= str(end_date):
        return 0
    try:
        dates = get_trade_dates(start_date=start_date, end_date=end_date)
    except Exception:
        return None
    if not dates:
        return None          # 日历不可用（网络/超窗口）→ 不判冷却，避免永久卡死
    return max(len(dates) - 1, 0)


def in_stop_cooldown(today, g=None):
    """★ 是否处于「止损后冷却期」。返回 (bool, gap_days, last_stop_date)。"""
    if not cfg.STOP_COOLDOWN_DAYS or cfg.STOP_COOLDOWN_DAYS <= 0:
        return False, None, None
    last = (g.last_stop_date if g is not None else None) or load_last_stop_date()
    if not last:
        return False, None, None
    gap = trade_days_between(last, today)
    if gap is None:
        return False, None, last
    return (gap < cfg.STOP_COOLDOWN_DAYS), gap, last


def check_intraday_stop(code, portfolio, today_price):
    """★ 盘中止损判断（不依赖收盘价）。

    条件：当前价 <= 持仓成本 ×(1 - STOP_LOSS_PCT)，即实盘挂的 -15% 条件单被击穿。
    ★ 与深套止损一样【无条件卖】：即使候选第一是自己，也必须止损。
    返回 (bool, reason, loss_pct)
    """
    if not cfg.ENABLE_INTRADAY_STOP:
        return False, '', 0.0
    pos = portfolio.position(code)
    if pos is None or pos.get('total_amount', 0) <= 0:
        return False, '', 0.0
    entry = pos.get('avg_cost')
    if not entry or entry <= 0:
        return False, '', 0.0
    if today_price is None or today_price <= 0:
        return False, '', 0.0
    trigger = entry * (1 - cfg.STOP_LOSS_PCT)
    if today_price <= trigger:
        return True, '盘中止损', today_price / entry - 1.0
    return False, '', today_price / entry - 1.0


def intraday_stop_scan(g, portfolio, rt_df, today, verbose=True):
    """★ 盘中止损巡检：遍历持仓，凡实时价击穿 -15% 的一律立即卖出。

    返回本次卖出的动作列表 [{code, price, loss_pct}]，并：
      - 从 g.position_info / g.position_source 摘除该持仓
      - 记录 g.last_stop_date（写入 cfg.STOP_STATE_FILE），启动冷却期
    可被 intraday_guard.py（盘中定时）与 execute_trades（14:50 决策前）共同调用。
    """
    if not cfg.ENABLE_INTRADAY_STOP:
        return []
    if rt_df is None or rt_df.empty:
        return []
    price_map = dict(zip(rt_df['code'], rt_df['price']))
    lc_map = dict(zip(rt_df['code'], rt_df.get('last_close', rt_df['price'])))
    paused_map = dict(zip(rt_df['code'], rt_df.get('paused', [False] * len(rt_df))))

    hit = []
    holdings = [c for c, p in portfolio.positions.items() if p.get('total_amount', 0) > 0]
    for code in holdings:
        price = price_map.get(code)
        ok, reason, loss = check_intraday_stop(code, portfolio, price)
        if not ok:
            continue
        # 跌停/停牌无法卖出 → 跳过，等下一轮巡检
        lc = float(lc_map.get(code, 0) or 0)
        if bool(paused_map.get(code, False)):
            if verbose:
                print(f"[盘中止损·跳过] {code} 停牌，无法卖出")
            continue
        if lc > 0 and float(price) <= lc * 0.901:
            if verbose:
                print(f"[盘中止损·跳过] {code} 跌停，无法卖出（待下一轮）")
            continue
        portfolio.order_target_value(code, 0, price_map, reason=reason)
        g.position_info.pop(code, None)
        g.position_source.pop(code, None)
        hit.append({'code': code, 'price': round(float(price), 4),
                    'loss_pct': round(loss * 100, 2), 'reason': reason})
        if verbose:
            print(f"[盘中止损] {code} 现价 {price:.4f} 触发 {reason}（{loss * 100:+.2f}%）")

    if hit:
        g.last_stop_date = today
        mark_stop_date(today)
    return hit


# ==================================================
# 卖出判断
# ==================================================
def should_sell(code, portfolio, position_info, rt_df, bias_th_map):
    """只判断止盈/止损。对应 should_sell()，返回 (bool, reason)。"""
    pos = portfolio.position(code)
    if pos is None or pos['total_amount'] <= 0:
        return False, ''
    entry_price = pos['avg_cost']
    if entry_price is None or entry_price <= 0:
        return False, ''

    price_map = dict(zip(rt_df['code'], rt_df['price'])) if not rt_df.empty else {}
    last_raw = price_map.get(code)
    if last_raw is None or last_raw <= 0:
        return False, ''

    # 用 T-1 及之前 20 日均线算乖离（fq='pre' 对应前复权，这里用原始序列）
    need = cfg.BIAS_BUY_DAYS + 1
    close_pre = ind.get_close_series(code, need, include_today=True, today_price=last_raw)
    if close_pre is None or len(close_pre) < need:
        return False, ''
    ma20 = float(close_pre.rolling(cfg.BIAS_BUY_DAYS).mean().iloc[-1])
    if ma20 <= 0:
        return False, ''
    last_pre = float(close_pre.iloc[-1])
    bias20 = (last_pre / ma20 - 1) * 100

    ret = last_raw / entry_price - 1.0

    if cfg.STOP_LOSS_PCT and ret <= -cfg.STOP_LOSS_PCT:
        return True, '深套止损'
    if cfg.SELL_BIAS_TH is not None and bias20 >= cfg.SELL_BIAS_TH and ret >= 0:
        return True, '回本止盈'
    if cfg.SELL_PROFIT_PCT and ret >= cfg.SELL_PROFIT_PCT:
        return True, '目标收益'
    return False, ''


def check_trailing_protect(code, portfolio, position_info, rt_df):
    """★ 移动止盈 + 保本止损（2026-11-04 已通过 config 归零，等效关闭）。

    🔴 历史说明：这两个函数体保留，但 TRAIL_STOP_PCT / BREAKEVEN_STOP_PCT 已置 0，
       函数会在下面第 3 行直接 return False，不参与任何决策。
       归零依据见 config.py 的注释块（原版 39.76%/-17.95% 全面优于现行 37.21%/-18.55%；
       移动止盈 5 笔触发全部亏损，均值 -8.24%）。

    旧设计意图（已作废，仅留档）：
      ① 保本止损：浮盈曾达 X% ⇒ 激活；之后回落到成本价（ret<=0）就卖。
      ② 移动止盈：自持仓期最高收盘价回撤超过 X% 即卖。
      实测这两条在 A 股 ETF 上不成立：peak 基本等于成本价，所谓"回撤 8%"
      实际是"从成本跌 8%"，等于把一次 -15% 止损拆成多次 -8% 止损。

    状态（peak_price / be_armed）仍由 position_store 落盘，归零后不再被读取。
    返回 (bool, reason)。
    """
    trail = float(getattr(cfg, 'TRAIL_STOP_PCT', 0) or 0)
    be_trig = float(getattr(cfg, 'BREAKEVEN_STOP_PCT', 0) or 0)
    if trail <= 0 and be_trig <= 0:
        return False, ''

    # ★ 时间护栏：保护位只认「尾盘快照」。
    #   回测对照：按盘中最低价触发 16.02%/-27.59%，按收盘价触发 38.03%/-18.37%，差 22pp。
    #   暴跌日盘中插针会把「暂时下探」判成「趋势破位」，这是本策略最贵的单点错误。
    #   故 14:40 之前（含手工提前运行）一律不判保护位。
    earliest = str(getattr(cfg, 'PROTECT_EARLIEST_TIME', '') or '')
    if earliest and _dt.datetime.now().strftime('%H:%M') < earliest:
        return False, ''

    pos = portfolio.position(code)
    if pos is None or pos.get('total_amount', 0) <= 0:
        return False, ''
    entry = pos.get('avg_cost')
    if not entry or entry <= 0:
        return False, ''

    price_map = dict(zip(rt_df['code'], rt_df['price'])) if not rt_df.empty else {}
    price = price_map.get(code)
    if price is None or price <= 0:
        return False, ''

    ret = price / entry - 1.0
    info = position_info.setdefault(code, {})
    peak = float(info.get('peak_price') or entry)
    if price > peak:
        peak = price
    info['peak_price'] = peak

    # ① 保本止损
    if be_trig > 0:
        if ret >= be_trig:
            info['be_armed'] = True
        if info.get('be_armed') and 0 >= ret > -cfg.STOP_LOSS_PCT:
            return True, '保本止损'

    # ② 移动止盈
    if trail > 0 and peak > 0:
        if price / peak - 1.0 <= -trail and ret > -cfg.STOP_LOSS_PCT:
            return True, '移动止盈'

    return False, ''


def held_days(code, position_info, today) -> int:
    """已持有交易日数。对应 _held_days()。"""
    info = position_info.get(code)
    entry_date = info.get('entry_date') if info else None
    if not entry_date:
        return None
    dates = get_trade_dates(start_date=entry_date, end_date=today)
    return max(len(dates) - 1, 0)


# ==================================================
# 可交易判断（涨停/跌停/停牌）
# ==================================================
def can_buy(code, rt_row, last_close=0.0) -> bool:
    """对应 _can_buy()。ETF 涨跌幅限制 10%（部分 20%，这里统一按 10% 保守判断）。"""
    if rt_row is None:
        return False
    if bool(rt_row.get('paused', False)):
        return False
    price = float(rt_row.get('price', 0) or 0)
    lc = float(rt_row.get('last_close', 0) or 0)
    if price <= 0:
        return False
    if lc > 0 and price >= lc * 1.099:
        return False
    return True


def can_sell(code, rt_row) -> bool:
    """对应 _can_sell()。"""
    if rt_row is None:
        return False
    if bool(rt_row.get('paused', False)):
        return False
    price = float(rt_row.get('price', 0) or 0)
    lc = float(rt_row.get('last_close', 0) or 0)
    if price <= 0:
        return False
    if lc > 0 and price <= lc * 0.901:
        return False
    return True


def cap_by_liquidity(code, buy_value, rt_row):
    """★ 容量看守：单笔不超过「当日成交额 × MAX_POS_PCT_OF_AMOUNT」，超出则缩量。

    为什么要缩量而不是跳过：
      · 跳过 = 用流动性做择时（实测把年化从 41.5% 打到 36.1%）；
      · 缩量只降低冲击成本，不改变选股结果，是单向风险。
    依据：回测后期单笔 65 万已占当日成交额 4.16%，是 1% 经验上限的 4 倍。
    """
    pct = float(getattr(cfg, 'MAX_POS_PCT_OF_AMOUNT', 0) or 0)
    # ★ 2026-11-05 修复：rt_row 常为 pandas Series，`not rt_row` 会抛
    #   "truth value of a Series is ambiguous"，导致整条买入路径中断。
    if pct <= 0 or rt_row is None:
        return buy_value
    amt = float(rt_row.get('amount', 0) or 0)
    if amt <= 0:
        return buy_value
    cap = amt * pct
    if buy_value > cap:
        print(f"[容量] {code} 当日成交额 {amt / 1e4:.0f} 万 × {pct * 100:.1f}% = "
              f"{cap / 1e4:.1f} 万 ＜ 拟买 {buy_value / 1e4:.1f} 万 → 按上限缩量")
        return cap
    return buy_value


# ==================================================
# 外部情绪信号（天基营 API）
# ==================================================
# 天基营接口说明（实测）：
#   GET /api/signals/today            → 只返回"今天"是否已发布
#   GET /api/signals/{YYYY-MM-DD}     → 精确查询指定交易日（交易日才 200，非交易日 404）
#   返回体 data 字段：duokong1 / newDuokong1 / duokong2 / midStrength / longCycle ...
# 策略真正使用的是 newDuokong1（"做多"→long；"空仓"→flat）
def _fetch_signal_by_date(date_str):
    """按交易日精确查询天基营信号。
    返回 dict 或 None（该日未发布/非交易日）。"""
    url = f"{cfg.EXTERNAL_API_BASE}/{date_str}"
    try:
        req = urllib.request.Request(url)
        req.add_header('X-API-Key', cfg.EXTERNAL_API_KEY)
        with urllib.request.urlopen(req, timeout=cfg.EXTERNAL_TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None          # 非交易日，无记录
        print(f"[外部信号] {date_str} HTTP {e.code}")
        return None
    except Exception as e:
        print(f"[外部信号] {date_str} 请求异常: {e}")
        return None

    if not data.get('ok'):
        return None
    row = data.get('data')
    if isinstance(row, list):
        row = row[-1] if row else None
    return row if isinstance(row, dict) else None


def fetch_external_signal(today=None, with_detail=False):
    """对应 fetch_external_signal()。

    返回 'long' / 'flat' / 'unpublished' / None
      - long        : 天基营 newDuokong1 == '做多'
      - flat        : 天基营 newDuokong1 == '空仓'
      - unpublished : 今日（或回溯到）无发布记录
      - None        : 请求/解析异常

    逻辑：先查 today；若今天没发布（例如 14:45 时尚未更新），
    自动向前回溯最近一个已发布的交易日信号，并把信号日期一并返回。

    with_detail=True 时返回 dict：
      {'signal': ..., 'date': 信号所属日期, 'today': 查询日期, 'staleness': 相差天数}
    """
    if today is None:
        today = _dt.date.today()
    elif isinstance(today, str):
        today = _dt.date.fromisoformat(today)

    key = (today, with_detail)
    if key in _external_signal_cache:
        return _external_signal_cache[key]

    def _wrap(sig, sig_date):
        if with_detail:
            staleness = (today - sig_date).days if sig_date else None
            out = {'signal': sig, 'date': sig_date.isoformat() if sig_date else None,
                   'today': today.isoformat(), 'staleness': staleness}
        else:
            out = sig
        _external_signal_cache[key] = out
        return out

    if not cfg.ENABLE_EXTERNAL_STRATEGY or not cfg.EXTERNAL_API_KEY:
        return _wrap('disabled', None)

    # 当日 → 向前回溯最多 12 个自然日（覆盖周末 + 假期）
    cur = today
    for _ in range(13):
        row = _fetch_signal_by_date(cur.strftime('%Y-%m-%d'))
        if row is not None:
            val = row.get(cfg.EXTERNAL_SIGNAL_FIELD)
            if val is None:
                return _wrap(None, cur)
            sig = 'long' if str(val).strip() == cfg.EXTERNAL_SIGNAL_LONG else 'flat'
            tag = '今日' if cur == today else f'回溯至{cur}'
            print(f"[外部信号·API] {tag} {cfg.EXTERNAL_SIGNAL_FIELD}={val} → {sig}")
            return _wrap(sig, cur)
        cur -= _dt.timedelta(days=1)

    print("[外部信号·API] 近13天均无发布记录")
    return _wrap('unpublished', None)


# ==================================================
# 14:50 计算信号
# ==================================================
def compute_signals(g: G, today, rt_df):
    """对应 compute_signals()。"""
    g.pending_signals = None
    if not g.etf_pool:
        return

    bias_df = ind.calculate_bias(g.etf_pool, rt_df)
    if bias_df.empty:
        print("[信号] 乖离率计算为空")
        return

    # 补充名称
    name_map = dict(zip(rt_df['code'], rt_df.get('name', pd.Series(dtype=str))))
    bias_df['名称'] = bias_df['代码'].map(lambda c: name_map.get(c, c))
    bias_df = bias_df.sort_values(by='50日乖离率(%)', ascending=True).reset_index(drop=True)
    bias_df.insert(0, '排名', range(1, len(bias_df) + 1))

    buy_candidates = []
    for _, row in bias_df.iterrows():
        code = row['代码']
        try:
            if ind.check_oversold_stabilized(code, rt_df, g.etf_buy_bias_th_map):
                buy_candidates.append({
                    'code': code,
                    'name': row['名称'],
                    'bias50': row['50日乖离率(%)'],
                })
        except Exception:
            continue

    g.pending_signals = {
        'date': today,
        'bias_df': bias_df,
        'buy_candidates': buy_candidates,
    }
    print(f"[信号] 池子{len(g.etf_pool)}只，有乖离率{len(bias_df)}只，候选{len(buy_candidates)}只")
    return bias_df


# ==================================================
# 14:55 统一交易
# ==================================================
def execute_trades(g: G, portfolio: Portfolio, today, rt_df):
    """对应 execute_trades()。决策树完全一致。"""
    signals = g.pending_signals
    if not signals or signals.get('date') != today:
        return

    bias_df = signals.get('bias_df', pd.DataFrame())
    buy_candidates = signals.get('buy_candidates', [])
    first_cand_code = buy_candidates[0]['code'] if buy_candidates else None
    has_bias_signal = len(buy_candidates) > 0

    ext_signal = fetch_external_signal(today)

    rt_map = {r['code']: r for _, r in rt_df.iterrows()} if not rt_df.empty else {}
    price_map = {c: r['price'] for c, r in rt_map.items()}
    holdings = {c: p for c, p in portfolio.positions.items() if p['total_amount'] > 0}

    for code in list(g.position_info.keys()):
        if code not in holdings:
            g.position_info.pop(code, None)
            g.position_source.pop(code, None)

    # ---------- 0. ★ v4.2.0 盘中止损：先用实时价扫一遍，不等尾盘 ----------
    sold_codes = set()
    for act in intraday_stop_scan(g, portfolio, rt_df, today):
        sold_codes.add(act['code'])
    if sold_codes:
        holdings = {c: p for c, p in portfolio.positions.items() if p['total_amount'] > 0}

    # ---------- 1. 卖出 ----------
    for code in list(holdings.keys()):
        source = g.position_source.get(code, 'bias')
        reason = None

        if source == 'bias':
            # ★ 2026-10-22：先查移动止盈 / 保本止损（风险控制，不受候选否决）
            protect, pr = check_trailing_protect(code, portfolio, g.position_info, rt_df)
            if protect:
                reason = pr
                if not can_sell(code, rt_map.get(code)):
                    continue
                portfolio.order_target_value(code, 0, price_map, reason=reason)
                g.position_info.pop(code, None)
                g.position_source.pop(code, None)
                sold_codes.add(code)
                print(f"[卖出·保护] {code} 原因={reason}")
                continue

            sell, r = should_sell(code, portfolio, g.position_info, rt_df,
                                  g.etf_buy_bias_th_map)
            if sell:
                if r not in ('深套止损',):
                    if first_cand_code == code:
                        print(f"[继续持有] {code} 触发{r}，候选最优仍是自己")
                        continue
                reason = r
            else:
                if not (cfg.ENABLE_HOLD_MAX_DAYS and cfg.HOLD_MAX_DAYS):
                    continue
                held = held_days(code, g.position_info, today)
                if held is None or held < cfg.HOLD_MAX_DAYS:
                    continue
                if first_cand_code:
                    if first_cand_code == code:
                        print(f"[时间到期·保持] {code} 已持{held}日，但仍是候选第一")
                        continue
                    reason = f'时间到期换仓→{first_cand_code}'
                elif ext_signal == 'long':
                    if code == cfg.EXTERNAL_TARGET_CODE:
                        continue
                    reason = '时间到期→外部做多信号'
                elif ext_signal == 'flat':
                    reason = '时间到期→空仓'
                else:
                    continue
        else:
            # 外部持仓
            if has_bias_signal and first_cand_code != code:
                reason = f'抄底信号({first_cand_code})，切换'
                print(f"[主动切换] 外部持仓{code} → 抄底候选{first_cand_code}")
            elif ext_signal == 'flat':
                reason = '外部信号转空'
            else:
                continue

        if reason is None:
            continue
        if not can_sell(code, rt_map.get(code)):
            continue
        portfolio.order_target_value(code, 0, price_map, reason=reason)
        g.position_info.pop(code, None)
        g.position_source.pop(code, None)
        sold_codes.add(code)
        print(f"[卖出·{source}] {code} 原因={reason}")

    # ---------- 2. 买入 ----------
    # ★ v4.2.0 冷却闸门：止损后 N 个交易日内不开新仓（否则当天回补=继续接刀）
    cd, gap, last_stop = in_stop_cooldown(today, g)
    if cd:
        print(f"[冷却] 距上次止损({last_stop})仅 {gap} 个交易日 < {cfg.STOP_COOLDOWN_DAYS}，今日不开新仓")
        return

    current_hold = len([c for c, p in portfolio.positions.items() if p['total_amount'] > 0])
    if current_hold >= cfg.MAX_HOLD:
        return

    # 2.1 抄底候选优先
    for cand in buy_candidates:
        code = cand['code']
        if code in sold_codes:
            continue
        pos = portfolio.position(code)
        if pos is not None and pos['total_amount'] > 0:
            continue
        if not can_buy(code, rt_map.get(code)):
            continue
        buy_value = portfolio.available_cash * 0.995
        buy_value = cap_by_liquidity(code, buy_value, rt_map.get(code))
        if buy_value <= 0:
            break
        portfolio.order_target_value(
            code, buy_value, price_map,
            reason='抄底候选#%d bias50=%+.2f%%' % (
                buy_candidates.index(cand) + 1, cand.get('bias50', 0)))
        pos_after = portfolio.position(code)
        px = pos_after['avg_cost'] if pos_after else price_map.get(code)
        if px:
            g.position_info[code] = {'entry_price': px, 'entry_date': today}
            g.position_source[code] = 'bias'
        print(f"[买入·抄底] {code} {cand['name']} bias50={cand['bias50']:.2f}")
        return

    # 2.2 抄底无候选，看外部信号
    if ext_signal == 'long':
        code = cfg.EXTERNAL_TARGET_CODE
        if code in sold_codes:
            print(f"[交易] 外部信号=long，但 {code} 今日已卖，跳过")
            return
        if not can_buy(code, rt_map.get(code)):
            print(f"[交易] 外部信号=long，但 {code} 无法买入（涨停/停牌）")
            return
        buy_value = portfolio.available_cash * 0.995
        buy_value = cap_by_liquidity(code, buy_value, rt_map.get(code))
        if buy_value <= 0:
            return
        portfolio.order_target_value(code, buy_value, price_map,
                                     reason='天基营做多信号')
        pos_after = portfolio.position(code)
        px = pos_after['avg_cost'] if pos_after else price_map.get(code)
        if px:
            g.position_info[code] = {'entry_price': px, 'entry_date': today}
            g.position_source[code] = 'external'
        print(f"[买入·外部] {code} 华泰柏瑞中证2000ETF 外部信号=long")
        return

    if ext_signal == 'flat':
        print("[交易] 抄底无候选 + 外部=空仓，今日空仓")
