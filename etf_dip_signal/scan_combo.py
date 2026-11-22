# -*- coding: utf-8 -*-
"""分仓 × 移动止盈 组合（线上口径），给出可选的两条落地路线"""
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

for wname, start in [('主窗口 2021起', '2021-01-01'), ('长窗口 2016起', '2016-01-01')]:
    m = bt1.build_matrices(hist, start=start, end='2026-10-20')
    print('\n' + '=' * 100)
    print('%s' % wname)
    print('=' * 100)
    print('  %-26s %9s %9s %9s %8s %8s %7s %10s' % (
        '组合', '年化', '最大回撤', 'Calmar', '夏普', '胜率', '交易', '剔最强年后化'))
    for mh in (1, 2):
        for tr, lbl in ((None, '原止盈'), (0.08, '移动止盈8%')):
            r = bt.run(m, BMAP, max_hold=mh, intraday_stop=True, exec_mode='close',
                       timeout_live=True, trail=tr)
            p = bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])
            ret = p['equity'].pct_change().fillna(0.0)
            by = ret.groupby(ret.index.year).apply(lambda s: (1 + s).prod() - 1)
            best = by.idxmax()
            r2 = ret[ret.index.year != best]
            c2 = (1 + r2).cumprod().iloc[-1] ** (252.0 / max(len(r2), 1)) - 1
            print('  %-26s %8.2f%% %8.2f%% %8.2f %8.2f %7.1f%% %7d %9.2f%%' % (
                '%d仓 · %s' % (mh, lbl), p['cagr'] * 100, p['max_dd'] * 100,
                p['calmar'], p['sharpe'],
                p['win_rate'] * 100 if np.isfinite(p['win_rate']) else -1,
                p['trades'], c2 * 100))
