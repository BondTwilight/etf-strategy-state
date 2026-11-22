# -*- coding: utf-8 -*-
"""
position_store.py —— 持仓状态持久化 + 每日快照

为什么需要：
  聚宽策略是常驻进程，靠内存 g.position_info / g.position_source 跨天记住持仓；
  本复刻版的定时任务是【无状态】的——每次运行都是全新进程，若不落盘，"上一个
  交易日收盘时持有什么"（source=抄底/天基营、entry_date=持有起点）就会丢失，
  导致买卖逻辑（持有天数、换仓、止损止盈、抄底↔天基营切换）无法正确判断。

文件：
  data/positions.json          当前实时持仓（positions_tool.py 手动维护，单条真实持仓）
  data/position_snapshots.json 每个交易日的持仓快照（本模块自动记录，跨天回溯用）

快照语义：
  「日期 D 的快照」= 交易日 D 决策时点的持仓（策略固定 14:40 决策、当日收盘前成交），
  等价于 D 收盘后的持仓基线。下一交易日运行时读「D 的快照」即得到"上一交易日收盘持仓"。
"""

import os
import json
import datetime as _dt

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
SNAPSHOT_FILE = os.path.join(DATA, 'position_snapshots.json')


# ==================================================
# 快照读写
# ==================================================
def load_snapshots() -> dict:
    """读取全部快照。返回 {date_str: {code: position}}，无则 {}。"""
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_snapshots(snaps: dict) -> None:
    os.makedirs(DATA, exist_ok=True)
    with open(SNAPSHOT_FILE, 'w', encoding='utf-8') as f:
        json.dump(snaps, f, ensure_ascii=False, indent=2)


def record_snapshot(date_str: str, positions: dict) -> None:
    """记录某交易日的持仓快照（幂等覆盖，重复运行不产生脏数据）。"""
    snaps = load_snapshots()
    snaps[date_str] = positions or {}
    save_snapshots(snaps)


def get_snapshot(date_str: str) -> dict:
    """读取某交易日的持仓快照，无则返回 {}。"""
    return load_snapshots().get(date_str, {})


def get_prev_snapshot(today_str: str, trade_dates=None):
    """返回上一交易日的 (date_str, positions)。

    trade_dates 为升序交易日列表（缺省时用 tdx_api 上证指数日历）。
    - 今天在日历中 → 上一交易日 = 倒数第二个
    - 今天不在日历中（周末/节假日）→ 上一交易日 = 最后一个
    """
    if trade_dates is None:
        try:
            from tdx_api import get_trade_dates
            trade_dates = get_trade_dates(end_date=today_str)
        except Exception:
            trade_dates = []
    if not trade_dates:
        return None, {}
    if trade_dates[-1] == today_str:
        prev = trade_dates[-2] if len(trade_dates) >= 2 else None
    else:
        prev = trade_dates[-1]
    if prev is None:
        return None, {}
    return prev, get_snapshot(prev)


# ==================================================
# 持仓 → 买卖状态
# ==================================================
def positions_to_state(positions: dict):
    """把 positions.json 的持仓映射成 engine 买卖逻辑所需的三份状态。

    返回 (portfolio_positions, position_info, position_source)：
      portfolio_positions : {code: {total_amount, avg_cost}}   → Portfolio.positions
      position_info       : {code: {entry_price, entry_date}}  → G.position_info
      position_source     : {code: 'bias'|'external'}          → G.position_source
    """
    portfolio_pos = {}
    position_info = {}
    position_source = {}
    for code, p in (positions or {}).items():
        if not isinstance(p, dict):
            continue
        amount = float(p.get('total_amount', 0) or 0)
        if amount <= 0:
            continue
        cost = float(p.get('avg_cost', 0) or 0)
        source = p.get('source', 'bias')
        entry_date = p.get('entry_date', '')
        portfolio_pos[code] = {'total_amount': amount, 'avg_cost': cost}
        position_info[code] = {'entry_price': cost, 'entry_date': entry_date}
        # ★ 2026-10-22：移动止盈 / 保本止损需要跨日记住「持仓期最高价」与「保本已激活」
        if p.get('peak_price'):
            position_info[code]['peak_price'] = float(p['peak_price'])
        if p.get('be_armed'):
            position_info[code]['be_armed'] = bool(p['be_armed'])
        position_source[code] = source
    return portfolio_pos, position_info, position_source


