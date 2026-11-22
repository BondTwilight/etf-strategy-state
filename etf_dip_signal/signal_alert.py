# -*- coding: utf-8 -*-
"""
signal_alert.py —— 交易信号生成与推送（定时任务核心）
  · 14:25 --preview 预览（只写 preview_*.txt）
  · 14:40 正式运行（写 latest.txt + positions.json + 快照）

功能：
  1. 判断今天是否交易日（非交易日直接退出）
  2. 重建/复用 ETF 池（带本地缓存，避免每次全量拉取）
  3. 批量取实时行情 → 计算 20/50 日乖离率
  4. 生成抄底候选池（按 50 日乖离率升序）
  5. 取天基营外部情绪信号
  6. 读取当前持仓（positions.json，由交易执行维护）
  7. 输出「今日操作建议」
  8. 推送（邮件 / 企业微信 webhook / 写文件）

用法：
    python signal_alert.py                # 生成信号并推送
    python signal_alert.py --dry-run      # 只打印，不推送
    python signal_alert.py --top 10       # 显示候选前10名
"""

import os
import sys
import json
import argparse
import datetime as _dt

import pandas as pd

import config as cfg
import engine
import indicators as ind
import web_quote
import tdx_api
import position_store

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
POOL_CACHE = os.path.join(DATA, 'pool_cache.json')
POSITIONS_FILE = os.path.join(DATA, 'positions.json')
OUTPUT_DIR = os.path.join(BASE, '信号输出')


# ==================================================
# 交易日判断
# ==================================================
def is_trade_day(dates=None) -> bool:
    """今天是否交易日。用上证指数最新日线日期 + 实时行情双保险判断。

    ★ 修复（2026-10-13）：原实现 `return latest < today` 会把法定节假日（国庆/春节
      等落在周一~周五的日子）误判为交易日，导致节假日发出一条"假信号"邮件。
      改为：日线未到今日时，用上证指数实时行情确认——盘中必然有成交量、且最新价
      ≠昨收；节假日则无成交、最新价==昨收。
    """
    today = _dt.date.today()
    today_str = today.strftime('%Y-%m-%d')
    if dates is None:
        dates = web_quote.fetch_trade_dates(count=10)
    if not dates:
        return False
    latest = dates[-1]
    # 今天是交易日：最新K线日期 == 今天（盘中/收盘后都会返回当日）
    if latest == today_str:
        return True
    # 若今天是周末，直接否
    if today.weekday() >= 5:
        return False
    # 工作日但日线未更新到今日：可能是法定节假日，也可能是盘中数据延迟。
    # 用上证指数实时行情确认：有成交（成交量>0 或 最新价≠昨收）→ 今天在交易。
    try:
        rt = web_quote.fetch_realtime(['SH000001'])
        if not rt.empty:
            price = float(rt.iloc[0]['price'])
            last_close = float(rt.iloc[0]['last_close'])
            vol = float(rt.iloc[0]['vol'])
            if vol > 0 or (last_close > 0 and abs(price - last_close) > 1e-9):
                return True
    except Exception:
        pass
    return False


# ==================================================
# ETF 池缓存
# ==================================================
def load_pool_cache():
    if os.path.exists(POOL_CACHE):
        try:
            with open(POOL_CACHE, 'r', encoding='utf-8') as f:
                d = json.load(f)
            return d.get('codes', []), d.get('cmap', {}), d.get('bmap', {}), d.get('date', '')
        except Exception:
            pass
    return [], {}, {}, ''


def save_pool_cache(codes, cmap, bmap, date):
    os.makedirs(DATA, exist_ok=True)
    with open(POOL_CACHE, 'w', encoding='utf-8') as f:
        json.dump({'codes': codes, 'cmap': cmap, 'bmap': bmap, 'date': date},
                  f, ensure_ascii=False)


def get_pool(refresh=False):
    """获取 ETF 池。

    ★ 固定池模式（cfg.USE_FIXED_POOL=True）：直接读 data/fixed_pool.json，
      绕开 pool_cache 与动态建池，代码→大类/阈值全部写死。
    否则：默认用缓存（7天内有效），--refresh 时重建。
    """
    if getattr(cfg, 'USE_FIXED_POOL', False):
        import pool_builder
        codes, cmap, bmap, frozen = pool_builder.load_fixed_pool()
        if codes:
            return codes, cmap, bmap, frozen

    codes, cmap, bmap, d = load_pool_cache()
    today = _dt.date.today().strftime('%Y-%m-%d')
    # 缓存7天内有效
    fresh = False
    if codes and d:
        try:
            age = (_dt.date.today() - _dt.date.fromisoformat(d)).days
            fresh = age <= 7
        except Exception:
            fresh = False
    if codes and fresh and not refresh:
        return codes, cmap, bmap, d

    import pool_builder
    codes, cmap, bmap = pool_builder.build_etf_pool()
    save_pool_cache(codes, cmap, bmap, today)
    return codes, cmap, bmap, today


