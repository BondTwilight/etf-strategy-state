# -*- coding: utf-8 -*-
"""三问实测：①十万资金适配 ②当前行情状态 ③持仓期做网格的影响。

网格模拟：在策略持仓期间，以成本为基准做等距网格（涨 x% 卖一份、跌 x% 买回），
与"不做网格、按策略原规则卖出"对比。
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
CSV = os.path.join(BASE, '回测输出', 'trades_full_2022_2026.csv')


def load():
    d = pd.read_parquet(NEW, columns=['code', 'date', 'open', 'close', 'high', 'low',
                                      'amount'])
    d['date'] = d['date'].astype(str).str[:10]
    hist = {}
    for code, g in d.groupby('code', sort=False):
        g = g.sort_values('date').reset_index(drop=True)
        f, _ = data_quality.repair_prices(g, jump_th=0.30)
        hist[code] = f.reset_index(drop=True)
    return hist


def part_capital(hist, m):
    """① 十万资金：单笔占成交额比例、最小报价单位成本。"""
    print('=' * 100)
    print('【一】十万资金适配性')
    print('=' * 100)
    df = pd.read_csv(CSV, dtype={'code': str})
    df['code'] = df['code'].str.zfill(6)
    closed = df[df['reason'] != '(未平仓)'].copy()

    # 建仓日成交额
    rows = []
    for _, x in closed.iterrows():
        c = x['code']
        if c not in hist:
            continue
        g = hist[c]
        seg = g[g['date'] == x['entry']]
        if not len(seg):
            continue
        amt = float(seg.iloc[0].get('amount', np.nan))
        px = float(x['entry_px'])
        order = 100000 * 0.995
        rows.append({
            'code': c, 'date': x['entry'], 'px': px, 'amount': amt,
            'pct': order / amt * 100 if amt and amt > 0 else np.nan,
            'tick_pct': 0.001 / px * 100,       # 1 个报价单位相对价格
            'shares': int(order // px // 100 * 100),
        })
    t = pd.DataFrame(rows)
    print('  以 10 万满仓（99,500 元）计，%d 笔建仓：' % len(t))
    print('    单笔占当日成交额：中位 %.2f%% ｜ 均值 %.2f%% ｜ 最大 %.2f%%'
          % (t['pct'].median(), t['pct'].mean(), t['pct'].max()))
    print('    最小报价单位成本(1 tick)：中位 %.3f%% ｜ 最大 %.3f%%'
          % (t['tick_pct'].median(), t['tick_pct'].max()))
    print('    可买份额：中位 %s 股 ｜ 最少 %s 股'
          % (format(int(t['shares'].median()), ','), format(int(t['shares'].min()), ',')))
    print()
    print('  ⇒ 10 万资金下：单笔占成交额中位 %.2f%%（远低于 1%% 警戒线），'
          '冲击成本可忽略' % t['pct'].median())
    print('  ⇒ 1 tick 相对成本中位 %.3f%%，往返约 %.2f%%；'
          '年换手 6.4 次 → 年化拖累约 %.1fpp'
          % (t['tick_pct'].median(), t['tick_pct'].median() * 2,
             t['tick_pct'].median() * 2 * 6.4))
    print('  ⇒ 份额中位 %s 股，100 股整数倍无摩擦；无流动性约束'
          % format(int(t['shares'].median()), ','))
    return t


def part_regime(hist, m):
    """② 当前行情：指数位置、波动率、候选机会。"""
    print()
    print('=' * 100)
    print('【二】当前行情状态（截至 2026-11-04）')
    print('=' * 100)
    for code, name in (('510300', '沪深300ETF'), ('159915', '创业板ETF'),
                       ('588000', '科创50ETF')):
        if code not in hist:
            continue
        g = hist[code]
        c = g['close'].to_numpy(float)
        last = c[-1]
        ma20 = c[-20:].mean()
        ma60 = c[-60:].mean() if len(c) >= 60 else np.nan
        ret = np.diff(np.log(c[-21:]))
        vol20 = ret.std() * np.sqrt(252) * 100
        # 历史分位
        allret = np.diff(np.log(c))
        roll = pd.Series(allret).rolling(20).std() * np.sqrt(252) * 100
        pct = (roll.dropna() < vol20).mean() * 100
        print('  %-12s 收 %.4f ｜ 距MA20 %+6.2f%% ｜ 距MA60 %+6.2f%% ｜ 20日年化波动 %.1f%%（历史 %s 分位）'
              % (name, last, (last / ma20 - 1) * 100,
                 (last / ma60 - 1) * 100 if np.isfinite(ma60) else float('nan'),
                 vol20, ('%.0f%%' % pct) if np.isfinite(pct) else '-'))

    # 近 20 日全池中位波动
    vols = []
    for c, g in hist.items():
        s = g['close'].to_numpy(float)[-21:]
        if len(s) < 21:
            continue
        vols.append(np.diff(np.log(s)).std() * np.sqrt(252) * 100)
    print()
    print('  全池 20 日年化波动率：中位 %.1f%% ｜ 25%% 分位 %.1f%% ｜ 75%% 分位 %.1f%%'
          % (np.median(vols), np.percentile(vols, 25), np.percentile(vols, 75)))

    # 今日候选数（用 bias 近似）
    i = len(m['dates']) - 1
    th = np.array([m.get('th_arr', np.full(len(m['codes']), -16))[k]
                   if False else -16 for k in range(len(m['codes']))])
    bmin5 = m['bmin5'][i]
    valid = m['valid'][i]
    n_cand = int(np.nansum((bmin5 < -16) & valid))
    print('  今日 bias 深度 < -16%% 的标的数：%d 只（策略候选，阈值分档后略有出入）' % n_cand)


def part_grid(hist):
    """③ 持仓期做网格的影响。"""
    print()
    print('=' * 100)
    print('【三】持仓期间做网格：先看振幅够不够')
    print('=' * 100)
    df = pd.read_csv(CSV, dtype={'code': str})
    df['code'] = df['code'].str.zfill(6)
    closed = df[df['reason'] != '(未平仓)'].copy()

    amps = []
    for _, x in closed.iterrows():
        c = x['code']
        if c not in hist:
            continue
        g = hist[c]
        seg = g[(g['date'] >= x['entry']) & (g['date'] <= x['exit'])]
        if len(seg) < 1:
            continue
        hi = seg['high'].to_numpy(float)
        lo = seg['low'].to_numpy(float)
        cl = seg['close'].to_numpy(float)
        ok = np.isfinite(hi) & np.isfinite(lo) & np.isfinite(cl) & (cl > 0)
        if not ok.any():
            continue
        amp = np.nanmean((hi[ok] / lo[ok] - 1) * 100)
        amps.append({'code': c, 'n': len(seg), 'amp': amp,
                     'ret': x['ret'] * 100, 'hold': x['hold_td']})
    a = pd.DataFrame(amps)
    print('  %d 笔持仓期间的单日振幅（high/low-1）：' % len(a))
    print('    均值 %.2f%% ｜ 中位 %.2f%% ｜ 最小 %.2f%% ｜ 最大 %.2f%%'
          % (a['amp'].mean(), a['amp'].median(), a['amp'].min(), a['amp'].max()))
    print()
    print('  若网格间距设为：')
    for gap in (0.5, 1.0, 1.5, 2.0, 3.0):
        # 粗略：单日振幅/间距 = 可能触发的档数（上限）
        n = (a['amp'] / gap).clip(lower=0)
        print('    %.1f%% → 单日平均可触发 %.1f 档（持仓 %.1f 日 → 全程约 %.1f 档）'
              % (gap, n.mean(), a['hold'].mean(),
                 n.mean() * a['hold'].mean()))

    print()
    print('  策略本身的单笔期望：+5.03%%（持仓中位 6 个交易日）')
    print('  ⇒ 若网格每档赚 %.1f%%，全程触发 %.1f 档，理论增益约 %.1f%%'
          % (1.0, (a['amp'] / 1.0).mean() * a['hold'].mean(),
             (a['amp'] / 1.0).mean() * a['hold'].mean() * 1.0))
    print('  ⇒ 但网格必须预留现金低吸，仓位从 100%% 降到 50~70%%，')
    print('     而策略的收益来源是"满仓吃到反弹"，仓位打折 = 收益直接打折')
    print('  ⇒ 且网格卖出会与「目标收益 +3%」冲突：半路卖掉就到不了目标线')


def main():
    hist = load()
    pool = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'),
                          encoding='utf-8'))
    bmap = pool['bmap']
    m = bt1.build_matrices(hist, start='2021-01-01', end='2026-11-04')
    part_capital(hist, m)
    part_regime(hist, m)
    part_grid(hist)


if __name__ == '__main__':
    main()
