# -*- coding: utf-8 -*-
"""原版 vs 现行：2026-11-03 到底谁卖了 588170。

原版（分发包 v4.1）= 只有四道闸门，无 trail / 无 breakeven
现行（我们改的）   = 四道闸门 + 移动止盈 8% + 保本止损 3%

验证目标：
  ① 原版在 11-03 会不会卖 588170？
  ② 若不卖，到 11-04 收盘净值多少？
  ③ 把窗口拉到 11-04，原版 vs 现行的完整差异（不只这一笔）
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
import cifang_api as cf
import data_quality

SLIP = 0.002
COMM = 0.0002
CY = 0.025


def load_hist():
    raw = pd.read_parquet(os.path.join(BASE, 'data', 'etf_qfq_cifang.parquet'),
                          columns=['code', 'date', 'open', 'close', 'low'])
    raw['date'] = raw['date'].astype(str).str[:10]
    print('  本地缓存 %s ~ %s，%d 只'
          % (raw['date'].min(), raw['date'].max(), raw['code'].nunique()))

    # 补最新（10-01 ~ 11-04），用新数据覆盖
    codes = sorted(raw['code'].unique().tolist())
    fresh = cf.fetch_pool_history(codes, '2026-10-01', '2026-11-04', force=True)
    print('  补拉 %d 只，最新到 %s'
          % (len(fresh), max(g['date'].max() for g in fresh.values())
             if fresh else 'N/A'))

    merged = {}
    for code, g in raw.groupby('code', sort=False):
        g2 = g.copy()
        if code in fresh:
            new = fresh[code][['date', 'open', 'close', 'low']].copy()
            new['date'] = new['date'].astype(str).str[:10]
            g2['date'] = g2['date'].astype(str).str[:10]
            g2 = g2[g2['date'] < new['date'].min()]
            g2 = pd.concat([g2, new], ignore_index=True)
        g2 = g2.sort_values('date').reset_index(drop=True)
        f, _ = data_quality.repair_prices(g2, jump_th=0.25)
        merged[code] = f.reset_index(drop=True)
    print('  合并后 %d 只' % len(merged))
    return merged


def main():
    pool = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'),
                          encoding='utf-8'))
    bmap = pool['bmap']

    hist = load_hist()
    m = bt1.build_matrices(hist, start='2021-01-01', end='2026-11-04')
    th_map = dict((c, bmap.get(c, -16)) for c in m['codes'])
    print('  矩阵 %s ~ %s，%d 只' % (m['dates'][0], m['dates'][-1], len(m['codes'])))
    print()

    def _run(trail, be):
        return bt.run(m, th_map, max_hold=1, intraday_stop=False,
                      exec_mode='close', cash0=100000.0, commission=COMM,
                      slippage=SLIP, trail=trail, be_stop=be, cash_yield=CY)

    r_old = _run(None, None)          # 原版
    r_new = _run(0.08, 0.03)          # 现行

    p_old = bt1.perf(r_old['equity'], r_old['trades'], cash0=100000.0,
                     exposure=r_old['exposure'])
    p_new = bt1.perf(r_new['equity'], r_new['trades'], cash0=100000.0,
                     exposure=r_new['exposure'])

    print('=' * 96)
    print('【一】全窗口（2021-01-01 ~ 2026-11-04）')
    print('=' * 96)
    print('  %-22s %9s %9s %9s %8s %8s' % ('配置', '年化', '总收益', '最大回撤', 'Calmar', '交易'))
    for nm, p in (('原版（无保护位）', p_old), ('现行（trail8+be3）', p_new)):
        cal = p['cagr'] / abs(p['max_dd']) if p['max_dd'] else 0
        print('  %-22s %8.2f%% %8.1f%% %8.2f%% %8.2f %8d'
              % (nm, p['cagr'] * 100, p['total_return'] * 100,
                 p['max_dd'] * 100, cal, int(p.get('n_sell', 0)) or
                 len(r_old['trades']) // 2))

    print()
    print('=' * 96)
    print('【二】2026-10-20 之后的逐笔（关键：谁卖了 588170）')
    print('=' * 96)
    for nm, r in (('原版', r_old), ('现行', r_new)):
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

    print()
    print('=' * 96)
    print('【三】净值对比（10-20 起）')
    print('=' * 96)
    e_old = r_old['equity']
    e_new = r_new['equity']
    idx = e_old.index[e_old.index >= '2026-10-20']
    print('  %-12s %12s %12s' % ('日期', '原版', '现行'))
    for d in idx:
        print('  %-12s %12.4f %12.4f'
              % (str(d.date()), e_old.loc[d], e_new.loc[d] if d in e_new.index else np.nan))
    print()
    if len(idx):
        last = idx[-1]
        print('  期末 %s：原版 %.4f（%+.2f%%）｜ 现行 %.4f（%+.2f%%）｜ 差 %+.2fpp'
              % (str(last.date()), e_old.loc[last], (e_old.loc[last] - 1) * 100,
                 e_new.loc[last], (e_new.loc[last] - 1) * 100,
                 (e_old.loc[last] - e_new.loc[last]) * 100))

    # 导出
    out = os.path.join(BASE, '回测输出')
    os.makedirs(out, exist_ok=True)
    for nm, r in (('orig', r_old), ('live', r_new)):
        t = r['trades']
        if len(t):
            t.to_csv(os.path.join(out, 'trades_1104_%s.csv' % nm),
                     index=False, encoding='utf-8-sig')
    print()
    print('  已写出 回测输出/trades_1104_orig.csv / _live.csv')


if __name__ == '__main__':
    main()
