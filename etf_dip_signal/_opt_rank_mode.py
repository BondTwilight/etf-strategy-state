# -*- coding: utf-8 -*-
"""按类别细化：让「各自的极端」公平竞争。

问题：现行口径是「全池按 bias50 绝对值升序」，A股 -20% 永远压过红利 -5%，
      而 -5% 已是红利自身的历史极端。红利候选日 62 天，只被买 5 次（8.1%）。

方案（不放松阈值、不改 MAX_HOLD）：
  R1  z-score 排序：key = (bias50 - 自身250日均值) / 自身250日标准差
  R2  分位排序：key = bias50 在自身过去 500 日中的分位数
  R3  z-score + 类内限额（各类最多同时持 1 只）

多方验证：
  ① 主窗口 2021-2026  ② walk-forward 拟合/检验
  ③ 逐年表  ④ 剔除最强年  ⑤ 蒙特卡洛噪声带（±3.9pp）
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
STD = dict(max_hold=1, intraday_stop=True, exec_mode='close', timeout_live=True,
           trail=0.08, be_stop=0.03, cash_yield=0.025, slippage=0.002)
WIN_Z, WIN_P = 250, 500
NOISE = 3.9          # 蒙特卡洛实测年化噪声 1σ (pp)


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


def line(name, p, n):
    wr = p['win_rate'] * 100 if np.isfinite(p['win_rate']) else float('nan')
    print('%-34s %+8.2f%% %+8.2f%% %8.2f%% %7.2f %6.2f %5.1f%% %4d'
          % (name, p['total_return'] * 100, p['cagr'] * 100, p['max_dd'] * 100,
             p['calmar'], p['sharpe'], wr, n))


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
    B50 = m['bias50']
    print('矩阵 %d x %d' % (n, len(codes)))

    # ---------- 构造排序键 ----------
    Z = np.full_like(B50, np.nan)
    P = np.full_like(B50, np.nan)
    for j in range(len(codes)):
        s = pd.Series(B50[:, j])
        mu = s.rolling(WIN_Z, min_periods=60).mean()
        sd = s.rolling(WIN_Z, min_periods=60).std()
        Z[:, j] = ((s - mu) / sd).to_numpy()
        P[:, j] = s.rolling(WIN_P, min_periods=80).rank(pct=True).to_numpy()
    print('z-score 有效 %.1f%%  分位有效 %.1f%%'
          % (100 * np.isfinite(Z).mean(), 100 * np.isfinite(P).mean()))

    # 类别编码矩阵（类内限额用）
    gs = ['A股', '远洋', '近岸', '红利', '商品']
    gid = {g: i for i, g in enumerate(gs)}
    cls = np.full_like(B50, -1, dtype=int)
    for j, c in enumerate(codes):
        cls[:, j] = gid[grp_of(c, cmap, sc, bmap)]
    print('类别: ' + ', '.join('%s=%d' % (g, i) for g, i in gid.items()))
    print()

    # ---------- 主窗口 ----------
    r0, p0 = go(m, bmap)
    print('=' * 106)
    print('【1】主窗口 2021-01-04 ~ 2026-10-20')
    print('=' * 106)
    print('%-34s %9s %9s %9s %7s %6s %6s %4s'
          % ('', '总收益', '年化', '回撤', 'Calmar', '夏普', '胜率', '笔数'))
    print('-' * 106)
    line('基准（bias50 绝对值排序）', p0, nb(r0))

    store = {}
    for name, kw in [
        ('R1 z-score 排序', dict(rank_mat=Z)),
        ('R2 分位排序', dict(rank_mat=P)),
        ('R1b z-score + 类内各1只', dict(rank_mat=Z, class_cap={0: 1, 1: 1, 2: 1, 3: 1, 4: 1}, cls_mat=cls)),
        ('R2b 分位 + 类内各1只', dict(rank_mat=P, class_cap={0: 1, 1: 1, 2: 1, 3: 1, 4: 1}, cls_mat=cls)),
        ('R3 类内各1只（仍绝对排序）', dict(class_cap={0: 1, 1: 1, 2: 1, 3: 1, 4: 1}, cls_mat=cls)),
    ]:
        r, p = go(m, bmap, **kw)
        store[name] = (r, p, kw)
        line(name, p, nb(r))
    print()
    print('  （噪声 1σ = %.1fpp：差异 < %.1fpp 视为不可区分）' % (NOISE, NOISE))
    print()

    # ---------- 交易结构对比 ----------
    print('=' * 106)
    print('【2】买入口径对比：各类别被买次数（细化的目标是让红利/商品也有机会）')
    print('=' * 106)
    print('%-34s %6s %6s %6s %6s %6s %8s'
          % ('', 'A股', '远洋', '近岸', '红利', '商品', '年频率'))
    print('-' * 106)

    def dist(r):
        t = r['trades']
        b = t[t['action'] == 'buy'].copy()
        b['code'] = b['code'].astype(str).str.zfill(6)
        v = b['code'].map(lambda c: grp_of(c, cmap, sc, bmap)).value_counts()
        return [int(v.get(g, 0)) for g in gs], len(b)

    for tag, r in [('基准', r0)] + [(k, v[0]) for k, v in store.items()]:
        cnt, tot = dist(r)
        print('%-34s %6d %6d %6d %6d %6d %7.1f次/年'
              % (tag, *cnt, tot / (n / 244.0)))
    print()

    # ---------- walk-forward ----------
    print('=' * 106)
    print('【3】walk-forward（拟合 2021-2023 / 检验 2024-2026）')
    print('=' * 106)

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
    bf = go(mf, bmap)[1]['cagr'] * 100
    bh = go(mh, bmap)[1]['cagr'] * 100
    print('%-30s %13s %13s %12s' % ('', '拟合段年化', '检验段年化', '判定'))
    print('-' * 106)
    print('%-30s %12.2f%% %12.2f%%' % ('基准', bf, bh))
    for name, (r, p, kw) in store.items():
        kf = dict(kw); kh = dict(kw)
        if 'rank_mat' in kw:
            kf['rank_mat'] = kw['rank_mat'][idf]
            kh['rank_mat'] = kw['rank_mat'][idh]
        if 'cls_mat' in kw:
            kf['cls_mat'] = kw['cls_mat'][idf]
            kh['cls_mat'] = kw['cls_mat'][idh]
        cf = go(mf, bmap, **kf)[1]['cagr'] * 100
        ch = go(mh, bmap, **kh)[1]['cagr'] * 100
        df_ = cf - bf; dh = ch - bh
        if df_ > NOISE * 0.5 and dh > NOISE * 0.5:
            flag = '✅ 两段显著改善'
        elif df_ > 0 and dh > 0:
            flag = '△ 两段同向但幅度小'
        elif (df_ > 0) != (dh > 0):
            flag = '⚠️ 方向不一致'
        else:
            flag = '❌ 两段同负'
        print('%-30s %12.2f%% %12.2f%%  %s (Δ%+.1f/%+.1f)'
              % (name, cf, ch, flag, df_, dh))
    print()

    # ---------- 逐年 ----------
    print('=' * 106)
    print('【4】逐年收益（%）')
    print('=' * 106)

    def yearly(r):
        e = r['equity']
        rr = e.pct_change().dropna()
        y = rr.groupby(rr.index.year).apply(lambda x: (1 + x).prod() - 1)
        return (y * 100).round(1)

    y0 = yearly(r0)
    yrs = sorted(y0.index)
    print('%-34s' % '' + ''.join('%8d' % y for y in yrs))
    print('-' * 106)

    def prow(tag, r):
        y = yearly(r)
        print('%-34s' % tag + ''.join('%7.1f ' % y.get(k, np.nan) for k in yrs))

    prow('基准', r0)
    for name, (r, p, kw) in store.items():
        prow(name, r)
    print()

    # ---------- 剔最强年 ----------
    print('=' * 106)
    print('【5】稳健性：剔除最强年')
    print('=' * 106)

    def drop_best(r):
        rr = r['equity'].pct_change().dropna()
        y = rr.groupby(rr.index.year).apply(lambda x: (1 + x).prod() - 1)
        best = y.idxmax()
        keep = rr[rr.index.year != best]
        tot = (1 + keep).prod() - 1
        return ((1 + tot) ** (244.0 / len(keep)) - 1) * 100, best

    for tag, r in [('基准', r0)] + [(k, v[0]) for k, v in store.items()]:
        cg, best = drop_best(r)
        p = bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])
        print('  %-32s 剔 %s 后 %+7.2f%%（原 %+7.2f%%，落差 %5.2fpp）'
              % (tag, best, cg, p['cagr'] * 100, p['cagr'] * 100 - cg))
    print()

    os.makedirs('回测输出', exist_ok=True)
    rows = [{'variant': 'base', 'cagr': p0['cagr'], 'max_dd': p0['max_dd'],
             'calmar': p0['calmar'], 'sharpe': p0['sharpe'], 'trades': nb(r0)}]
    for k, v in store.items():
        rows.append({'variant': k, 'cagr': v[1]['cagr'], 'max_dd': v[1]['max_dd'],
                     'calmar': v[1]['calmar'], 'sharpe': v[1]['sharpe'],
                     'trades': nb(v[0])})
    pd.DataFrame(rows).to_csv('回测输出/diag_freq_variants.csv', index=False,
                              encoding='utf-8-sig')
    print('已写出 回测输出/diag_freq_variants.csv')


if __name__ == '__main__':
    main()