# ==================================================
# 持仓读取
# ==================================================
def load_positions() -> dict:
    """读取持仓。结构：
    {"510300": {"total_amount": 1000, "avg_cost": 4.0, "entry_date": "2026-10-01",
                "source": "bias"}}
    """
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def position_summary(positions: dict, rt_df: pd.DataFrame) -> list:
    """把持仓转成"带浮盈"的可读列表。"""
    price_map = dict(zip(rt_df['code'], rt_df['price'])) if not rt_df.empty else {}
    name_map = dict(zip(rt_df['code'], rt_df['name'])) if not rt_df.empty else {}
    out = []
    for code, p in positions.items():
        if p.get('total_amount', 0) <= 0:
            continue
        cur = price_map.get(code, p.get('avg_cost', 0))
        cost = p.get('avg_cost', 0)
        pnl = (cur / cost - 1) * 100 if cost > 0 else 0
        out.append({
            'code': code,
            'name': name_map.get(code, code),
            'amount': p['total_amount'],
            'avg_cost': round(cost, 4),
            'price': round(cur, 4),
            'pnl_pct': round(pnl, 2),
            'entry_date': p.get('entry_date', ''),
            'source': p.get('source', 'bias'),
        })
    return out


# ==================================================
# 信号生成
# ==================================================
def generate_signal(top=10, refresh_pool=False, force=False):
    today = _dt.date.today().strftime('%Y-%m-%d')

    # 1. 交易日
    if not force and not is_trade_day():
        return {'date': today, 'is_trade_day': False, 'msg': '今天非交易日'}
    # 2. 池子
    codes, cmap, bmap, pool_date = get_pool(refresh=refresh_pool)
    if not codes:
        return {'date': today, 'is_trade_day': True, 'error': 'ETF池为空'}

    # 3. 实时行情（池子 + 持仓 + 外部标的）
    positions = load_positions()
    watch = list(set(codes) | set(positions.keys()) | {cfg.EXTERNAL_TARGET_CODE})
    rt_df = tdx_api.get_realtime(watch)

    # 4. 乖离率
    web_quote.SRC_STATS.update({'tencent': 0, 'sina': 0})   # ★ 每轮清零，只统计本轮
    web_quote.clear_kline_cache()                           # ★ 每轮清空单轮日线缓存
    if str(getattr(cfg, 'DATA_SOURCE', 'web')).lower() == 'cifang':
        try:
            import cifang_quote
            cifang_quote.clear_cache()                      # ★ 进程内缓存每轮清零
        except Exception:
            pass
    bias_df = ind.calculate_bias(codes, rt_df)
    name_map = dict(zip(rt_df['code'], rt_df['name'])) if not rt_df.empty else {}
    if not bias_df.empty:
        bias_df['名称'] = bias_df['代码'].map(lambda c: name_map.get(c, c))
        bias_df = bias_df.sort_values('50日乖离率(%)', ascending=True).reset_index(drop=True)
        bias_df.insert(0, '排名', range(1, len(bias_df) + 1))

    # ★ 数据质量守卫（2026-10-20 新增）
    #   腾讯 qfq 被限流时脚本会静默退化到新浪「不复权」，或干脆丢掉一批标的，
    #   两者都会让乖离率失真／候选池残缺，却照样输出「看起来正常」的信号。
    #   这里把退化显式曝光，宁可报警也不要让人拿残缺数据去下单。
    data_warning = ''
    try:
        st = web_quote.SRC_STATS
        n_src = st['tencent'] + st['sina']
        cov = (len(bias_df) / len(codes)) if codes else 0.0
        qfq_ratio = (st['tencent'] / n_src) if n_src else 0.0
        src_name = str(getattr(cfg, 'DATA_SOURCE', 'web')).lower()
        if src_name == 'cifang':
            # 次方源：只要覆盖够就算健康（本身就是前复权，不存在退化问题）
            try:
                import cifang_quote
                cst = cifang_quote.stats()
            except Exception:
                cst = {}
            if cov < 0.90:
                data_warning = (f"数据覆盖不足：池子{len(codes)}只，仅算出{len(bias_df)}只乖离率"
                                f"（{cov*100:.0f}%），次方接口返回残缺（"
                                f"{cst.get('codes', '?')} 只 / {cst.get('calls', '?')} 次请求），"
                                f"本期候选池不可信")
        elif cov < 0.90:
            data_warning = (f"数据覆盖不足：池子{len(codes)}只，仅算出{len(bias_df)}只乖离率"
                            f"（{cov*100:.0f}%），行情接口疑似被限流，本期候选池残缺、不可信")
        elif n_src and qfq_ratio < 0.90:
            data_warning = (f"前复权覆盖率不足：{st['tencent']}/{n_src} 只走腾讯前复权，"
                            f"另有 {st['sina']} 只退化为新浪不复权 —— "
                            f"有分红/份额折算的标的乖离率会失真，信号仅供参考")
        if data_warning:
            print("[⚠️ 数据告警] " + data_warning)
    except Exception as e:
        print(f"[数据质量检查] 异常: {e}")

    # ★ 判定"乖离率所用实时价的时点"——这是信号新鲜度的关键
    #   规则（按优先级）：
    #     1) 若日线末根日期 == 今天 → 数据基准=今天，且为盘中实时价
    #     2) 否则若实时价 == 上一交易日收盘 → 今日尚未开盘（盘前/非交易日），基准=上一交易日
    #     3) 否则若实时价 != 上一交易日收盘 → 已开盘，实时价即当日盘中价，基准=今天
    quote_date = today
    intraday = False          # True=盘中实时价；False=上一交易日收盘价
    quote_kind = '未知'
    try:
        sample = codes[0] if codes else None
        if sample:
            kdf = tdx_api.get_daily_kline(sample, count=3)
            last_k_date = str(kdf['date'].iloc[-1])[:10] if not kdf.empty else ''
            last_close = float(kdf['close'].iloc[-1]) if not kdf.empty else None
            rt_price_map = dict(zip(rt_df['code'], rt_df['price'])) if not rt_df.empty else {}
            rt_px = rt_price_map.get(sample)
            if last_k_date == today:
                quote_date = today
                intraday = True
                quote_kind = '今日盘中实时价'
            elif (rt_px is not None and last_close is not None
                  and abs(float(rt_px) - last_close) < 1e-9):
                quote_date = last_k_date or today
                intraday = False
                quote_kind = f'{quote_date} 收盘价（尚未开盘）'
            else:
                quote_date = today
                intraday = True
                quote_kind = '今日盘中实时价'
    except Exception:
        pass

    # 5. 抄底候选
    candidates = []
    for _, row in bias_df.iterrows():
        code = row['代码']
        try:
            if ind.check_oversold_stabilized(code, rt_df, bmap):
                candidates.append({
                    'code': code,
                    'name': row['名称'],
                    'bias50': round(row['50日乖离率(%)'], 2),
                    'bias20': round(row['20日乖离率(%)'], 2),
                    '阈值': bmap.get(code, cfg.BUY_BIAS_TH),
                })
        except Exception:
            continue

    # 6. 外部情绪信号（带信号日期，未更新时回溯最近交易日）
    try:
        ext = engine.fetch_external_signal(_dt.date.today(), with_detail=True)
    except Exception as e:
        print(f"[外部信号] 获取异常: {e}")
        ext = None

    # 7. 持仓
    pos_list = position_summary(positions, rt_df)

    # 7.5 上一交易日收盘持仓快照（买卖逻辑的历史基线）
    try:
        prev_date, prev_pos = position_store.get_prev_snapshot(today)
    except Exception:
        prev_date, prev_pos = None, {}
    prev_pos_text = (position_store.describe_positions(prev_pos)
                     if prev_pos else "（空仓）")

    # 7.55 运行断档自检（2026-11-02 新增）
    #   事故：2026-10-27~10-30 连续 4 个交易日没有运行，止盈判断整段缺失，
    #   持仓一路跌到 -15.25% 才被深套止损带走（多亏约 5.5~7pp）。
    #   ★ 2026-11-04：保护位（移动止盈/保本止损）已归零回退原版，此处不再提它们。
    #   这里只负责"把断档吼出来"，不做任何自动补救——漏掉的触发无法回溯成交。
    gap_warning = ''
    try:
        # ★ 不能用 prev_date：get_prev_snapshot 返回的是「上一个交易日」（那天没跑时
        #   也会返回日历上的日期 + 空持仓），会把断档掩盖成"没断档"。
        #   这里直接读快照文件，取 < today 的实际最后记录日。
        _last = None
        _sp = os.path.join('data', 'position_snapshots.json')
        if os.path.exists(_sp):
            _all = json.load(open(_sp, encoding='utf-8'))
            _cand = sorted(k for k in _all if str(k) < str(today))
            if _cand:
                _last = _cand[-1]
        if _last:
            _tds = tdx_api.get_trade_dates(start_date=_last, end_date=today)
            missed = max(len(_tds) - 2, 0)      # 去掉 prev 与 today 两端
            if missed >= 1:
                gap_warning = (
                    f"运行断档：最后一条记录是 {_last}，其后错过 {missed} 个交易日。"
                    f"断档期间止盈判断（回本止盈 / 目标收益 +3% / 满30日换仓）未判定，"
                    f"持仓可能已越过 -15% 深套止损线——请先人工核对走势，再执行今日动作")
                print("[⚠️ 断档告警] " + gap_warning)
    except Exception as e:
        print(f"[断档自检] 异常: {e}")

    # 7.6 买卖决策树（基于当前持仓 + 当日信号，跑完整止盈止损/换仓/切换逻辑）
    trade_actions = []
    final_positions = {}
    no_action_note = ''
    try:
        tr = run_trade_decision(codes, bmap, bias_df, candidates, rt_df,
                                positions, today)
        trade_actions = tr.get('actions', [])
        final_positions = tr.get('final_positions', {})
        # ★ 无动作时说明真实原因（冷却 / 无法买入 / 无候选），不要一律说"没候选"
        if not trade_actions and not final_positions:
            if candidates:
                _g = tr.get('g')
                _msg = ''
                if _g is not None:
                    try:
                        _cd, _gap, _last = engine.in_stop_cooldown(today, _g)
                        if _cd:
                            _msg = (f"冷却期内：{_last} 刚止损，距今仅 {_gap} 个交易日 "
                                    f"< {cfg.STOP_COOLDOWN_DAYS}，按规则不开新仓")
                    except Exception:
                        pass
                no_action_note = _msg or '候选均无法买入（涨停 / 停牌 / 资金不足）'
            else:
                no_action_note = '今日无候选'
    except Exception as e:
        print(f"[买卖决策] 异常: {e}")

    # 7.7 持仓卖出条件体检（仅用于解释"为何不动仓"，不参与决策）
    try:
        hold_check = build_hold_check(pos_list, bias_df, candidates, today)
    except Exception as e:
        print(f"[持仓体检] 异常: {e}")
        hold_check = []

    # 8. 操作建议（★ 由买卖决策树结果驱动，与【今日交易动作】严格对齐）
    advice = build_advice(candidates, ext, pos_list,
                          trade_actions=trade_actions, hold_check=hold_check)
    cash_advice = build_cash_advice(trade_actions, pos_list,
                                    getattr(cfg, 'CASH_YIELD_ANNUAL', 0))

    return {
        'date': today,
        'is_trade_day': True,
        'data_warning': data_warning,
        'gap_warning': gap_warning,
        'calc_time': _dt.datetime.now().strftime('%H:%M'),
        'quote_date': quote_date,
        'intraday': intraday,
        'quote_kind': quote_kind,
        'pool_size': len(codes),
        'pool_date': pool_date,
        'candidates': candidates,
        'bias_top': (bias_df.head(top).to_dict('records') if not bias_df.empty else []),
        'external_signal': ext,
        'positions': pos_list,
        'prev_position': {'date': prev_date, 'text': prev_pos_text, 'raw': prev_pos},
        'trade_actions': trade_actions,
        'final_positions': final_positions,
        'no_action_note': no_action_note,
        'hold_check': hold_check,
        'advice': advice,
        'cash_advice': cash_advice,
    }


