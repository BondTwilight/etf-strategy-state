# -*- coding: utf-8 -*-
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cifang_api, bt_etf_dip as bt, data_quality

d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
CODES, BMAP = d['codes'], {str(k): int(v) for k, v in d['bmap'].items()}
hist = cifang_api.fetch_pool_history(CODES, cache_path='data/etf_qfq_cifang.parquet')
hist, _ = data_quality.audit(hist, verbose=False)
m = bt.build_matrices(hist, start='2021-01-01', end='2026-10-20')

for lbl, kw in [('V1 无盘中止损', dict(intraday_stop=False, cooldown=0)),
                ('V2 cd=0', dict(intraday_stop=True, cooldown=0)),
                ('V2 cd=3', dict(intraday_stop=True, cooldown=3))]:
    r = bt.run(m, BMAP, exec_mode='close', **kw)
    tr = r['trades']
    sells = tr[tr.action == 'sell'] if len(tr) else pd.DataFrame()
    print('\n%s：卖出 %d 笔' % (lbl, len(sells)))
    if len(sells):
        print('  卖出原因分布：', sells['reason'].value_counts().to_dict())
        worst = sells.nsmallest(3, 'ret')[['date', 'code', 'ret', 'reason']]
        print('  最差 3 笔：')
        for _, x in worst.iterrows():
            print('    %s %s  %.2f%%  %s' % (x['date'], x['code'], x['ret'] * 100, x['reason']))
    p = bt.perf(r['equity'], tr, 100000.0, r['exposure'])
    print('  年化 %.2f%%  回撤 %.2f%%' % (p['cagr'] * 100, p['max_dd'] * 100))
