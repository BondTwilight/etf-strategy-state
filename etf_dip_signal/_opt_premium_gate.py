# -*- coding: utf-8 -*-
"""跨境 ETF 溢价闸门回测 + 513100 异常核查。

上一步发现：买入时溢价偏离 >5% 的 4 笔平均 -2.06%，<=5% 的 10 笔平均 +8.11%，
r = -0.776。但那是「用当日收盘后净值算的事后值」。

本脚本用「前一日溢价偏离」做闸门（14:45 决策时可得），检验是否仍成立。
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
WIN = 250


def go(m, bmap, **kw):
    a = dict(STD); a.update(kw)
    r = bt.run(m, bmap, **a)
    return r, bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])


def nb(r):
    t = r['trades']
    return int((t['action'] == 'buy').sum()) if len(t) else 0


def line(name, p, n):
    wr = p['win_rate'] * 100 if np.isfinite(p['win_rate']) else float('nan')
    print('%-30s %+8.2f%% %+8.2f%% %8.2f%% %7.2f %6.2f %5.1f%% %4d'
          % (name, p['total_return'] * 100, p['cagr'] * 100, p['max_dd'] * 100,
             p['calmar'], p['sharpe'], wr, n))


def main():
    d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
    cmap = d.get('cmap', {}); sc = d.get('subclass', {})
    bmap = {str(k): int(v) for k, v in d['bmap'].items()}
    nm = d.get('name', {})
    cross = [c for c in d['codes'] if cmap.get(c) == '跨境']

    # ---------- 0. 513100 核查 ----------
    print('=' * 100)
    print('【0】513100 纳指ETF 极差 523% 核查')
    print('=' * 100)
    nav = pd.read_parquet('data/etf_nav_cifang.parquet')
    px = pd.read_parquet('data/etf_qfq_cifang.parquet',
                         columns=['code', 'date', 'open', 'close', 'low'])
    px['date'] = pd.to_datetime(px['date'])
    for c in ('513100', '513500'):
        n1 = nav[nav['code'] == c][['nav_date', 'unit_nav']].sort_values('nav_date')
        p1 = px[px['code'] == c][['date', 'close']].sort_values('date')
        j = n1.merge(p1, left_on='nav_date', right_on='date', how='inner').sort_values('date')
        j['ratio'] = j['close'] / j['unit_nav']
        v = j['unit_nav'].to_numpy(float)
        jump = np.where(np.abs(v[1:] / v[:-1] - 1) > 0.12)[0]
        print('  %s: 对齐 %d 行, ratio min %.3f med %.3f max %.3f, 净值跳变>12%% %d 次'
              % (c, len(j), j['ratio'].min(), j['ratio'].median(),
                 j['ratio'].max(), len(jump)))
        for k in jump[:6]:
            print('       %s  nav %.4f -> %.4f (%+.1f%%)  close %.4f  ratio %.3f'
                  % (j['date'].iloc[k + 1].date(), v[k], v[k + 1],
                     (v[k + 1] / v[k] - 1) * 100, j['close'].iloc[k + 1],
                     j['ratio'].iloc[k + 1]))
        # 极端 ratio 的日期
        imax = j['ratio'].idxmax()
        print('       最高 ratio 于 %s: close %.4f nav %.4f'
              % (j.loc[imax, 'date'].date(), j.loc[imax, 'close'],
                 j.loc[imax, 'unit_nav']))
    print()

    # ---------- 1. 构造前一日溢价偏离矩阵 ----------
    raw = pd.read_parquet('data/etf_qfq_cifang.parquet',
                          columns=['code', 'date', 'open', 'close', 'low'])
    raw['date'] = raw['date'].astype(str).str[:10]
    hist = {}
    for code, g in raw.groupby('code', sort=False):
        f, _ = data_quality.repair_prices(g[['date', 'open', 'close', 'low']])
        hist[code] = f.reset_index(drop=True)
    del raw
    m = bt1.build_matrices(hist, start=START, end=END)
    codes = list(m['codes'])
    dates = pd.to_datetime(m['dates'])
    n, mm = len(dates), len(codes)
    print('矩阵 %d x %d' % (n, mm))

    DEV = np.full((n, mm), np.nan)
    col = {c: i for i, c in enumerate(codes)}
    filled = 0
    for c in cross:
        if c not in col:
            continue
        n1 = nav[nav['code'] == c][['nav_date', 'unit_nav']].sort_values('nav_date')
        p1 = px[px['code'] == c][['date', 'close']].sort_values('date')
        j = n1.merge(p1, left_on='nav_date', right_on='date', how='inner').sort_values('date')
        if len(j) < 100:
            continue
        r = pd.Series((j['close'] / j['unit_nav']).to_numpy(float),
                      index=pd.to_datetime(j['date']))
        base = r.rolling(WIN, min_periods=60).median()
        dv = (r / base - 1.0).reindex(dates).ffill().shift(1)   # ★ 前一日的值
        DEV[:, col[c]] = dv.to_numpy(float)
        filled += 1
    print('溢价偏离矩阵已填 %d 只跨境（其余为 NaN=不过滤）' % filled)
    fin = np.isfinite(DEV)
    print('有效值 %d / %d (%.1f%%)' % (fin.sum(), DEV.size, 100.0 * fin.sum() / DEV.size))
    print()

    # ---------- 2. 回测 ----------
    r0, p0 = go(m, bmap)
    print('=' * 100)
    print('【1】溢价闸门回测（前一日溢价偏离 > X 则不买；仅作用于跨境）')
    print('=' * 100)
    print('%-30s %9s %9s %9s %7s %6s %6s %4s'
          % ('', '总收益', '年化', '回撤', 'Calmar', '夏普', '胜率', '笔数'))
    print('-' * 100)
    line('基准（无溢价过滤）', p0, nb(r0))
    store = {}
    for cap in (0.02, 0.03, 0.05, 0.08, 0.10, 0.15):
        mask = ~(np.isfinite(DEV) & (DEV > cap))
        r, p = go(m, bmap, liq=mask)
        store[cap] = (r, p, mask)
        line('溢价偏离 > %.0f%% 不买' % (cap * 100), p, nb(r))
    print()
    print('  （liq 掩码：True=可买；NaN 视为可买，即 A股/无净值数据不受影响）')
    print()

    # ---------- 3. walk-forward ----------
    print('=' * 100)
    print('【2】walk-forward：溢价闸门（拟合 2021-2023 / 检验 2024-2026）')
    print('=' * 100)

    def cut(m, lo, hi):
        idx = np.where((dates >= pd.Timestamp(lo)) & (dates <= pd.Timestamp(hi)))[0]
        o = {}
        for k in ('open', 'close', 'low', 'close_raw', 'bias20', 'bias50', 'bmin5',
                  'valid', 'amount'):
            if k in m:
                o[k] = m[k][idx]
        o['dates'] = np.array(m['dates'])[idx]
        o['codes'] = m['codes']
        return o, idx

    mf, idxf = cut(m, '2021-01-01', '2023-12-31')
    mh, idxh = cut(m, '2024-01-01', '2026-10-20')
    print('%-22s %14s %14s %14s' % ('配置', '拟合段年化', '检验段年化', '全段年化'))
    print('-' * 100)
    bf = go(mf, bmap)[1]['cagr'] * 100
    bh = go(mh, bmap)[1]['cagr'] * 100
    print('%-22s %13.2f%% %13.2f%% %13.2f%%' % ('无过滤', bf, bh, p0['cagr'] * 100))
    for cap in (0.03, 0.05, 0.10):
        mask = store[cap][2]
        cf = go(mf, bmap, liq=mask[idxf])[1]['cagr'] * 100
        ch = go(mh, bmap, liq=mask[idxh])[1]['cagr'] * 100
        ca = store[cap][1]['cagr'] * 100
        flag = '✅' if (cf - bf > 0 and ch - bh > 0) else ('⚠️' if (cf - bf > 0) != (ch - bh > 0) else '❌')
        print('%-22s %13.2f%% %13.2f%% %13.2f%%  %s (Δ%+.1f/%+.1f)'
              % ('溢价>%.0f%%不买' % (cap * 100), cf, ch, ca, flag, cf - bf, ch - bh))
    print()

    # ---------- 4. 稳健性 ----------
    print('=' * 100)
    print('【3】稳健性：剔除最强年')
    print('=' * 100)

    def drop_best(eq):
        r = eq.pct_change().dropna()
        yr = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
        best = yr.idxmax()
        keep = r[r.index.year != best]
        tot = (1 + keep).prod() - 1
        return ((1 + tot) ** (244.0 / len(keep)) - 1) * 100, best

    for tag, r, p in [('基准', r0, p0),
                      ('溢价>3%不买', store[0.03][0], store[0.03][1]),
                      ('溢价>5%不买', store[0.05][0], store[0.05][1])]:
        cg, best = drop_best(r['equity'])
        print('  %-16s 剔 %s 后 %+7.2f%%（原 %+7.2f%%，落差 %5.2fpp）'
              % (tag, best, cg, p['cagr'] * 100, p['cagr'] * 100 - cg))
    print()

    os.makedirs('回测输出', exist_ok=True)
    pd.DataFrame([{'variant': 'base', 'cagr': p0['cagr'], 'max_dd': p0['max_dd'],
                   'calmar': p0['calmar'], 'trades': nb(r0)}] +
                 [{'variant': 'prem>%.0f%%' % (k * 100), 'cagr': v[1]['cagr'],
                   'max_dd': v[1]['max_dd'], 'calmar': v[1]['calmar'],
                   'trades': nb(v[0])} for k, v in store.items()]
                 ).to_csv('回测输出/premium_gate.csv', index=False, encoding='utf-8-sig')
    print('已写出 回测输出/premium_gate.csv')


if __name__ == '__main__':
    main()
