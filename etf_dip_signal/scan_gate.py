# -*- coding: utf-8 -*-
"""市场闸门检验：把「择时缺失」这一项单独拎出来量化

思路：策略当前没有任何市场级风控（只看个股乖离率）。这里加一个最朴素的择时闸门
     —— 池内等权指数在 N 日均线下方时不开新仓，看回撤能压多少。
若回撤显著改善 ⇒ 缺的是「市场闸门」这一环；
若几乎无改善 ⇒ 回撤主要由「单票满仓 + 盈亏比结构」造成，不是择时问题。
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

for wname, start in [('主窗口 2021起', '2021-01-01'), ('长窗口 2016起', '2016-01-01')]:
    m = bt1.build_matrices(hist, start=start, end='2026-10-20')
    print('\n' + '=' * 96)
    print('%s ｜ 交易日 %d' % (wname, len(m['dates'])))
    print('=' * 96)
    print('  %-28s %9s %9s %9s %8s %7s %7s' % (
        '口径', '年化', '最大回撤', 'Calmar', '夏普', '交易', '持仓日占比'))
    cases = [
        ('无闸门（现状）', dict()),
        ('池等权 > MA120 才开仓', dict(market_gate_ma=120)),
        ('池等权 > MA200 才开仓', dict(market_gate_ma=200)),
        ('无闸门 + 移动止盈8%', dict(trail=0.08)),
        ('MA200闸门 + 移动止盈8%', dict(market_gate_ma=200, trail=0.08)),
    ]
    for name, kw in cases:
        r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode='close',
                   timeout_live=True, **kw)
        p = bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])
        print('  %-28s %8.2f%% %8.2f%% %8.2f %8.2f %7d %6.1f%%' % (
            name, p['cagr'] * 100, p['max_dd'] * 100, p['calmar'], p['sharpe'],
            p['trades'], p['exposure'] * 100))
