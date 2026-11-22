# -*- coding: utf-8 -*-
"""导出原版（v4.6）在 2026-10-01 ~ 2026-11-04 的逐笔操作，用于回答"最近十五天该做什么"。"""
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
NAME = {}


def make_hist():
    d = pd.read_parquet(NEW, columns=['code', 'date', 'open', 'close', 'low'])
    d['date'] = d['date'].astype(str).str[:10]
    hist = {}
    for code, g in d.groupby('code', sort=False):
        g = g.sort_values('date').reset_index(drop=True)
        f, _ = data_quality.repair_prices(g, jump_th=0.30)
        hist[code] = f.reset_index(drop=True)
    return hist


def main():
    pool = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'),
                          encoding='utf-8'))
    bmap = pool['bmap']
    # 名称（如果有）
    for k in ('name', 'names'):
        if k in pool and isinstance(pool[k], dict):
            NAME.update(pool[k])

    hist = make_hist()
    m = bt1.build_matrices(hist, start='2021-01-01', end='2026-11-04')
    th_map = dict((c, bmap.get(c, -16)) for c in m['codes'])

    r = bt.run(m, th_map, max_hold=1, intraday_stop=False, exec_mode='close',
               timeout_live=True, trail=None, be_stop=None, cash_yield=0.025,
               slippage=0.0010, tick_frac=2.0)

    t = r['trades'].copy()
    t['d'] = pd.to_datetime(t['date'])
    seg = t[(t['d'] >= '2026-10-01') & (t['d'] <= '2026-11-04')]

    print('=' * 96)
    print('【一】原版（v4.6）2026-10-01 ~ 2026-11-04 逐笔')
    print('=' * 96)
    print('  %-12s %-5s %-8s %9s %10s  %s'
          % ('日期', '方向', '标的', '成交价', '金额(元)', '原因'))
    cash_flow = 0.0
    for _, x in seg.iterrows():
        amt = x.get('value', 0) or 0
        print('  %-12s %-5s %-8s %9.4f %10.0f  %s'
              % (str(x['d'].date()), x['action'], x['code'], x['price'],
                 amt, x.get('reason', '')))

    print()
    print('=' * 96)
    print('【二】逐笔往返收益')
    print('=' * 96)
    buys = seg[seg['action'] == 'buy'].reset_index(drop=True)
    sells = seg[seg['action'] == 'sell'].reset_index(drop=True)
    for i in range(min(len(buys), len(sells))):
        b = buys.iloc[i] if i < len(buys) else None
        print('  （买卖自动配对见下）')

    # 用完整 trades 配对
    tb = t[t['action'] == 'buy'].reset_index(drop=True)
    ts = t[t['action'] == 'sell'].reset_index(drop=True)
    n = min(len(tb), len(ts))
    pairs = []
    for i in range(n):
        pairs.append({
            'entry': str(tb.loc[i, 'd'].date()), 'code': tb.loc[i, 'code'],
            'entry_px': tb.loc[i, 'price'],
            'exit': str(ts.loc[i, 'd'].date()), 'exit_px': ts.loc[i, 'price'],
            'ret': ts.loc[i].get('ret', float('nan')),
            'reason': ts.loc[i].get('reason', ''),
        })
    pp = pd.DataFrame(pairs)
    seg_p = pp[pp['exit'] >= '2026-10-01']
    print('  %-12s %-8s %9s %-12s %9s %9s  %s'
          % ('买入日', '标的', '买入价', '卖出日', '卖出价', '收益', '原因'))
    for _, x in seg_p.iterrows():
        r_ = x['ret']
        print('  %-12s %-8s %9.4f %-12s %9.4f %8.2f%%  %s'
              % (x['entry'], x['code'], x['entry_px'], x['exit'],
                 x['exit_px'], (r_ * 100) if r_ == r_ else float('nan'),
                 x['reason']))

    print()
    print('=' * 96)
    print('【三】期末状态')
    print('=' * 96)
    eq = r['equity']
    print('  期末净值 %.4f（%+.2f%%）｜ 最后持仓 %s'
          % (eq.iloc[-1] / 100000.0, (eq.iloc[-1] / 100000.0 - 1) * 100,
             seg[seg['action'] == 'buy'].iloc[-1]['code']
             if len(seg[seg['action'] == 'buy']) else '空仓'))
    last_buy = seg[seg['action'] == 'buy'].iloc[-1] if len(seg[seg['action'] == 'buy']) else None
    if last_buy is not None:
        c = last_buy['code']
        px = float(hist[c].iloc[-1]['close'])
        print('  持仓 %s ｜ 成本 %.4f ｜ 最新收盘 %.4f ｜ 浮盈 %+.2f%%'
              % (c, last_buy['price'], px, (px / last_buy['price'] - 1) * 100))
        print('  -15%% 止损线 %.4f ｜ +3%% 目标线 %.4f'
              % (last_buy['price'] * 0.85, last_buy['price'] * 1.03))

    out = os.path.join(BASE, '回测输出', 'trades_15d_orig.csv')
    seg.to_csv(out, index=False, encoding='utf-8-sig')
    print()
    print('  已写出 回测输出/trades_15d_orig.csv')


if __name__ == '__main__':
    main()
