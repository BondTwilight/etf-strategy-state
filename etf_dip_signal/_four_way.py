# -*- coding: utf-8 -*-
"""全量重拉 + 四组合对比（修正"拼接前复权"的错误）。

错误说明：
    前复权价格每次分红都会整体重算。把 2026-10-20 拉的旧缓存（基准日=当时）
    和 2026-11-04 拉的新数据（基准日=今天）拼接，两者基准不同 ⇒ 拼接点出现假跳变
    ⇒ 又被 data_quality 当成脏数据"修复"（前缀等比缩放）⇒ 历史价格被整体扭曲。

本脚本改为：全量拉 2015-01-01 ~ 2026-11-04，落新 parquet，再跑四组合。
"""
import json
import os
import sys

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import bt_etf_dip as bt1
import bt_multi as bt
import cifang_api as cf
import data_quality

COMM = 0.0002
CY = 0.025
NEW_PARQ = os.path.join(BASE, 'data', 'etf_qfq_cifang_1104.parquet')


def build_full():
    pool = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'),
                          encoding='utf-8'))
    codes = pool['codes']
    if os.path.exists(NEW_PARQ):
        d = pd.read_parquet(NEW_PARQ)
        print('  已存在全量缓存：%s ~ %s，%d 只'
              % (d['date'].astype(str).str[:10].min(),
                 d['date'].astype(str).str[:10].max(), d['code'].nunique()))
        return d
    print('  全量拉取 %d 只 2015-01-01 ~ 2026-11-04 ...' % len(codes))
    hist = cf.fetch_pool_history(codes, '2015-01-01', '2026-11-04', force=True)
    frames = []
    for c, g in hist.items():
        g = g.copy()
        g['code'] = c
        frames.append(g[['code', 'date', 'open', 'close', 'low']])
    d = pd.concat(frames, ignore_index=True)
    d['date'] = d['date'].astype(str).str[:10]
    d.to_parquet(NEW_PARQ, index=False)
    print('  全量落盘：%s ~ %s，%d 只，%d 行'
          % (d['date'].min(), d['date'].max(), d['code'].nunique(), len(d)))
    return d


def make_hist(d, jump_th=0.30):
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

    d = build_full()
    print()

    for jt in (0.30,):
        hist = make_hist(d, jump_th=jt)
        print('=' * 108)
        print('全量数据 · 清洗阈值 %.2f' % jt)
        print('=' * 108)
        for start in ('2021-01-01', '2022-01-01'):
            m = bt1.build_matrices(hist, start=start, end='2026-11-04')
            th_map = dict((c, bmap.get(c, -16)) for c in m['codes'])
            print('  窗口 %s ~ %s（%d 只）' % (start, '2026-11-04', len(m['codes'])))
            print('    %-32s %9s %9s %9s %8s %6s %6s'
                  % ('配置', '年化', '总收益', '最大回撤', 'Calmar', '交易', '胜率'))
            combos = [
                ('原版 · 盘中开 · 滑点0.1%', True, None, None, 0.001),
                ('原版 · 盘中开 · 滑点0.2%', True, None, None, 0.002),
                ('原版 · 盘中关 · 滑点0.2%', False, None, None, 0.002),
                ('现行 · 盘中关 · 滑点0.2%', False, 0.08, 0.03, 0.002),
            ]
            for nm, intra, trail, be, slip in combos:
                r = bt.run(m, th_map, max_hold=1, intraday_stop=intra,
                           exec_mode='close', cash0=100000.0, commission=COMM,
                           slippage=slip, trail=trail, be_stop=be, cash_yield=CY)
                p = bt1.perf(r['equity'], r['trades'], cash0=100000.0,
                             exposure=r['exposure'])
                cal = p['cagr'] / abs(p['max_dd']) if p['max_dd'] else 0
                print('    %-32s %8.2f%% %8.1f%% %8.2f%% %8.2f %6d %5.1f%%'
                      % (nm, p['cagr'] * 100, p['total_return'] * 100,
                         p['max_dd'] * 100, cal, len(r['trades']) // 2,
                         (p.get('win_rate') or 0) * 100))
            print()


if __name__ == '__main__':
    main()
