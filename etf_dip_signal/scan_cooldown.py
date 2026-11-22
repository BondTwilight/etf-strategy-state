# -*- coding: utf-8 -*-
"""STOP_COOLDOWN_DAYS 离散操作点扫描（改参数前的稳健性检验）

项目铁律：单点好看不算数，必须给「离散操作点结构」+「剔除最强单年」。
若最优值只是孤立尖峰 → 不可信；若落在平台区间 → 可信。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cifang_api
import bt_etf_dip as bt
import data_quality

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, 'data', 'etf_qfq_cifang.parquet')
CASH0 = 100000.0

d = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'), encoding='utf-8'))
CODES, BMAP = d['codes'], {str(k): int(v) for k, v in d['bmap'].items()}

hist = cifang_api.fetch_pool_history(CODES, cache_path=CACHE)
hist, _ = data_quality.audit(hist, verbose=False)

SCAN = [0, 1, 2, 3, 5, 10]
WINDOWS = [('主窗口 2021起', '2021-01-01', '2026-10-20'),
           ('长窗口 2016起', '2016-01-01', '2026-10-20')]


def drop_best_year(p):
    eq = p['equity']
    ret = eq.pct_change().fillna(0.0)
    by = ret.groupby(ret.index.year).apply(lambda s: (1 + s).prod() - 1)
    best = by.idxmax()
    r2 = ret[ret.index.year != best]
    eq2 = (1 + r2).cumprod()
    return eq2.iloc[-1] ** (252.0 / max(len(r2), 1)) - 1, best


for wname, start, end in WINDOWS:
    m = bt.build_matrices(hist, start=start, end=end)
    print('\n' + '=' * 96)
    print('%s ｜ 交易日 %d ｜ 起点在世 %d 只' % (
        wname, len(m['dates']), int(np.isfinite(m['close'][0]).sum())))
    print('=' * 96)
    for mode, lbl in [(True, 'V2 盘中止损'), (False, 'V1 收盘(无盘中止损)')]:
        print('\n  【%s】冷却天数 → 绩效' % lbl)
        print('    %-6s %10s %8s %9s %8s %8s %8s %10s' % (
            '冷却', '总收益', '年化', '最大回撤', '夏普', 'Calmar', '交易数', '剔最强年后化'))
        for cd in SCAN:
            r = bt.run(m, BMAP, intraday_stop=mode, exec_mode='close', cooldown=cd)
            p = bt.perf(r['equity'], r['trades'], CASH0, r['exposure'])
            cagr2, best = drop_best_year(p)
            print('    %-6d %9.1f%% %7.2f%% %8.2f%% %8.2f %8.2f %8d %9.2f%%   (最强年%d)' % (
                cd, p['total_return'] * 100, p['cagr'] * 100, p['max_dd'] * 100,
                p['sharpe'], p['calmar'], p['trades'], cagr2 * 100, best))
