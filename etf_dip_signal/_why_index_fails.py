# -*- coding: utf-8 -*-
"""为什么「指数级择时」救不了这套策略：收益驱动源与回撤时段的对账"""
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
idx.index = pd.to_datetime(idx.index)
c = idx['close'].astype(float)
ma20 = c.rolling(20).mean()
state = (c > ma20)

m = bt1.build_matrices(hist, start='2021-01-01', end='2026-10-20')
r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode='close', timeout_live=True)
p = bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])
eq = p['equity']
ret = eq.pct_change().fillna(0.0)

# 1. 年度收益对账
by_strat = (1 + ret).groupby(ret.index.year).prod() - 1
idx_ret = c.pct_change()
by_idx = (1 + idx_ret).groupby(idx_ret.index.year).prod() - 1

print('【1】年度收益对账：策略 vs 中证1000')
print('  %-6s %12s %12s' % ('年份', '策略', '中证1000'))
common = [y for y in by_strat.index if y in by_idx.index]
for y in common:
    print('  %-6d %11.2f%% %11.2f%%' % (y, by_strat[y] * 100, by_idx[y] * 100))
a = np.array([by_strat[y] for y in common])
b = np.array([by_idx[y] for y in common])
print('  年度收益相关系数 r = %.3f（样本 %d 年）' % (np.corrcoef(a, b)[0, 1], len(common)))

# 2. 最大回撤区间内的状态分布
peak = eq.cummax()
dd = eq / peak - 1
trough = dd.idxmin()
peak_d = eq[:trough].idxmax()
seg = state[(state.index >= peak_d) & (state.index <= trough)]
print('\n【2】最大回撤区间（%s ~ %s，%d 个交易日）里，中证1000 处于「MA20 上方」的天数'
      % (peak_d.date(), trough.date(), len(seg)))
if len(seg):
    print('  MA20 上方 %d 天（%.0f%%）｜下方 %d 天' % (
        int(seg.sum()), seg.mean() * 100, int((~seg).sum())))
print('  ⇒ 若用「跌破 MA20 就不开仓」做闸门，该区间内 %.0f%% 的时间闸门是"开"的，'
      '拦不住这段回撤' % (seg.mean() * 100 if len(seg) else 0))

# 3. 2021 年逐月：策略在跌，指数在涨？
print('\n【3】2021 年月度对照（回撤发生年）')
m21 = ret[ret.index.year == 2021]
i21 = idx_ret[idx_ret.index.year == 2021]
mo_s = (1 + m21).groupby(m21.index.month).prod() - 1
mo_i = (1 + i21).groupby(i21.index.month).prod() - 1
print('  %-4s %10s %12s' % ('月', '策略', '中证1000'))
for mo in sorted(set(mo_s.index) | set(mo_i.index)):
    print('  %-4d %9.2f%% %11.2f%%' % (mo, mo_s.get(mo, np.nan) * 100,
                                       mo_i.get(mo, np.nan) * 100))
