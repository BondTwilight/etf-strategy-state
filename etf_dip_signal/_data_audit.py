# -*- coding: utf-8 -*-
"""数据版本对账：旧 parquet(10-20拉) vs 新全量(11-04拉)，同一配置同一窗口。

目的：解释为什么「原版+盘中止损」从 34.28%/-32.32% 变成 36.91%/-14.94%。
可能是：①次方修正了历史数据 ②前复权基准变化 ③清洗识别点不同
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

OLD = os.path.join(BASE, 'data', 'etf_qfq_cifang.parquet')
NEW = os.path.join(BASE, 'data', 'etf_qfq_cifang_1104.parquet')


def load(path, jump_th=0.30):
    d = pd.read_parquet(path, columns=['code', 'date', 'open', 'close', 'low'])
    d['date'] = d['date'].astype(str).str[:10]
    hist = {}
    n_fix = 0
    for code, g in d.groupby('code', sort=False):
        g = g.sort_values('date').reset_index(drop=True)
        f, hits = data_quality.repair_prices(g, jump_th=jump_th)
        n_fix += len(hits) if hits else 0
        hist[code] = f.reset_index(drop=True)
    return hist, n_fix, d


def main():
    print('=' * 96)
    print('【一】两个数据版本的基本盘')
    print('=' * 96)
    h_old, f_old, d_old = load(OLD)
    h_new, f_new, d_new = load(NEW)
    for nm, d, nf in (('旧(10-20拉)', d_old, f_old), ('新(11-04全量)', d_new, f_new)):
        print('  %-14s %s ~ %s ｜ %d 只 ｜ %d 行 ｜ 修复跳变 %d 处'
              % (nm, d['date'].min(), d['date'].max(), d['code'].nunique(),
                 len(d), nf))

    # 同一标的两版价格比对（截至 10-20）
    print()
    print('=' * 96)
    print('【二】两版价格是否一致（同一标的、同一日期）')
    print('=' * 96)
    common = sorted(set(d_old['code']) & set(d_new['code']))
    diffs = []
    for c in common[:400]:
        a = d_old[d_old['code'] == c][['date', 'close']].set_index('date')['close']
        b = d_new[d_new['code'] == c][['date', 'close']].set_index('date')['close']
        j = a.index.intersection(b.index)
        if len(j) < 100:
            continue
        r = (b.loc[j] / a.loc[j]).replace([np.inf, -np.inf], np.nan).dropna()
        if len(r) == 0:
            continue
        ratio_med = float(r.median())
        ratio_std = float(r.std())
        diffs.append({'code': c, 'n': len(r), 'ratio_med': ratio_med,
                      'ratio_std': ratio_std})
    if diffs:
        dd = pd.DataFrame(diffs)
        print('  可比标的 %d 只' % len(dd))
        print('  收盘价比值中位数分布：min %.6f ｜ 中位 %.6f ｜ max %.6f'
              % (dd['ratio_med'].min(), dd['ratio_med'].median(),
                 dd['ratio_med'].max()))
        print('  比值标准差 >0.001 的标的数：%d（说明整段等比缩放，非单点差异）'
              % (dd['ratio_std'] > 0.001).sum())
        bad = dd[dd['ratio_std'] > 0.001].head(10)
        if len(bad):
            print('  差异最大的 10 只：')
            for _, x in bad.iterrows():
                print('    %s  n=%d  ratio中位=%.6f  std=%.6f'
                      % (x['code'], int(x['n']), x['ratio_med'], x['ratio_std']))

    print()
    print('=' * 96)
    print('【三】同一配置、同一窗口（2021-01-01 ~ 2026-10-20）两版结果')
    print('=' * 96)
    pool = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'),
                          encoding='utf-8'))
    bmap = pool['bmap']
    for nm, h in (('旧数据', h_old), ('新数据', h_new)):
        m = bt1.build_matrices(h, start='2021-01-01', end='2026-10-20')
        th_map = dict((c, bmap.get(c, -16)) for c in m['codes'])
        for cfg, intra, trail, be in (('原版盘中开', True, None, None),
                                      ('原版盘中关', False, None, None),
                                      ('现行', False, 0.08, 0.03)):
            r = bt.run(m, th_map, max_hold=1, intraday_stop=intra,
                       exec_mode='close', cash0=100000.0, commission=0.0002,
                       slippage=0.002, trail=trail, be_stop=be, cash_yield=0.025)
            p = bt1.perf(r['equity'], r['trades'], cash0=100000.0,
                         exposure=r['exposure'])
            cal = p['cagr'] / abs(p['max_dd']) if p['max_dd'] else 0
            print('  %-8s %-12s 年化 %7.2f%% ｜ 回撤 %7.2f%% ｜ Calmar %.2f ｜ 交易 %d'
                  % (nm, cfg, p['cagr'] * 100, p['max_dd'] * 100, cal,
                     len(r['trades']) // 2))


if __name__ == '__main__':
    main()
