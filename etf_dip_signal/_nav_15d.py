# -*- coding: utf-8 -*-
"""取原版在 2026-10 的净值曲线与仓位金额，把逐笔换算成实际金额。"""
import json
import os
import sys

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import bt_etf_dip as bt1
import bt_multi as bt
import data_quality


def main():
    pool = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'),
                          encoding='utf-8'))
    bmap = pool['bmap']
    d = pd.read_parquet(os.path.join(BASE, 'data', 'etf_qfq_cifang_1104.parquet'),
                        columns=['code', 'date', 'open', 'close', 'low'])
    d['date'] = d['date'].astype(str).str[:10]
    hist = {}
    for code, g in d.groupby('code', sort=False):
        g = g.sort_values('date').reset_index(drop=True)
        f, _ = data_quality.repair_prices(g, jump_th=0.30)
        hist[code] = f.reset_index(drop=True)

    m = bt1.build_matrices(hist, start='2021-01-01', end='2026-11-04')
    th_map = dict((c, bmap.get(c, -16)) for c in m['codes'])
    r = bt.run(m, th_map, max_hold=1, intraday_stop=False, exec_mode='close',
               timeout_live=True, trail=None, be_stop=None, cash_yield=0.025,
               slippage=0.0010, tick_frac=2.0)

    eq = r['equity']
    t = r['trades'].copy()
    t['d'] = pd.to_datetime(t['date'])

    print('=' * 92)
    print('【净值与仓位】2026-10-14 ~ 2026-11-04（10 万本金起）')
    print('=' * 92)
    print('  %-12s %12s %8s' % ('日期', '总资产', '相对初始'))
    for d0 in eq.index:
        if pd.Timestamp('2026-10-14') <= d0 <= pd.Timestamp('2026-11-04'):
            print('  %-12s %12.0f %7.1f%%'
                  % (str(d0.date()), eq.loc[d0], (eq.loc[d0] / 100000 - 1) * 100))

    print()
    print('=' * 92)
    print('【逐笔金额】')
    print('=' * 92)
    seg = t[t['d'] >= '2026-10-01']
    print('  %-12s %-5s %-8s %9s %12s %12s  %s'
          % ('日期', '方向', '标的', '价格', '份额(约)', '金额(约)', '原因'))
    for _, x in seg.iterrows():
        # 找到当日净值
        dt = x['d']
        nav = float(eq.loc[dt]) if dt in eq.index else float('nan')
        px = float(x['price'])
        if x['action'] == 'buy':
            amt = nav * 0.995
            sh = int(amt / (px * 1.0) // 100 * 100)
        else:
            # 卖出：用当时的持仓份额（近似 = 上一次买入的份额）
            prev = seg[(seg['d'] <= dt) & (seg['action'] == 'buy')]
            if len(prev):
                pnav = float(eq.loc[prev.iloc[-1]['d']])
                sh = int(pnav * 0.995 / float(prev.iloc[-1]['price']) // 100 * 100)
            else:
                sh = 0
            amt = sh * px
        print('  %-12s %-5s %-8s %9.4f %12s %12.0f  %s'
              % (str(dt.date()), x['action'], x['code'], px,
                 format(sh, ','), amt, x.get('reason', '')))

    # 期末持仓
    print()
    lb = seg[seg['action'] == 'buy']
    if len(lb):
        last = lb.iloc[-1]
        c = last['code']
        px_now = float(hist[c].iloc[-1]['close'])
        nav0 = float(eq.loc[last['d']])
        sh = int(nav0 * 0.995 / float(last['price']) // 100 * 100)
        print('  期末持仓：%s  成本 %.4f  份额约 %s  最新收盘 %.4f  市值 %.0f  浮盈 %+.2f%%'
              % (c, last['price'], format(sh, ','), px_now, sh * px_now,
                 (px_now / float(last['price']) - 1) * 100))
        print('  两条线：-15%% 止损 %.4f ｜ +3%% 目标 %.4f'
              % (float(last['price']) * 0.85, float(last['price']) * 1.03))


if __name__ == '__main__':
    main()
