# -*- coding: utf-8 -*-
"""原版 vs 现行：回撤区间、逐年、以及"移动止盈到底有没有降回撤"的最终核对。

为什么必须做：
    历史结论说"移动止盈把回撤从 -32.32% 降到 -18.37%"，
    但今天同数据同引擎跑出「原版 -17.63% vs 现行 -18.22%」，
    方向完全相反。必须定位 -32.32% 到底来自哪个口径。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

NEW = os.path.join(BASE, 'data', 'etf_qfq_cifang_1104.parquet')


def make_hist(jump_th=0.30):
    d = pd.read_parquet(NEW, columns=['code', 'date', 'open', 'close', 'low'])
    d['date'] = d['date'].astype(str).str[:10]
    hist = {}
    for code, g in d.groupby('code', sort=False):
        g = g.sort_values('date').reset_index(drop=True)
        f, _ = data_quality.repair_prices(g, jump_th=jump_th)
        hist[code] = f.reset_index(drop=True)
    return hist


def dd_detail(eq, trades, label):
    peak = eq.cummax()
    dd = eq / peak - 1
    trough = dd.idxmin()
    # 找峰值日
    seg = eq[:trough]
    peak_day = seg.idxmax()
    print('  %-10s 期末 %.4f ｜ 年化 %.2f%% ｜ 最大回撤 %.2f%%'
          % (label, eq.iloc[-1] / 100000.0,
             ((eq.iloc[-1] / 100000.0) ** (365.25 / (eq.index[-1] - eq.index[0]).days) - 1) * 100,
             dd.min() * 100))
    print('             回撤区间 %s → %s（%d 个交易日，%d 天）'
          % (peak_day.date(), trough.date(),
             len(eq[peak_day:trough]), (trough - peak_day).days))
    # 区间内的交易
    t = trades.copy()
    t['d'] = pd.to_datetime(t['date'])
    seg_t = t[(t['d'] >= peak_day) & (t['d'] <= trough)]
    if len(seg_t):
        for _, x in seg_t.iterrows():
            extra = ''
            if x['action'] == 'sell' and 'ret' in x and pd.notna(x.get('ret')):
                extra = ' ret=%+.2f%%' % (x['ret'] * 100)
            print('       %s %-4s %-8s %8.4f %s%s'
                  % (str(x['d'].date()), x['action'], x['code'], x['price'],
                     x.get('reason', ''), extra))
    else:
        print('       （区间内无交易）')


def main():
    pool = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'),
                          encoding='utf-8'))
    bmap = pool['bmap']
    hist = make_hist()
    m = bt1.build_matrices(hist, start='2021-01-01', end='2026-11-04')
    th_map = dict((c, bmap.get(c, -16)) for c in m['codes'])

    print('=' * 104)
    print('【一】最大回撤解剖（2 tick，timeout_live=True）')
    print('=' * 104)
    out = {}
    for nm, trail, be in (('原版', None, None), ('现行', 0.08, 0.03)):
        r = bt.run(m, th_map, max_hold=1, intraday_stop=False, exec_mode='close',
                   timeout_live=True, trail=trail, be_stop=be, cash_yield=0.025,
                   slippage=0.0010, tick_frac=2.0)
        out[nm] = r
        dd_detail(r['equity'], r['trades'], nm)
        print()

    print('=' * 104)
    print('【二】逐年收益')
    print('=' * 104)
    e0 = out['原版']['equity']
    e1 = out['现行']['equity']
    print('  %-6s %12s %12s %10s' % ('年份', '原版', '现行', '差'))
    for y in sorted(set(e0.index.year)):
        a = e0[e0.index.year == y]
        b = e1[e1.index.year == y]
        if len(a) < 2 or len(b) < 2:
            continue
        ra = a.iloc[-1] / a.iloc[0] - 1
        rb_ = b.iloc[-1] / b.iloc[0] - 1
        print('  %-6d %11.2f%% %11.2f%% %+9.2fpp' % (y, ra * 100, rb_ * 100,
                                                     (rb_ - ra) * 100))

    print()
    print('=' * 104)
    print('【三】卖出原因分布')
    print('=' * 104)
    for nm in ('原版', '现行'):
        t = out[nm]['trades']
        s = t[t['action'] == 'sell']
        dist = dict(s['reason'].value_counts())
        rets = s['ret'].describe() if 'ret' in s else None
        print('  %s（%d 笔卖出）：%s' % (nm, len(s), dist))
        if rets is not None:
            print('      收益 均值 %+.2f%% ｜ 中位 %+.2f%% ｜ 最差 %+.2f%% ｜ 最好 %+.2f%%'
                  % (rets['mean'] * 100, rets['50%'] * 100,
                     rets['min'] * 100, rets['max'] * 100))

    print()
    print('=' * 104)
    print('【四】"移动止盈"单独触发时的真实收益（它到底在赚还是亏）')
    print('=' * 104)
    t = out['现行']['trades']
    s = t[(t['action'] == 'sell') & (t['reason'] == '移动止盈')]
    if len(s):
        for _, x in s.iterrows():
            print('    %s %-8s 收益 %+.2f%%' % (x['date'], x['code'],
                                               x.get('ret', np.nan) * 100))
        print('    ⇒ 移动止盈 %d 笔，均值 %+.2f%%，胜 %d/%d'
              % (len(s), s['ret'].mean() * 100, (s['ret'] > 0).sum(), len(s)))
    else:
        print('    （无移动止盈触发）')


if __name__ == '__main__':
    main()
