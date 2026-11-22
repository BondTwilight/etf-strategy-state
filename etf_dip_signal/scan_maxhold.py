# -*- coding: utf-8 -*-
"""多持仓分仓回测 + 引擎等价性校验

第一步必须先证明：新引擎 max_hold=1 与已过保真校验的单仓引擎逐笔同值。
不等价则后面所有多仓结果都不可信。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cifang_api
import bt_etf_dip as bt1
import bt_multi as bt3
import data_quality

CACHE = 'data/etf_qfq_cifang.parquet'
CASH0 = 100000.0
d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
CODES, BMAP = d['codes'], {str(k): int(v) for k, v in d['bmap'].items()}
hist = cifang_api.fetch_pool_history(CODES, cache_path=CACHE)
hist, _ = data_quality.audit(hist, verbose=False)

for wname, start in [('主窗口 2021起', '2021-01-01'), ('长窗口 2016起', '2016-01-01')]:
    m = bt1.build_matrices(hist, start=start, end='2026-10-20')
    print('\n' + '=' * 100)
    print('%s ｜ 交易日 %d ｜ 起点在世 %d 只' % (
        wname, len(m['dates']), int(np.isfinite(m['close'][0]).sum())))
    print('=' * 100)

    # ---------- 等价性校验 ----------
    a = bt1.run(m, BMAP, intraday_stop=True, exec_mode='close')
    b = bt3.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode='close')
    pa = bt1.perf(a['equity'], a['trades'], CASH0, a['exposure'])
    pb = bt1.perf(b['equity'], b['trades'], CASH0, b['exposure'])
    same_eq = bool(np.allclose(a['equity'].values, b['equity'].values, rtol=1e-12))
    same_n = len(a['trades']) == len(b['trades'])
    print('\n[等价性] max_hold=1 vs 单仓引擎：净值序列一致=%s ｜ 交易笔数 %d vs %d ｜ '
          '年化 %.4f%% vs %.4f%% ｜ 回撤 %.4f%% vs %.4f%%'
          % (same_eq, len(a['trades']), len(b['trades']),
             pa['cagr'] * 100, pb['cagr'] * 100, pa['max_dd'] * 100, pb['max_dd'] * 100))
    if not (same_eq and same_n):
        print('  ⚠️ 不等价，后续多仓结果不可信，请先修引擎')
        continue

    # ---------- 多仓扫描 ----------
    print('\n【分仓扫描（V2 盘中止损口径，等权分仓）】')
    print('  %-10s %10s %9s %10s %8s %8s %7s %8s %9s' % (
        '持仓数', '总收益', '年化', '最大回撤', '夏普', 'Calmar', '交易数', '胜率', '平均持有日'))
    rows = {}
    for mh in (1, 2, 3, 4):
        r = bt3.run(m, BMAP, max_hold=mh, intraday_stop=True, exec_mode='close')
        p = bt1.perf(r['equity'], r['trades'], CASH0, r['exposure'])
        rows[mh] = (r, p)
        print('  %-10d %9.1f%% %8.2f%% %9.2f%% %8.2f %8.2f %7d %7s %9.1f'
              % (mh, p['total_return'] * 100, p['cagr'] * 100, p['max_dd'] * 100,
                 p['sharpe'], p['calmar'], p['trades'],
                 '%.1f%%' % (p['win_rate'] * 100) if np.isfinite(p['win_rate']) else 'n/a',
                 p['avg_hold_days'] if np.isfinite(p['avg_hold_days']) else -1))

    # ---------- 分年 ----------
    print('\n【分年收益】')
    yrs = sorted(set().union(*[set(v[1]['by_year'].index) for v in rows.values()]))
    print('  %-6s %9s %9s %9s %9s' % ('年份', '1仓', '2仓', '3仓', '4仓'))
    for y in yrs:
        cells = []
        for mh in (1, 2, 3, 4):
            v = rows[mh][1]['by_year'].get(y, np.nan)
            cells.append('%.1f%%' % (v * 100) if pd.notna(v) else '-')
        print('  %-6d %9s %9s %9s %9s' % (y, *cells))

    # ---------- 剔除最强单年 ----------
    print('\n【稳健性：剔除最强单年后的年化】')
    for mh, (r, p) in rows.items():
        eq = p['equity']
        ret = eq.pct_change().fillna(0.0)
        by = ret.groupby(ret.index.year).apply(lambda s: (1 + s).prod() - 1)
        best = by.idxmax()
        r2 = ret[ret.index.year != best]
        cagr2 = (1 + r2).cumprod().iloc[-1] ** (252.0 / max(len(r2), 1)) - 1
        print('  %d 仓：原 %+.2f%% → 剔最强年(%d) %+.2f%%（差 %+.2fpp）'
              % (mh, p['cagr'] * 100, best, cagr2 * 100, (cagr2 - p['cagr']) * 100))

    # ---------- 换手与成本 ----------
    print('\n【换手与成本】')
    for mh, (r, p) in rows.items():
        tr = r['trades']
        buys = tr[tr.action == 'buy'] if len(tr) else pd.DataFrame()
        fees = float(tr['fee'].sum()) if len(tr) else 0.0
        yrs = p['years']
        print('  %d 仓：买入 %d 笔 / %.1f 笔每年 ｜ 累计费用 %.0f 元（初始资金 %.0f%%，'
              '年均 %.1f%%）｜ 持仓占比 %.1f%%'
              % (mh, len(buys), len(buys) / yrs, fees, fees / CASH0 * 100,
                 fees / CASH0 * 100 / yrs, p['exposure'] * 100))
