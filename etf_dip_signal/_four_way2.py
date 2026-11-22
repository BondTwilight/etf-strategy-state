# -*- coding: utf-8 -*-
"""四组合 · 严格对齐历史口径（timeout_live=True + tick 成本模型）。

上一版漏了 timeout_live=True（满 30 日无候选即清仓），导致"原版"跑出 40.8%
而非历史记录的 34.28%。本脚本补齐，并同时给 tick=1/2/3 三档成本。
"""
import json
import os
import sys

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

NEW = os.path.join(BASE, 'data', 'etf_qfq_cifang_1104.parquet')


def make_hist(path=NEW, jump_th=0.30):
    d = pd.read_parquet(path, columns=['code', 'date', 'open', 'close', 'low'])
    d['date'] = d['date'].astype(str).str[:10]
    hist = {}
    for code, g in d.groupby('code', sort=False):
        g = g.sort_values('date').reset_index(drop=True)
        f, _ = data_quality.repair_prices(g, jump_th=jump_th)
        hist[code] = f.reset_index(drop=True)
    return hist


def main():
    pool = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'),
                          encoding='utf-8'))
    bmap = pool['bmap']
    hist = make_hist()

    print('=' * 112)
    print('四组合 · timeout_live=True（对齐历史口径）· tick 成本模型')
    print('=' * 112)

    for start in ('2021-01-01', '2022-01-01'):
        m = bt1.build_matrices(hist, start=start, end='2026-11-04')
        th_map = dict((c, bmap.get(c, -16)) for c in m['codes'])
        print()
        print('窗口 %s ~ 2026-11-04（%d 只）' % (start, len(m['codes'])))
        print('  %-30s %6s %9s %9s %8s %6s %6s'
              % ('配置', '成本', '年化', '最大回撤', 'Calmar', '交易', '胜率'))
        combos = [
            ('原版（无保护位）', False, None, None),
            ('现行（trail8+be3）', False, 0.08, 0.03),
        ]
        for nm, intra, trail, be in combos:
            for tf, base, cname in ((1.0, 0.0005, '1tick'),
                                    (2.0, 0.0010, '2tick'),
                                    (3.0, 0.0010, '3tick')):
                r = bt.run(m, th_map, max_hold=1, intraday_stop=intra,
                           exec_mode='close', timeout_live=True,
                           trail=trail, be_stop=be, cash_yield=0.025,
                           slippage=base, tick_frac=tf)
                p = bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])
                print('  %-30s %6s %8.2f%% %8.2f%% %8.2f %6d %5.1f%%'
                      % (nm, cname, p['cagr'] * 100, p['max_dd'] * 100,
                         p['calmar'], p['trades'],
                         (p['win_rate'] if p['win_rate'] == p['win_rate'] else 0) * 100))

    # 逐笔对比 10-20 之后
    print()
    print('=' * 112)
    print('2026-10-20 之后逐笔（1 tick 口径）')
    print('=' * 112)
    m = bt1.build_matrices(hist, start='2021-01-01', end='2026-11-04')
    th_map = dict((c, bmap.get(c, -16)) for c in m['codes'])
    for nm, trail, be in (('原版', None, None), ('现行', 0.08, 0.03)):
        r = bt.run(m, th_map, max_hold=1, intraday_stop=False,
                   exec_mode='close', timeout_live=True, trail=trail,
                   be_stop=be, cash_yield=0.025, slippage=0.0005, tick_frac=1.0)
        t = r['trades']
        t = t[pd.to_datetime(t['date']) >= '2026-10-20']
        print('  ---- %s ----' % nm)
        if len(t):
            for _, x in t.iterrows():
                print('    %s  %-5s %-8s %8.4f  %s'
                      % (x['date'], x['action'], x['code'], x['price'],
                         x.get('reason', '')))
        else:
            print('    （无交易）')


if __name__ == '__main__':
    main()