def state_to_positions(portfolio_positions: dict, position_info: dict, position_source: dict) -> dict:
    """反向映射：决策后的状态 → positions.json 结构。

    输入为 engine 买卖逻辑跑完后的 (Portfolio.positions, G.position_info, G.position_source)，
    输出可写回 positions.json / 快照的 {code: {total_amount, avg_cost, entry_date, source}}。
    """
    out = {}
    for code, p in (portfolio_positions or {}).items():
        if not isinstance(p, dict):
            continue
        amt = float(p.get('total_amount', 0) or 0)
        if amt <= 0:
            continue
        info = (position_info or {}).get(code, {}) or {}
        out[code] = {
            'total_amount': amt,
            'avg_cost': float(p.get('avg_cost', 0) or 0),
            'entry_date': info.get('entry_date', ''),
            'source': (position_source or {}).get(code, 'bias'),
        }
        # ★ 2026-10-22：回写保护位状态，供下一交易日续用
        if info.get('peak_price'):
            out[code]['peak_price'] = float(info['peak_price'])
        if info.get('be_armed'):
            out[code]['be_armed'] = True
    return out


def write_positions(positions: dict) -> None:
    """把决策后持仓写回 data/positions.json（只写纯持仓字段，剥离浮盈快照）。

    ★ 这是策略"自维护持仓"的闭环关键：每次跑完买卖决策后调用，
      下次运行的 load_positions() 读到的即"上一交易日收盘持仓"。
    """
    clean = {}
    for code, p in (positions or {}).items():
        if not isinstance(p, dict):
            continue
        amt = float(p.get('total_amount', 0) or 0)
        if amt <= 0:
            continue
        clean[code] = {
            'total_amount': amt,
            'avg_cost': float(p.get('avg_cost', 0) or 0),
            'entry_date': p.get('entry_date', ''),
            'source': p.get('source', 'bias'),
        }
        # ★ 2026-10-22：保护位状态必须落盘，否则每次运行 peak 从成本价重算，
        #   移动止盈永远触发不了（这是活到线上的关键一步）
        if p.get('peak_price'):
            clean[code]['peak_price'] = float(p['peak_price'])
        if p.get('be_armed'):
            clean[code]['be_armed'] = True
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, 'positions.json'), 'w', encoding='utf-8') as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)


def enrich_positions(positions: dict, rt_prices: dict) -> dict:
    """给持仓 dict 附加 last_price（记录时刻实时价）与 pnl_pct（浮盈比例%）。

    ★ 止盈/止损/回本判断里的"盈亏比例"是实时算的（实时价 ÷ 成本 - 1），本不需要存；
      这里顺手记录，是为了让快照自包含"记录时刻赚/亏多少"，便于事后诊断与回溯。
    """
    out = {}
    for code, p in (positions or {}).items():
        if not isinstance(p, dict):
            continue
        rec = dict(p)
        cost = float(p.get('avg_cost', 0) or 0)
        px = rt_prices.get(code)
        if px is not None and cost > 0:
            rec['last_price'] = round(float(px), 4)
            rec['pnl_pct'] = round((float(px) / cost - 1) * 100, 4)
        out[code] = rec
    return out


def describe_positions(positions: dict) -> str:
    """把持仓 dict 转成一行可读文本，用于信号展示/日志。"""
    if not positions:
        return "（空仓）"
    parts = []
    for code, p in positions.items():
        if not isinstance(p, dict):
            continue
        amt = p.get('total_amount', 0)
        if float(amt or 0) <= 0:
            continue
        src = p.get('source', 'bias')
        src_txt = '抄底' if src == 'bias' else ('天基营' if src == 'external' else src)
        pnl = p.get('pnl_pct')
        pnl_txt = f" 浮盈{pnl:+.2f}%" if pnl is not None else ""
        parts.append(f"{code}({src_txt}@{p.get('entry_date', '?')},{amt}份{pnl_txt})")
    return "、".join(parts) if parts else "（空仓）"