def run_trade_decision(codes, bmap, bias_df, candidates, rt_df, prev_positions, today):
    """基于上一交易日持仓 + 当日信号，跑 engine.execute_trades 完整买卖决策树。

    返回 dict：
      actions         : [{code, side, price, amount, value}] 本次买卖动作
      final_positions : {code: {...}} 决策后持仓（可写回 positions.json / 快照）
    """
    pp, pi, ps = position_store.positions_to_state(prev_positions or {})
    portfolio = engine.Portfolio()
    portfolio.positions = pp

    g = engine.G()
    g.etf_pool = list(codes)
    g.etf_buy_bias_th_map = dict(bmap or {})
    g.position_info = pi
    g.position_source = ps
    g.pending_signals = {
        'date': today,
        'bias_df': bias_df if bias_df is not None else pd.DataFrame(),
        'buy_candidates': candidates or [],
    }

    engine.execute_trades(g, portfolio, today, rt_df)

    actions = []
    name_map = {c['code']: c.get('name', '') for c in (candidates or [])}
    for code, p in (prev_positions or {}).items():
        if isinstance(p, dict):
            name_map.setdefault(code, p.get('name', ''))
    for t in portfolio.trades:
        actions.append({
            'code': t['code'], 'side': t['side'],
            'price': round(t['price'], 4),
            'amount': t['amount'], 'value': round(t['value'], 2),
            'reason': t.get('reason', ''),
            'name': name_map.get(t['code'], ''),
        })

    final_positions = position_store.state_to_positions(
        portfolio.positions, g.position_info, g.position_source)
    # 附带决策时点实时价与浮盈，便于写回/快照自包含盈亏
    price_map = dict(zip(rt_df['code'], rt_df['price'])) if not rt_df.empty else {}
    final_positions = position_store.enrich_positions(final_positions, price_map)

    return {'actions': actions, 'final_positions': final_positions,
            'portfolio': portfolio, 'g': g}


