# -*- coding: utf-8 -*-
"""检验：以中证1000状态（天基营的标的与作用域）做闸门/仓位系数，对抄底策略是否有用

天基营 = 中证1000 上的「资金面+情绪面 → 做多/空仓」。这里用可得的公开代理重构同一族信号，
直接问一个问题：**这类状态信号接到抄底策略上，是加分还是减分？**

四种状态定义（全部只用当日及之前数据，无前视）：
  A 趋势20      close > MA20
  B 趋势20向上   close > MA20 且 MA20 高于 5 日前
  C 量能参与     成交额 5 日均 > 20 日均（纯情绪/参与度代理）
  D 共振         close > MA20 且 成交额5均 > 20均（最接近「资金与情绪共振」）

每种分别测两种接法：
  gate   → 状态不佳时**不开新仓**（scale=0）
  scaler → 状态不佳时**仓位减半**（scale=0.5）
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

idx = pd.read_parquet('data/index_000852.parquet')
idx['date'] = pd.to_datetime(idx['date'].astype(str)).dt.strftime('%Y-%m-%d')
idx = idx.sort_values('date').set_index('date')
c = idx['close'].astype(float)
amt = idx['amount'].astype(float)
ma20 = c.rolling(20).mean()
ma60 = c.rolling(60).mean()
a5 = amt.rolling(5).mean()
a20 = amt.rolling(20).mean()

STATES = {
    'A 趋势20': c > ma20,
    'B 趋势20向上': (c > ma20) & (ma20 > ma20.shift(5)),
    'C 量能参与': a5 > a20,
    'D 共振': (c > ma20) & (a5 > a20),
}


def scale_for(dates, ser, mode):
    s = ser.reindex(pd.Index(dates)).ffill().fillna(False).to_numpy(dtype=bool)
    if mode == 'gate':
        return np.where(s, 1.0, 0.0)
    return np.where(s, 1.0, 0.5)


for wname, start in [('主窗口 2021起', '2021-01-01'), ('长窗口 2016起', '2016-01-01')]:
    m = bt1.build_matrices(hist, start=start, end='2026-10-20')
    dates = m['dates']
    base = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode='close',
                  timeout_live=True)
    pb = bt1.perf(base['equity'], base['trades'], 100000.0, base['exposure'])
    print('\n' + '=' * 108)
    print('%s ｜ 基准 年化 %.2f%% / 回撤 %.2f%% / Calmar %.2f / 交易 %d'
          % (wname, pb['cagr'] * 100, pb['max_dd'] * 100, pb['calmar'], pb['trades']))
    print('=' * 108)
    print('  %-22s %9s %9s %9s %8s %8s %7s' % (
        '状态信号 · 接法', '年化', '最大回撤', 'Calmar', '夏普', '胜率', '交易'))
    for name, ser in STATES.items():
        for mode in ('gate', 'scaler'):
            sc = scale_for(dates, ser, mode)
            r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode='close',
                       timeout_live=True, scale=sc)
            if not len(r['trades']):
                print('  %-22s 无交易' % ('%s · %s' % (name, mode)))
                continue
            p = bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])
            print('  %-22s %8.2f%% %8.2f%% %8.2f %8.2f %7.1f%% %7d' % (
                '%s · %s' % (name, mode), p['cagr'] * 100, p['max_dd'] * 100,
                p['calmar'], p['sharpe'],
                p['win_rate'] * 100 if np.isfinite(p['win_rate']) else -1,
                p['trades']))
