# -*- coding: utf-8 -*-
"""细化 = 每类各一仓（强制分散），检验能否提高频率同时不牺牲风险收益比。

背景诊断：
  · 205 个有候选日，各组机会几乎不重叠（74% 只有单一组有候选）
  · 所有组的「买/候选日」都低于 26%，红利 8.1%、商品 8.5%
  · MAX_HOLD=1 时类内限额无效（同时间只持 1 只）

所以唯一能提高频率的结构 = MAX_HOLD > 1，且「每类最多 1 只」。
对比：
  A 纯分仓（不分类）：max_hold=2/3/5，全局排序取前 N
  B 类内各 1 只：max_hold=5 + class_cap{每类:1}（最多 5 类各一仓）
  C 类内各 1 只但只开 2/3 仓：max_hold=2/3 + class_cap
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

START, END = '2021-01-01', '2026-10-20'
STD = dict(intraday_stop=True, exec_mode='close', timeout_live=True,
           trail=0.08, be_stop=0.03, cash_yield=0.025, slippage=0.002)
NOISE = 3.9
GS = ['A股', '远洋', '近岸', '红利', '商品']


def grp_of(c, cmap, sc, bmap):
    if cmap.get(c) == '商品':
        return '商品'
    if sc.get(c) in ('美股', '日本', '欧股'):
        return '远洋'
    if cmap.get(c) == '跨境' and bmap.get(c) == -16:
        return '近岸'
    if bmap.get(c) == -5:
        return '红利'
    return 'A股'


def go(m, bmap, **kw):
    a = dict(STD); a.update(kw)
    r = bt.run(m, bmap, **a)
    return r, bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])


def nb(r):
    t = r['trades']
    return int((t['action'] == 'buy').sum()) if len(t) else 0


def line(name, p, n, yrs):
    wr = p['win_rate'] * 100 if np.isfinite(p['win_rate']) else float('nan')
    print('%-30s %+8.2f%% %+8.2f%% %8.2f%% %7.2f %6.2f %5.1f%% %5d %6.1f'
          % (name, p['total_return'] * 100, p['cagr'] * 100, p['max_dd'] * 100,
             p['calmar'], p['sharpe'], wr, n, n / yrs))


def main():
    d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
    cmap = d.get('cmap', {}); sc = d.get('subclass', {})
    bmap = {str(k): int(v) for k, v in d['bmap'].items()}

    raw = pd.read_parquet('data/etf_qfq_cifang.parquet',
                          columns=['code', 'date', 'open', 'close', 'low'])
    raw['date'] = raw['date'].astype(str).str[:10]
    hist = {}
    for code, g in raw.groupby('code', sort=False):
        f, _ = data_quality.repair_prices(g[['date', 'open', 'close', 'low']])
        hist[code] = f.reset_index(drop=True)
    del raw
    m = bt1.build_matrices(hist, start=START, end=END)
    codes = list(m['codes']); n = m['close'].shape[0]
    yrs = n / 244.0
    print('矩阵 %d x %d ｜ %.1f 年' % (n, len(codes), yrs))

    gid = {g: i for i, g in enumerate(GS)}
    cls = np.full((n, len(codes)), -1, dtype=int)
    for j, c in enumerate(codes):
        cls[:, j] = gid[grp_of(c, cmap, sc, bmap)]
    CAP1 = {0: 1, 1: 1, 2: 1, 3: 1, 4: 1}

    print()
    print('=' * 112)
    print('【1】分仓结构对比（年频率 = 买入笔数 / 年）')
    print('=' * 112)
    print('%-30s %9s %9s %9s %7s %6s %6s %5s %6s'
          % ('', '总收益', '年化', '回撤', 'Calmar', '夏普', '胜率', '笔数', '年频率'))
    print('-' * 112)
    r0, p0 = go(m, bmap, max_hold=1)
    line('基准 MAX=1', p0, nb(r0), yrs)

    store = {}
    plans = [
        ('纯分仓 MAX=2', dict(max_hold=2)),
        ('纯分仓 MAX=3', dict(max_hold=3)),
        ('纯分仓 MAX=5', dict(max_hold=5)),
        ('每类各1只 MAX=2', dict(max_hold=2, class_cap=CAP1, cls_mat=cls)),
        ('每类各1只 MAX=3', dict(max_hold=3, class_cap=CAP1, cls_mat=cls)),
        ('每类各1只 MAX=5', dict(max_hold=5, class_cap=CAP1, cls_mat=cls)),
    ]
    for name, kw in plans:
        r, p = go(m, bmap, **kw)
        store[name] = (r, p, kw)
        line(name, p, nb(r), yrs)
    print()

    # ---------- 各类别被买次数 ----------
    print('=' * 112)
    print('【2】各类别被买次数（看「每类各1只」是否真的让低频类上位）')
    print('=' * 112)
    print('%-30s %6s %6s %6s %6s %6s' % ('', *GS))
    print('-' * 112)

    def dist(r):
        t = r['trades']
        b = t[t['action'] == 'buy'].copy()
        b['code'] = b['code'].astype(str).str.zfill(6)
        v = b['code'].map(lambda c: grp_of(c, cmap, sc, bmap)).value_counts()
        return [int(v.get(g, 0)) for g in GS]

    print('%-30s %6d %6d %6d %6d %6d' % ('基准 MAX=1', *dist(r0)))
    for k, v in store.items():
        print('%-30s %6d %6d %6d %6d %6d' % (k, *dist(v[0])))
    print()

    # ---------- walk-forward ----------
    print('=' * 112)
    print('【3】walk-forward（拟合 2021-2023 / 检验 2024-2026）')
    print('=' * 112)
    dates = pd.to_datetime(m['dates'])

    def cut(lo, hi):
        idx = np.where((dates >= pd.Timestamp(lo)) & (dates <= pd.Timestamp(hi)))[0]
        o = {}
        for k in ('open', 'close', 'low', 'close_raw', 'bias20', 'bias50', 'bmin5',
                  'valid', 'amount'):
            if k in m:
                o[k] = m[k][idx]
        o['dates'] = np.array(m['dates'])[idx]
        o['codes'] = m['codes']
        return o, idx

    mf, idf = cut('2021-01-01', '2023-12-31')
    mh, idh = cut('2024-01-01', '2026-10-20')
    bf = go(mf, bmap, max_hold=1)[1]['cagr'] * 100
    bh = go(mh, bmap, max_hold=1)[1]['cagr'] * 100
    print('%-30s %13s %13s %12s' % ('', '拟合段', '检验段', '判定'))
    print('-' * 112)
    print('%-30s %12.2f%% %12.2f%%' % ('基准 MAX=1', bf, bh))
    for name, (r, p, kw) in store.items():
        kf = dict(kw); kh = dict(kw)
        if 'cls_mat' in kw:
            kf['cls_mat'] = kw['cls_mat'][idf]
            kh['cls_mat'] = kw['cls_mat'][idh]
        cf = go(mf, bmap, **kf)[1]['cagr'] * 100
        ch = go(mh, bmap, **kh)[1]['cagr'] * 100
        df_, dh = cf - bf, ch - bh
        if df_ > 0 and dh > 0:
            flag = '✅ 两段同向'
        elif (df_ > 0) != (dh > 0):
            flag = '⚠️ 方向不一致'
        else:
            flag = '❌ 两段同负'
        print('%-30s %12.2f%% %12.2f%%  %s (Δ%+.1f/%+.1f)'
              % (name, cf, ch, flag, df_, dh))
    print()

    # ---------- 逐年 ----------
    print('=' * 112)
    print('【4】逐年收益（%）')
    print('=' * 112)

    def yearly(r):
        rr = r['equity'].pct_change().dropna()
        y = rr.groupby(rr.index.year).apply(lambda x: (1 + x).prod() - 1)
        return (y * 100).round(1)

    y0 = yearly(r0); ys = sorted(y0.index)
    print('%-30s' % '' + ''.join('%8d' % y for y in ys))
    print('-' * 112)
    for tag, r in [('基准 MAX=1', r0)] + [(k, v[0]) for k, v in store.items()]:
        y = yearly(r)
        print('%-30s' % tag + ''.join('%7.1f ' % y.get(k2, np.nan) for k2 in ys))
    print()

    # ---------- 成本敏感性（分仓后换手上升） ----------
    print('=' * 112)
    print('【5】成本敏感性：分仓会提高换手，检查在 2tick/3tick 下是否还成立')
    print('=' * 112)
    print('%-30s %12s %12s %12s' % ('', '1 tick(0.1%)', '2 tick(0.2%)', '3 tick(0.3%)'))
    print('-' * 112)
    for tag, kw in [('基准 MAX=1', dict(max_hold=1)),
                    ('每类各1只 MAX=3', dict(max_hold=3, class_cap=CAP1, cls_mat=cls)),
                    ('每类各1只 MAX=5', dict(max_hold=5, class_cap=CAP1, cls_mat=cls))]:
        vals = []
        for slip in (0.001, 0.002, 0.003):
            p = go(m, bmap, slippage=slip, **kw)[1]
            vals.append('%+.2f%%/%+.1f%%' % (p['cagr'] * 100, p['max_dd'] * 100))
        print('%-30s %12s %12s %12s' % (tag, *vals))
    print('  （格式：年化/回撤）')
    print()

    os.makedirs('回测输出', exist_ok=True)
    rows = [{'variant': 'MAX=1', 'cagr': p0['cagr'], 'max_dd': p0['max_dd'],
             'calmar': p0['calmar'], 'sharpe': p0['sharpe'], 'trades': nb(r0)}]
    for k, v in store.items():
        rows.append({'variant': k, 'cagr': v[1]['cagr'], 'max_dd': v[1]['max_dd'],
                     'calmar': v[1]['calmar'], 'sharpe': v[1]['sharpe'],
                     'trades': nb(v[0])})
    pd.DataFrame(rows).to_csv('回测输出/position_split.csv', index=False,
                              encoding='utf-8-sig')
    print('已写出 回测输出/position_split.csv')


if __name__ == '__main__':
    main()