def build_hold_check(pos_list, bias_df, candidates, today) -> list:
    """★ 持仓卖出条件体检（仅用于解释"为何不动仓"，不参与决策）。

    口径与 engine.execute_trades / should_sell 完全一致：
      bias 持仓：深套止损(-15%) / 回本止盈(bias20≥0 且收益≥0) / 目标收益(+3%) / 持有满30个交易日换仓
      external 持仓：出现抄底候选且非本人 → 切换；外部转空 → 卖
    """
    first = candidates[0]['code'] if candidates else None
    b20_map = {}
    if bias_df is not None and not bias_df.empty:
        for _, r in bias_df.iterrows():
            b20_map[r['代码']] = r['20日乖离率(%)']

    out = []
    for p in pos_list:
        code = p['code']
        ret = p['pnl_pct'] / 100.0
        raw20 = b20_map.get(code)
        try:
            b20 = round(float(raw20), 2) if raw20 is not None and pd.notna(raw20) else None
        except Exception:
            b20 = None

        held = None
        if p.get('entry_date'):
            try:
                held = engine.held_days(code, {code: {'entry_date': p['entry_date']}}, today)
            except Exception:
                held = None

        gates = []
        if p.get('source', 'bias') == 'bias':
            gates.append({
                'name': '深套止损',
                'th': f"-{cfg.STOP_LOSS_PCT*100:.0f}%",
                'cur': f"{p['pnl_pct']:+.2f}%",
                'hit': bool(cfg.STOP_LOSS_PCT) and ret <= -cfg.STOP_LOSS_PCT,
            })
            gates.append({
                'name': '回本止盈',
                'th': f"bias20≥{cfg.SELL_BIAS_TH}%且收益≥0",
                'cur': (f"bias20 {b20:+.2f}%" if b20 is not None else "bias20未知"),
                'hit': (cfg.SELL_BIAS_TH is not None and b20 is not None
                        and b20 >= cfg.SELL_BIAS_TH and ret >= 0),
            })
            gates.append({
                'name': '目标收益',
                'th': f"+{cfg.SELL_PROFIT_PCT*100:.0f}%",
                'cur': f"{p['pnl_pct']:+.2f}%",
                'hit': bool(cfg.SELL_PROFIT_PCT) and ret >= cfg.SELL_PROFIT_PCT,
            })
            if cfg.ENABLE_HOLD_MAX_DAYS and cfg.HOLD_MAX_DAYS:
                gates.append({
                    'name': '持有到期换仓',
                    'th': f"{cfg.HOLD_MAX_DAYS}个交易日",
                    'cur': (f"{held}日" if held is not None else "买入日未知"),
                    'hit': (held is not None and held >= cfg.HOLD_MAX_DAYS
                            and first is not None and first != code),
                })
        else:
            gates.append({
                'name': '抄底信号切换',
                'th': '出现抄底候选且非本人',
                'cur': f"候选第一={first or '无'}",
                'hit': bool(first) and first != code,
            })

        out.append({
            'code': code, 'name': p.get('name', code),
            'source': p.get('source', 'bias'),
            'pnl_pct': p['pnl_pct'], 'bias20': b20, 'held': held,
            'gates': gates, 'any_hit': any(g['hit'] for g in gates),
        })
    return out


