# -*- coding: utf-8 -*-
"""核查：本地「商品 4 笔全拖累」的结论，是不是窗口造成的假象。

聚宽 2022-01-01 起的结果：剔除商品后年化 33.09% → 30.78%（-2.31pp），回撤不变。
本地 2021-01-04 起的结果：剔除商品后 38.73% → 39.37%（+0.64pp），回撤 -18.87 → -13.20。

两者方向相反。最可能的原因：本地那 4 笔商品交易全在 2021 年，
而聚宽从 2022 起跑，看到的是另一批商品交易（且是赚的）。
"""
import os
import sys
import json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

STD = dict(max_hold=1, intraday_stop=True, exec_mode='close', timeout_live=True,
           trail=0.08, be_stop=0.03, cash_yield=0.025, slippage=0.002)
GOODS = ['159831', '159981', '159985', '510170', '518600']


def main():
    d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
    bmap = {str(k): int(v) for k, v in d['bmap'].items()}
    nm = d.get('name', {})

    raw = pd.read_parquet('data/etf_qfq_cifang.parquet',
                          columns=['code', 'date', 'open', 'close', 'low'])
    raw['date'] = raw['date'].astype(str).str[:10]
    hist = {}
    for code, g in raw.groupby('code', sort=False):
        f, _ = data_quality.repair_prices(g[['date', 'open', 'close', 'low']])
        hist[code] = f.reset_index(drop=True)
    del raw

    for start, tag in (('2021-01-01', '本地基准窗口'), ('2022-01-01', '聚宽窗口')):
        m = bt1.build_matrices(hist, start=start, end='2026-10-20')
        r = bt.run(m, bmap, **STD)
        p = bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])
        tr = r['trades']
        b = tr[tr['action'] == 'buy'].copy()
        b['code'] = b['code'].astype(str).str.zfill(6)
        b['date'] = pd.to_datetime(b['date'])
        s = tr[tr['action'] == 'sell'].copy()
        s['code'] = s['code'].astype(str).str.zfill(6)
        s['date'] = pd.to_datetime(s['date'])

        print('=' * 96)
        print('【%s】%s ~ 2026-10-20' % (tag, start))
        print('=' * 96)
        print('  年化 %+.2f%%  回撤 %.2f%%  买入 %d 笔'
              % (p['cagr'] * 100, p['max_dd'] * 100, len(b)))
        gb = b[b['code'].isin(GOODS)]
        print('  其中商品 %d 笔:' % len(gb))
        tot = 1.0
        for _, x in gb.iterrows():
            sv = s[(s['code'] == x['code']) & (s['date'] >= x['date'])]
            ret = float(sv.iloc[0]['ret']) if len(sv) else float('nan')
            rsn = sv.iloc[0]['reason'] if len(sv) else '未平仓'
            if np.isfinite(ret):
                tot *= (1 + ret)
            print('     %s  %s %-18s 收益 %+7.2f%%  卖出原因 %s'
                  % (x['date'].date(), x['code'], str(nm.get(x['code'], ''))[:16],
                     ret * 100, rsn))
        if len(gb):
            print('     商品合计复利 %+.2f%%' % ((tot - 1) * 100))
        print()
        # 逐年统计商品交易
        if len(gb):
            print('  商品交易按年份:', dict(gb['date'].dt.year.value_counts().sort_index()))
            print()

    # 逐窗口对比「剔除商品」的效果
    print('=' * 96)
    print('【3】两个窗口下「剔除商品」的效果对比')
    print('=' * 96)
    bmap_n = dict(bmap)
    for c in GOODS:
        bmap_n[c] = -18
    print('%-14s %14s %14s %10s' % ('窗口', '含商品年化', '剔除后年化', '差'))
    print('-' * 96)
    for start in ('2021-01-01', '2022-01-01', '2023-01-01'):
        m = bt1.build_matrices(hist, start=start, end='2026-10-20')
        a = bt1.perf(*[bt.run(m, bmap, **STD)[k] for k in ('equity', 'trades')],
                     100000.0, bt.run(m, bmap, **STD)['exposure'])
        rn = bt.run(m, bmap_n, **STD)
        bn = bt1.perf(rn['equity'], rn['trades'], 100000.0, rn['exposure'])
        print('%-14s %13.2f%% %13.2f%% %+9.2fpp'
              % (start, a['cagr'] * 100, bn['cagr'] * 100,
                 (bn['cagr'] - a['cagr']) * 100))
    print()
    print('  若不同起点的符号不一致 ⇒ 「商品该不该剔除」的结论对窗口敏感，')
    print('  根因是商品交易只有 4 笔，样本不足以支撑任何方向。')


if __name__ == '__main__':
    main()
