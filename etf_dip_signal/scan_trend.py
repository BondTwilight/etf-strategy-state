# -*- coding: utf-8 -*-
"""入场质量检验：TREND_FILTER_MODE 0/1/2/3 + 组合

分发包自带「右侧确认」开关（TREND_FILTER_MODE），出厂为 0（关闭）。
它修饰的是**入场**而不是出场，因此是唯一有可能同时改善胜率与收益的杠杆。
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

LABEL = {0: '关闭(现状)', 1: '非新低', 2: '站上5日均线', 3: '两者'}

for wname, start in [('主窗口 2021起', '2021-01-01'), ('长窗口 2016起', '2016-01-01')]:
    m = bt1.build_matrices(hist, start=start, end='2026-10-20')
    print('\n' + '=' * 106)
    print('%s' % wname)
    print('=' * 106)
    print('  %-24s %9s %9s %9s %8s %8s %7s %9s' % (
        '入场确认', '年化', '最大回撤', 'Calmar', '夏普', '胜率', '交易', '持仓日占比'))
    for tm in (0, 1, 2, 3):
        for tr, tl in ((None, ''), (0.08, ' +移动止盈8%')):
            r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode='close',
                       timeout_live=True, trend_mode=tm, trail=tr)
            if not len(r['trades']):
                print('  %-24s 无交易' % (LABEL[tm] + tl))
                continue
            p = bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])
            print('  %-24s %8.2f%% %8.2f%% %8.2f %8.2f %7.1f%% %7d %8.1f%%' % (
                LABEL[tm] + tl, p['cagr'] * 100, p['max_dd'] * 100, p['calmar'],
                p['sharpe'],
                p['win_rate'] * 100 if np.isfinite(p['win_rate']) else -1,
                p['trades'], p['exposure'] * 100))