def build_cash_advice(trade_actions, pos_list, cash_yield=0.0) -> str:
    """空仓期现金管理（回测里的 cash_yield，线上必须手工执行才有）。

    回测按 2.5% 年化给闲置现金计息（约 +2.0pp/年），但线上引擎不持有账户、
    不会自动申购，所以这里只出操作指令。
    工具必须是**货币ETF**（511880 银华日利 / 511990 华宝添益 / 511360 短融），
    因为它们 **T+0**：当日卖出所得当日可用；普通债基 T+1 到账会直接错过次日买点。
    """
    buys = [a for a in (trade_actions or []) if a.get('side') == 'buy']
    apy = float(cash_yield or 0) * 100
    if buys:
        return ("有买入动作 → 若现金在货币ETF(511880/511990)里，需 15:00 前 T+0 赎回"
                "对应金额；货币ETF 卖出资金当日可用，不影响成交")
    if not pos_list:
        return (f"空仓 → 闲置现金申购 511880（银华日利），T+0 可当日卖出。"
                f"按 {apy:.1f}% 年化，空仓 1 个月≈+{apy / 12:.2f}%"
                f"（这是回测已计入、线上尚未落地的部分）")
    return "持仓中 → 剩余现金仍放货币ETF(511880)，卖出所得当日即可复投，避免空转"


