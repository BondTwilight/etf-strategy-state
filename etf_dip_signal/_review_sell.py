# -*- coding: utf-8 -*-
"""止盈（卖出）机制专项复盘：胜率口径 vs 回撤口径的对账

输出四块：
  A. 逐笔往返：MAE（过程最大浮亏）/ MFE（过程最大浮盈）/ 最终收益
  B. 最大回撤区间解剖：当时持有什么、浮亏多深、最后是赚是亏
  C. 「止盈条件已成立但被候选排名否决」的次数与代价
  D. 盈亏比与期望值
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

CODES_ALL, BMAP = (lambda d: (d['codes'], {str(k): int(v) for k, v in d['bmap'].items()}))(
    json.load(open('data/fixed_pool.json', encoding='utf-8')))
hist = cifang_api.fetch_pool_history(CODES_ALL, cache_path='data/etf_qfq_cifang.parquet')
hist, _ = data_quality.audit(hist, verbose=False)
m = bt1.build_matrices(hist, start='2021-01-01', end='2026-10-20')
CODES = m['codes']

trace = []
r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode='close', trace=trace,
           timeout_live=True)
tr = r['trades'].copy()
p = bt1.perf(r['equity'], tr, 100000.0, r['exposure'])

# 等价性回归（加了 trace/trail 参数后必须仍然同值）
r0 = bt1.run(m, BMAP, intraday_stop=True, exec_mode='close')
print('[回归] 加参数后与单仓引擎净值一致：%s'
      % bool(np.allclose(r['equity'].values, r0['equity'].values, rtol=1e-12)))

print('\n' + '=' * 104)
print('基准（V2 盘中止损，主窗口 2021~2026）：年化 %.2f%% ｜ 最大回撤 %.2f%% ｜ '
      '交易 %d 笔 ｜ 胜率 %.1f%%' % (p['cagr'] * 100, p['max_dd'] * 100,
                                    p['trades'], p['win_rate'] * 100))
print('=' * 104)

# ---------------- A. 逐笔往返 MAE / MFE ----------------
buys = tr[tr.action == 'buy'].reset_index(drop=True)
sells = tr[tr.action == 'sell'].reset_index(drop=True)
rows = []
for i in range(min(len(buys), len(sells))):
    b, s = buys.iloc[i], sells.iloc[i]
    code = b['code']
    df = hist[code].copy()
    df['date'] = df['date'].astype(str).str[:10]
    seg = df[(df['date'] > b['date']) & (df['date'] <= s['date'])]
    if len(seg) == 0:
        continue
    mae = float(seg['low'].min()) / b['price'] - 1
    mfe = float(seg['high'].max()) / b['price'] - 1
    rows.append({'#': i + 1, 'code': code, 'in': b['date'], 'out': s['date'],
                 'days': len(seg), 'ret': s['ret'], 'MAE': mae, 'MFE': mfe,
                 'reason': s['reason']})
R = pd.DataFrame(rows)

print('\n【A. 逐笔往返：过程浮亏(MAE) vs 最终收益】按 MAE 最差排序，前 12 笔')
print('  %-3s %-8s %-11s %-11s %4s %9s %9s %9s  %s' % (
    '#', '代码', '买入', '卖出', '日数', '最终收益', '过程最深', '过程最高', '卖出原因'))
for _, x in R.sort_values('MAE').head(12).iterrows():
    print('  %-3d %-8s %-11s %-11s %4d %8.2f%% %8.2f%% %8.2f%%  %s' % (
        x['#'], x['code'], x['in'], x['out'], x['days'],
        x['ret'] * 100, x['MAE'] * 100, x['MFE'] * 100, x['reason']))

win = R[R['ret'] > 0]
los = R[R['ret'] <= 0]
print('\n  ── 汇总 ──')
print('  盈利单 %d 笔：平均最终收益 %+.2f%%，但平均过程最深浮亏 %+.2f%%，最深 %+.2f%%'
      % (len(win), win['ret'].mean() * 100, win['MAE'].mean() * 100, win['MAE'].min() * 100))
print('  亏损单 %d 笔：平均最终收益 %+.2f%%，平均过程最深浮亏 %+.2f%%'
      % (len(los), los['ret'].mean() * 100, los['MAE'].mean() * 100))
print('  浮亏曾超过 -10%% 的笔数：%d（其中最终盈利 %d 笔）'
      % (int((R['MAE'] <= -0.10).sum()), int(((R['MAE'] <= -0.10) & (R['ret'] > 0)).sum())))
print('  浮亏曾超过 -20%% 的笔数：%d（其中最终盈利 %d 笔）'
      % (int((R['MAE'] <= -0.20).sum()), int(((R['MAE'] <= -0.20) & (R['ret'] > 0)).sum())))

# ---------------- B. 最大回撤区间解剖 ----------------
eq = r['equity']
peak = eq.cummax()
dd = eq / peak - 1
trough = dd.idxmin()
peak_date = eq[:trough].idxmax()
print('\n【B. 最大回撤区间解剖】')
print('  回撤 %.2f%% ｜ 峰值日 %s（净值 %.0f）→ 谷底日 %s（净值 %.0f）'
      % (dd.min() * 100, peak_date.date(), eq[peak_date], trough.date(), eq[trough]))
seg = R[(pd.to_datetime(R['in']) <= trough) & (pd.to_datetime(R['out']) >= peak_date)]
if len(seg):
    for _, x in seg.iterrows():
        print('  区间内持仓：%s  %s 买 → %s 卖 ｜ 过程最深 %+.2f%% ｜ 最终 %+.2f%%（%s）'
              % (x['code'], x['in'], x['out'], x['MAE'] * 100, x['ret'] * 100, x['reason']))
else:
    print('  （区间内无完整往返，可能为跨笔或空仓段）')
held_days_in = len(eq[(eq.index >= peak_date) & (eq.index <= trough)])
print('  区间长度 %d 个交易日' % held_days_in)

# ---------------- C. 否决事件 ----------------
T = pd.DataFrame(trace)
print('\n【C. 止盈条件成立但被「候选第一仍是自己」否决】')
if len(T):
    cnt = T['event'].value_counts()
    for k, v in cnt.items():
        print('  %s：%d 次' % (k, v))
    veto3 = T[T['event'].str.startswith('止盈被否决')]
    if len(veto3):
        print('  +3%% 达标却被否决时，当时的实际浮盈：均值 %+.2f%%，最高 %+.2f%%'
              % (veto3['ret'].mean() * 100, veto3['ret'].max() * 100))
        print('  这些被否决的日子涉及 %d 个不同标的' % veto3['code'].nunique())
else:
    print('  无')

# ---------------- D. 盈亏比 ----------------
print('\n【D. 盈亏结构】')
aw = win['ret'].mean() if len(win) else np.nan
al = los['ret'].mean() if len(los) else np.nan
print('  平均盈利 %+.2f%% ｜ 平均亏损 %+.2f%% ｜ 盈亏比 %.2f : 1'
      % (aw * 100, al * 100, abs(aw / al) if al else np.nan))
print('  最大单笔盈利 %+.2f%% ｜ 最大单笔亏损 %+.2f%% ｜ 极值比 %.2f : 1'
      % (R['ret'].max() * 100, R['ret'].min() * 100,
         abs(R['ret'].max() / R['ret'].min())))
gp = R[R['ret'] > 0]['ret'].sum()
gl = abs(R[R['ret'] <= 0]['ret'].sum())
print('  盈利因子（总盈/总亏）%.2f' % (gp / gl if gl else np.nan))
print('  期望值：单笔均值 %+.2f%% ｜ 按 95%% 胜率、+3%% 止盈、-15%% 止损的理论期望 %+.2f%%'
      % (R['ret'].mean() * 100, (0.95 * 0.03 + 0.05 * -0.15) * 100))
