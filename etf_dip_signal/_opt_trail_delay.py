# -*- coding: utf-8 -*-
"""止损确认延迟检验：触发后等 N 天再卖，是否优于当天卖。

背景：11-03 卖 588170 @0.583，11-04 该标的 +20.03%（涨幅全在 13:00-14:45）。
7 笔亏损卖出中，T+5 全部反弹（均值 +13.25%）。
假设：止损落在急跌惯性末端，当天卖 = 卖在最低点；加一天确认可能更好。

同时做起点敏感性（2021/2022/2023），符号随起点翻转即判噪声。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

SLIP = 0.002
TRAIL = 0.08
BE = 0.03
CY = 0.025
COMM = 0.0002

_HIST = None


def load_hist():
    """一次性加载并清洗全部历史（与 _cost_ladder.py 同口径）。"""
    global _HIST
    if _HIST is not None:
        return _HIST
    raw = pd.read_parquet(os.path.join(BASE, 'data', 'etf_qfq_cifang.parquet'),
                          columns=['code', 'date', 'open', 'close', 'low'])
    raw['date'] = raw['date'].astype(str).str[:10]
    hist = {}
    for code, g in raw.groupby('code', sort=False):
        f, _ = data_quality.repair_prices(g[['date', 'open', 'close', 'low']])
        hist[code] = f.reset_index(drop=True)
    _HIST = hist
    print('  历史已加载并清洗：%d 只' % len(hist))
    return hist


def prep(start='2021-01-01', end='2026-10-20'):
    return bt1.build_matrices(load_hist(), start=start, end=end)


def run(m, **kw):
    return bt.run(m, kw.pop('th_map'), max_hold=1, intraday_stop=False,
                  exec_mode='close', cash0=100000.0, commission=COMM,
                  slippage=SLIP, trail=TRAIL, be_stop=BE, cash_yield=CY, **kw)


def pct(x):
    return '%+.2f%%' % (x * 100)


def main():
    import json
    pool = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'),
                          encoding='utf-8'))
    bmap = pool['bmap']

    print('=' * 96)
    print('【一】止损确认延迟（主窗口 2021-01-01 ~ 2026-10-20）')
    print('=' * 96)
    m = prep()
    th_map = dict((c, bmap.get(c, -16)) for c in m['codes'])

    res = {}
    for d in (0, 1, 2, 3):
        r = run(m, th_map=th_map, trail_delay=d)
        p = bt1.perf(r['equity'], r['trades'], cash0=100000.0,
                     exposure=r['exposure'])
        p['calmar'] = p['cagr'] / abs(p['max_dd']) if p['max_dd'] else 0.0
        sells = r['trades'][r['trades']['action'] == 'sell']
        dist = dict(sells['reason'].value_counts()) if len(sells) else {}
        res[d] = p
        print('  delay=%d ｜ 年化 %s ｜ 回撤 %6.2f%% ｜ Calmar %.2f ｜ 夏普 %.2f ｜ 交易 %d ｜ %s'
              % (d, pct(p['cagr']), p['max_dd'] * 100, p['calmar'], p['sharpe'],
                 len(r['trades']) // 2, dist))

    print()
    print('=' * 96)
    print('【二】起点敏感性（防"方向假"）')
    print('=' * 96)
    for start in ('2021-01-01', '2022-01-01', '2023-01-01'):
        try:
            mm = prep(start=start)
        except Exception as e:
            print('  %s 取数失败：%s' % (start, str(e)[:80]))
            continue
        th2 = dict((c, bmap.get(c, -16)) for c in mm['codes'])

        def _p(d):
            r = run(mm, th_map=th2, trail_delay=d)
            q = bt1.perf(r['equity'], r['trades'], cash0=100000.0,
                         exposure=r['exposure'])
            q['calmar'] = q['cagr'] / abs(q['max_dd']) if q['max_dd'] else 0.0
            return q

        base = _p(0)
        line = '  %s ｜ 基准 %s / %6.2f%%' % (start, pct(base['cagr']),
                                              base['max_dd'] * 100)
        for d in (1, 2, 3):
            p = _p(d)
            line += ' ｜ d%d %s(%+.2fpp)' % (d, pct(p['cagr']),
                                             (p['cagr'] - base['cagr']) * 100)
        print(line)

    print()
    print('=' * 96)
    print('【三】逐年（delay=0 vs delay=1）')
    print('=' * 96)
    r0 = run(m, th_map=th_map, trail_delay=0)
    r1 = run(m, th_map=th_map, trail_delay=1)
    e0 = pd.Series(r0['equity'], index=pd.to_datetime(m['dates'])).dropna()
    e1 = pd.Series(r1['equity'], index=pd.to_datetime(m['dates'])).dropna()
    print('  %-6s %12s %12s %10s' % ('年份', 'delay=0', 'delay=1', '差'))
    for y in sorted(set(e0.index.year)):
        a = e0[e0.index.year == y]
        b = e1[e1.index.year == y]
        if len(a) < 2 or len(b) < 2:
            continue
        ra = a.iloc[-1] / a.iloc[0] - 1
        rb_ = b.iloc[-1] / b.iloc[0] - 1
        print('  %-6d %11.2f%% %11.2f%% %+9.2fpp' % (y, ra * 100, rb_ * 100,
                                                     (rb_ - ra) * 100))


if __name__ == '__main__':
    main()