def build_advice(candidates, ext, pos_list, trade_actions=None, hold_check=None) -> list:
    """生成今日操作建议。ext 为 dict：{signal, date, staleness}。

    ★★ 核心原则：操作建议以买卖决策树（trade_actions）为唯一准绳，
       与【今日交易动作】严格一致。决策树未卖出 → 建议绝不出现"切换/换仓"，
       因为 bias 持仓只有触发止盈/止损/持有到期才允许卖出（见 engine.execute_trades）。
    """
    a = []
    trade_actions = trade_actions or []
    hold_check = hold_check or []
    has_cand = len(candidates) > 0
    has_pos = len(pos_list) > 0
    ext_sig = (ext or {}).get('signal') if isinstance(ext, dict) else ext
    ext_date = (ext or {}).get('date') if isinstance(ext, dict) else None
    ext_stale = (ext or {}).get('staleness') if isinstance(ext, dict) else None
    first = candidates[0] if has_cand else None

    # ---------- 1. 决策结论（第一段，必须与【今日交易动作】一字不差地对齐）----------
    if trade_actions:
        for t in trade_actions:
            side_txt = '买入' if t['side'] == 'buy' else '卖出'
            a.append(f"【{side_txt}】{t['code']} {t['amount']}份 @ {t['price']}"
                     f"（决策树已执行，14:55 前确认）")
        if has_cand and any(t['side'] == 'buy' and t['code'] == first['code']
                            for t in trade_actions):
            a.append(f"　→ 买入依据：抄底候选第一名 {first['code']} {first['name']}"
                     f"(50日乖离 {first['bias50']}%, 20日乖离 {first['bias20']}%, 阈值 {first['阈值']}%)")
    else:
        if has_pos:
            codes = '、'.join(f"{p['code']} {p['name']}" for p in pos_list)
            a.append(f"【结论】继续持有 {codes} —— 今日未触发任何卖出条件，不换仓")
        elif has_cand:
            a.append("【结论】今日空仓 —— 有抄底候选但决策树未给出买入（冷却期/涨跌停/停牌/持仓已满）")
        else:
            a.append("【结论】空仓观望 —— 今日无抄底候选")

    # ---------- 2. 持仓卖出条件体检（解释"为什么不动"）----------
    for h in hold_check:
        gate_txt = ' ｜ '.join(
            f"{g['name']}({g['th']}) 现{g['cur']} {'✗已触发' if g['hit'] else '✓未触发'}"
            for g in h['gates']
        )
        a.append(f"【持仓体检】{h['code']} {h['name']} 浮动{h['pnl_pct']:+.2f}%")
        a.append(f"　{gate_txt}")

    # ---------- 3. 候选池（只做信息说明，不构成操作指令）----------
    if has_cand and has_pos:
        cur_codes = {p['code'] for p in pos_list}
        if first['code'] not in cur_codes:
            if trade_actions:
                a.append(f"【候选】今日抄底第一名 {first['code']} {first['name']}"
                         f"(50日乖离 {first['bias50']}%，低于阈值 {first['阈值']}%)")
            else:
                a.append(f"【候选】今日抄底第一名 {first['code']} {first['name']}"
                         f"(50日乖离 {first['bias50']}%，低于阈值 {first['阈值']}%) 数值上优于当前持仓，"
                         f"但策略规定持仓未触发卖出条件不予切换（避免无谓换手成本）")
        else:
            a.append(f"【候选】当前持仓即为抄底第一名 {first['code']} {first['name']}"
                     f"(50日乖离 {first['bias50']}%)，无需换仓")
    elif has_cand and not has_pos:
        a.append(f"【候选】空仓可买：{first['code']} {first['name']} "
                 f"(50日乖离 {first['bias50']}%, 20日乖离 {first['bias20']}%, 阈值 {first['阈值']}%)")
    elif not has_cand:
        a.append("【候选】今日无抄底候选")

    # ---------- 4. 外部情绪信号（状态说明，不覆盖持仓卖出条件）----------
    when = f"（{ext_date}）" if ext_date else ""
    stale_note = ""
    if ext_stale not in (None, 0) and ext_sig in ('long', 'flat'):
        stale_note = f" ⚠️信号为{ext_stale}个自然日前，仅供参考"
    if ext_sig == 'long':
        a.append(f"【外部】天基营=做多{when} → 仅在空仓且抄底无候选时作为买入方向"
                 f"（{cfg.EXTERNAL_TARGET_CODE} 中证2000ETF）{stale_note}")
    elif ext_sig == 'flat':
        a.append(f"【外部】天基营=空仓{when} → 仅在空仓且抄底无候选时保持空仓，"
                 f"不触发现有持仓卖出{stale_note}")
    elif ext_sig == 'unpublished':
        a.append("【外部】天基营近13天无发布记录")
    elif ext_sig == 'disabled':
        a.append("【外部】未配置天基营 API Key，已跳过外部情绪信号（不影响抄底引擎）")
    else:
        a.append("【外部】天基营信号获取异常")

    return a


