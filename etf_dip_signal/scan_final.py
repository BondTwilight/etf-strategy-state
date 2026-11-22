# -*- coding: utf-8 -*-
"""最终推荐配置的确认：移动止盈 + 保本止损 + 空仓计息 三重叠加
并做稳健性：剔除最强单年、样本前后切分。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cifang_api
import bt_multi as bt
import bt_etf_dip as bt1
import data_quality

d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
CODES, BMAP = d['codes'], {str(k): int(v) for k, v in d['bmap'].items()}
hist = cifang_api.fetch_pool_history(CODES, cache_path='data/etf_qfq_cifang.parquet')
hist, _ = data_quality.audit(hist, verbose=False)

CFG = [
    ('现状（线上）', dict()),
    ('+移动止盈8%', dict(trail=0.08)),
    ('+移动止盈8%+保本3%', dict(trail=0.08, be_stop=0.03)),
    ('+移动止盈8%+保本3%+计息2.5%', dict(trail=0.08, be_stop=0.03, cash_yield=0.025)),
]

for wname, start in [('主窗口 2021起', '2021-01-01'), ('长窗口 2016起', '2016-01-01')]:
    m = bt1.build_matrices(hist, start=start, end='2026-10-20')
    print('\n' + '=' * 104)
    print(wname)
    print('=' * 104)
    print('  %-30s %9s %9s %9s %8s %8s %7s' % (
        '配置', '年化', '最大回撤', 'Calmar', '夏普', '胜率', '交易'))
    keep = {}
    for name, kw in CFG:
        r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode='close',
                   timeout_live=True, **kw)
        p = bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])
        keep[name] = (r, p)
        print('  %-30s %8.2f%% %8.2f%% %8.2f %8.2f %7.1f%% %7d' % (
            name, p['cagr'] * 100, p['max_dd'] * 100, p['calmar'], p['sharpe'],
            p['win_rate'] * 100 if np.isfinite(p['win_rate']) else -1, p['trades']))

    print('\n  【稳健性：剔除最强单年 / 前后切分】')
    for name, (r, p) in keep.items():
        eq = p['equity']
        ret = eq.pct_change().fillna(0.0)
        by = ret.groupby(ret.index.year).apply(lambda s: (1 + s).prod() - 1)
        best = by.idxmax()
        r2 = ret[ret.index.year != best]
        c2 = (1 + r2).cumprod().iloc[-1] ** (252.0 / max(len(r2), 1)) - 1
        split = pd.Timestamp('2024-01-01')
        a, b = eq[eq.index < split], eq[eq.index >= split]

        def st(s):
            if len(s) < 2:
                return np.nan, np.nan
            y = (s.index[-1] - s.index[0]).days / 365.25
            return (s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1, (s / s.cummax() - 1).min()
        ca, da = st(a)
        cb, db = st(b)
        print('    %-30s 剔最强年(%d) %+6.2f%%（差%+5.2fpp）｜前段 %+6.1f%%/%.1f%% '
              '｜后段 %+6.1f%%/%.1f%%' % (
                  name, best, c2 * 100, (c2 - p['cagr']) * 100,
                  ca * 100, da * 100, cb * 100, db * 100))