# ==================================================
# 格式化输出
# ==================================================
def build_action_card(res) -> list:
    """今日操作卡：把买卖动作压成一眼能看懂、可以直接照着下单的一段。

    设计原则：
      · 有动作时只讲动作（标的/金额/份额/价格/理由/怎么下单）
      · 无动作时讲"继续持有 + 最近的触发点在哪"，让用户知道下次什么价格会动
      · 触发点按成本价估算（2026-11-04 起保护位已归零，只剩深套止损与目标收益两条价格线）
    """
    L = []
    acts = res.get('trade_actions') or []
    pos = res.get('positions') or []
    L.append('━' * 44)
    if acts:
        L.append('【今日操作】★ 照这个执行 ★')
        for a in acts:
            code = a.get('code', '')
            name = a.get('name') or code
            side = '买入' if a.get('side') == 'buy' else '卖出'
            px = float(a.get('price') or 0)
            amt = int(a.get('amount') or 0)
            val = float(a.get('value') or 0)
            L.append(f"  ▶ {side} {code} {name}")
            if side == '买入':
                L.append(f"    金额 {val:,.0f} 元 ｜ 份额 {amt:,} 份 ｜ 参考价 {px:.4f}")
            else:
                L.append(f"    份额 {amt:,} 份 ｜ 参考价 {px:.4f} ｜ 金额 {val:,.0f} 元")
            rs = a.get('reason') or ''
            if rs:
                L.append(f"    触发：{rs}")
            if px > 0:
                if side == '买入':
                    L.append(f"    下单：限价 {px*0.997:.3f} ~ {px*1.003:.3f}，"
                             f"14:50 前未成交可上调 1 tick，不追高")
                else:
                    L.append(f"    下单：限价不低于 {px*0.995:.3f}，优先成交")
    else:
        note = res.get('no_action_note') or ''
        L.append('【今日操作】无 —— 按策略什么都不用做')
        if note:
            L.append(f"  原因：{note}")
        if pos:
            for p in pos:
                cost = float(p.get('avg_cost') or 0)
                cur = float(p.get('price') or 0)
                L.append(f"  继续持有 {p.get('code','')} {p.get('name','')}")
                L.append(f"    {int(p.get('amount',0)):,} 份 ｜ 成本 {cost:.4f} ｜ "
                         f"现价 {cur:.4f} ｜ 浮盈 {p.get('pnl_pct',0):+.2f}%")
                entry = p.get('entry_date') or ''
                if entry:
                    try:
                        held = engine.held_days(p['code'], {p['code']: {'entry_date': entry}},
                                                res.get('date') or _dt.date.today().strftime('%Y-%m-%d'))
                    except Exception:
                        held = None
                    if held is not None:
                        L.append(f"    已持有 {held} 个交易日（满 {cfg.HOLD_MAX_DAYS} 日到期换仓）")
                if cost > 0 and cur > 0:
                    L.append('    两条价格线（按成本价算）：')
                    # ★ 2026-11-11 修：原逻辑不区分方向，目标线被越过时会写成
                    #   「目标收益 0.4423（还需再跌 3.4%）」——文案与事实相反。
                    #   现在按方向分别措辞：下方线（止损）/<上方线（止盈）>。
                    trig = []
                    tr = float(getattr(cfg, 'TRAIL_STOP_PCT', 0) or 0)
                    if tr > 0:
                        trig.append(('移动止盈 -%.0f%%' % (tr * 100),
                                     cost * (1 - tr), 'down'))
                    trig.append(('深套止损 -%.0f%%' % (cfg.STOP_LOSS_PCT * 100),
                                 cost * (1 - cfg.STOP_LOSS_PCT), 'down'))
                    trig.append(('目标收益 +%.0f%%' % (cfg.SELL_PROFIT_PCT * 100),
                                 cost * (1 + cfg.SELL_PROFIT_PCT), 'up'))
                    for nm2, tp, direc in trig:
                        if direc == 'down':
                            if tp < cur:
                                L.append(f"      {nm2}: {tp:.4f}"
                                         f"（还需再跌 {(1 - tp / cur) * 100:.1f}%）")
                            else:
                                L.append(f"      {nm2}: {tp:.4f}"
                                         f"（已跌破，现价比它低 {(1 - cur / tp) * 100:.1f}%）")
                        else:
                            if tp > cur:
                                L.append(f"      {nm2}: {tp:.4f}"
                                         f"（还需再涨 {(tp / cur - 1) * 100:.1f}%）")
                            else:
                                L.append(f"      {nm2}: {tp:.4f}"
                                         f"（已越过，现价比它高 {(cur / tp - 1) * 100:.1f}%）")
                    # ★ 2026-11-11：目标线越过但未卖出时，必须说明是「自我否决」而非漏判
                    if cost > 0 and cur / cost - 1 >= cfg.SELL_PROFIT_PCT:
                        L.append('    ⓘ 目标收益线已越过：若候选第一仍是自己则继续持有，'
                                 '否则卖出换仓（看下方【候选】一行）')
                    be = float(getattr(cfg, 'BREAKEVEN_STOP_PCT', 0) or 0)
                    if be > 0:
                        arm = cost * (1 + be)
                        L.append(f"      保本止损：需先涨到 {arm:.4f}（+{be*100:.0f}%）激活，"
                                 f"之后回落到 {cost:.4f}（成本）才卖")
        else:
            L.append('  当前空仓，也没有买入动作。闲置现金按【现金管理】处理（511880）。')
    L.append('━' * 44)
    return L


def format_text(res) -> str:
    if not res.get('is_trade_day'):
        return f"【{res['date']}】非交易日，无信号。"

    lines = []
    calc_time = res.get('calc_time') or _dt.datetime.now().strftime('%H:%M')
    quote_date = res.get('quote_date') or res['date']
    quote_kind = res.get('quote_kind') or '未知'
    # 标题以【行情数据日期】为准；并显式注明数据时点，避免误读
    lines.append(f"📊 量化交易信号 · 行情数据日期 {quote_date}")
    lines.append(f"（乖离率所用价格：{quote_kind} · 计算时刻 {calc_time}）")
    if res.get('data_warning'):
        lines.append(f"⚠️ {res['data_warning']}")
    if res.get('gap_warning'):
        lines.append(f"⛔ {res['gap_warning']}")
    lines.append("=" * 40)

    # ★ 操作卡：放最前面，让「今天做什么」第一屏可见
    lines.extend(build_action_card(res))
    lines.append("")

    # 抄底候选池
    lines.append(f"\n【抄底候选池】共 {len(res['candidates'])} 只")
    if res['candidates']:
        for i, c in enumerate(res['candidates'], 1):
            lines.append(f"  {i}. {c['code']} {c['name']}  "
                         f"50日乖离{c['bias50']}% / 20日乖离{c['bias20']}%")
    else:
        lines.append("  （无）")

    # 乖离率前列（观察）
    lines.append(f"\n【乖离率最低 TOP】")
    for r in res['bias_top'][:10]:
        lines.append(f"  {r['排名']}. {r['代码']} {r.get('名称', '')}  "
                     f"50日{r['50日乖离率(%)']:.2f}% / 20日{r['20日乖离率(%)']:.2f}%")

    # 外部信号（标注信号所属交易日）
    ext = res['external_signal']
    ext_sig = ext.get('signal') if isinstance(ext, dict) else ext
    ext_date = ext.get('date') if isinstance(ext, dict) else None
    ext_stale = ext.get('staleness') if isinstance(ext, dict) else None
    ext_txt = {'long': '做多 ✅', 'flat': '空仓 ⬜',
               'unpublished': '无发布记录 ⏸', 'disabled': '未配置 ⚙️',
               None: '获取异常 ⚠️'}.get(ext_sig, str(ext_sig))
    date_note = ""
    if ext_date:
        date_note = f"（信号日 {ext_date}）"
        if ext_stale not in (None, 0):
            date_note += f" ⚠️已滞后{ext_stale}天"
    lines.append(f"\n【天基营情绪信号】{ext_txt}{date_note}")

    # 上一交易日收盘持仓（持仓记录功能的展示）
    prev = res.get('prev_position') or {}
    prev_date = prev.get('date')
    lines.append(f"\n【上一交易日收盘持仓】({prev_date or '无记录'})")
    lines.append(f"  {prev.get('text', '（空仓）')}")

    # 当前持仓
    lines.append(f"\n【当前持仓】共 {len(res['positions'])} 只")
    if res['positions']:
        for p in res['positions']:
            lines.append(f"  {p['code']} {p['name']}  {p['amount']}份  "
                         f"成本{p['avg_cost']} 现价{p['price']}  "
                         f"浮动{'+' if p['pnl_pct'] >= 0 else ''}{p['pnl_pct']}%  "
                         f"[{p['source']}]")
    else:
        lines.append("  （空仓）")

    # 今日交易动作（买卖决策树结果）
    actions = res.get('trade_actions', [])
    lines.append(f"\n【今日交易动作】")
    if actions:
        for a in actions:
            side_txt = '买入' if a['side'] == 'buy' else '卖出'
            lines.append(f"  {side_txt} {a['code']} {a['amount']}份 @ {a['price']}")
    elif res.get('positions'):
        lines.append("  无（未触发卖出条件，继续持有）")
    else:
        lines.append("  无（空仓观望）")

    # 现金管理（对应回测里的空仓计息，线上需手工执行）
    if res.get('cash_advice'):
        lines.append("\n【现金管理】")
        lines.append(f"  {res['cash_advice']}")

    # 操作建议（★ 与上方交易动作严格对齐，不另起一套判断）
    lines.append(f"\n【今日操作建议】")
    for a in res['advice']:
        lines.append(f"  {a}")

    lines.append("\n" + "=" * 40)
    lines.append(f"池子{res.get('pool_size', '?')}只 · 更新于{res.get('pool_date', '?')}")
    return "\n".join(lines)


# ==================================================
# 推送
# ==================================================
def push_email(text, subject):
    """邮件推送（用 Agent Mail，见 send 逻辑说明）。"""
    print("[推送] 邮件方式需在定时任务中由智能体调用邮箱工具发送")
    return False


def push_wecom(text):
    """企业微信机器人推送。需在 config 配置 WECOM_WEBHOOK。"""
    webhook = getattr(cfg, 'WECOM_WEBHOOK', '')
    if not webhook:
        print("[推送] 未配置企业微信 webhook，跳过")
        return False
    import urllib.request
    payload = json.dumps({'msgtype': 'text', 'text': {'content': text}}).encode('utf-8')
    try:
        req = urllib.request.Request(webhook, data=payload,
                                     headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        print("[推送] 企业微信发送成功")
        return True
    except Exception as e:
        print(f"[推送] 企业微信失败: {e}")
        return False


def save_output(text, date, preview=False):
    """preview=True 时只写单独文件，**不覆盖 latest.txt**。

    14:25 预览与 14:40 正式运行会在同一天各跑一次；若预览覆盖 latest.txt，
    正式结果一旦生成失败就会把预览误当最终信号。两个文件分开更安全。
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if preview:
        p = os.path.join(OUTPUT_DIR, f'preview_{date}.txt')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(text)
        return p
    p = os.path.join(OUTPUT_DIR, f'signal_{date}.txt')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text)
    # 同时写一个 latest
    with open(os.path.join(OUTPUT_DIR, 'latest.txt'), 'w', encoding='utf-8') as f:
        f.write(text)
    return p


# ==================================================
# 主入口
# ==================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='只打印不推送')
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--refresh-pool', action='store_true', help='强制重建ETF池')
    ap.add_argument('--json', action='store_true', help='输出JSON')
    ap.add_argument('--preview', action='store_true',
                    help='14:25 预览模式：只算信号、不覆盖 latest.txt、不记影子、'
                         '不推送。用于给用户 20 分钟下单准备时间')
    args = ap.parse_args()

    res = generate_signal(top=args.top, refresh_pool=args.refresh_pool)

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return

    text = format_text(res)
    print(text)

    if res.get('is_trade_day'):
        p = save_output(text, res['date'], preview=args.preview)
        print(f"\n[已保存] {p}")
        if args.preview:
            print("[预览模式] 未写 latest.txt、未记影子、未推送；"
                  "14:40 正式运行会给出最终动作")
            return
        # ★ 影子记录：为「天基营仓位调节」积累证据（不影响任何交易逻辑）
        try:
            import shadow_gate
            row = shadow_gate.record(res)
            if row:
                print(f"[影子记录] 天基营={row['tj_signal']} 候选{row['n_cand']}只 "
                      f"动作={row['action']}")
        except Exception as _e:
            print(f"[影子记录] 跳过: {_e}")
        if not args.dry_run:
            push_wecom(text)
            # 邮件推送由定时任务的智能体完成（见 automation prompt）


if __name__ == '__main__':
    main()
