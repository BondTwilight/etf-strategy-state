# -*- coding: utf-8 -*-
"""跨境 ETF 溢价风险全池排查 + 策略实际买入时的溢价暴露。

核心问题：QDII 额度紧张时场内价格可长期偏离净值（159529 极差 55.9%、
单点溢价 52.2%）。若策略在「高溢价」时买入，它买的不是下跌的标的，
而是「贵的壳」—— 后续既有均值回归（可能亏），也有溢价收敛（一定亏）。

方法：
  1. 全池 84 只跨境的 close/nav 比值极差排序（相对值，不受 qfq 缩放影响）
  2. 用「比值 / 250 日滚动中位数 - 1」构造溢价偏离度（可实盘计算的代理）
  3. 找出策略买入的跨境交易，看买入日的溢价偏离度与事后收益
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

WIN = 250          # 溢价偏离度的滚动基准窗口


def main():
    d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
    cmap = d.get('cmap', {}); sc = d.get('subclass', {}); bmap = d['bmap']
    nm = d.get('name', {})
    cross = [c for c in d['codes'] if cmap.get(c) == '跨境']

    nav = pd.read_parquet('data/etf_nav_cifang.parquet')
    px = pd.read_parquet('data/etf_qfq_cifang.parquet',
                         columns=['code', 'date', 'open', 'close', 'low'])
    px['date'] = pd.to_datetime(px['date'])

    # ---------- 1. 全池溢价极差排名 ----------
    print('=' * 100)
    print('【1】跨境 ETF 溢价波动排名（close/nav 比值的极差，相对值）')
    print('=' * 100)
    rows = []
    for c in cross:
        n1 = nav[nav['code'] == c][['nav_date', 'unit_nav']]
        p1 = px[px['code'] == c][['date', 'close']]
        if len(n1) < 100 or len(p1) < 100:
            continue
        j = n1.merge(p1, left_on='nav_date', right_on='date', how='inner').sort_values('date')
        if len(j) < 100:
            continue
        r = j['close'] / j['unit_nav']
        rows.append({'code': c, 'name': nm.get(c, ''), 'grp':
                     '远洋' if sc.get(c) in ('美股', '日本', '欧股') else '近岸',
                     'th': bmap.get(c), 'n': len(j),
                     'min': r.min(), 'med': r.median(), 'max': r.max(),
                     'range': r.max() / r.min() - 1,
                     'prem_max': r.max() / r.median() - 1})
    pr = pd.DataFrame(rows).sort_values('range', ascending=False)
    print('%-8s %-22s %-5s %5s %10s %10s' % ('code', 'name', '组', '阈值', '极差', '最高偏离常态'))
    for _, x in pr.head(15).iterrows():
        print('%-8s %-22s %-5s %5d %9.1f%% %9.1f%%'
              % (x['code'], str(x['name'])[:20], x['grp'], x['th'],
                 x['range'] * 100, x['prem_max'] * 100))
    print()
    print('  极差 >20%% 的只数: %d / %d' % ((pr['range'] > 0.20).sum(), len(pr)))
    print('  极差 >30%% 的只数: %d' % (pr['range'] > 0.30).sum())
    print()
    for g, gg in pr.groupby('grp'):
        print('  %-5s 极差中位 %.1f%%  均值 %.1f%%  最大 %.1f%%'
              % (g, gg['range'].median() * 100, gg['range'].mean() * 100,
                 gg['range'].max() * 100))
    print()
    pr.to_csv('回测输出/premium_range_by_etf.csv', index=False, encoding='utf-8-sig')

    # ---------- 2. 策略实际买入的跨境交易 ----------
    print('=' * 100)
    print('【2】策略买入的跨境标的那几天，溢价偏离度是多少')
    print('=' * 100)

    # 构造溢价偏离度时间序列（比值 / 250 日滚动中位数 - 1）
    dev = {}
    for c in pr['code']:
        n1 = nav[nav['code'] == c][['nav_date', 'unit_nav']]
        p1 = px[px['code'] == c][['date', 'close']]
        j = n1.merge(p1, left_on='nav_date', right_on='date', how='inner').sort_values('date')
        r = pd.Series((j['close'] / j['unit_nav']).to_numpy(float),
                      index=pd.to_datetime(j['date']))
        base = r.rolling(WIN, min_periods=60).median()
        dev[c] = (r / base - 1.0)

    raw = pd.read_parquet('data/etf_qfq_cifang.parquet',
                          columns=['code', 'date', 'open', 'close', 'low'])
    raw['date'] = raw['date'].astype(str).str[:10]
    hist = {}
    for code, g in raw.groupby('code', sort=False):
        f, _ = data_quality.repair_prices(g[['date', 'open', 'close', 'low']])
        hist[code] = f.reset_index(drop=True)
    del raw
    m = bt1.build_matrices(hist, start='2021-01-01', end='2026-10-20')
    r0 = bt.run(m, bmap, max_hold=1, intraday_stop=True, exec_mode='close',
                timeout_live=True, trail=0.08, be_stop=0.03, cash_yield=0.025,
                slippage=0.002)
    tr = r0['trades']
    buys = tr[tr['action'] == 'buy'].copy()
    buys['code'] = buys['code'].astype(str).str.zfill(6)
    sells = tr[tr['action'] == 'sell'].copy()
    sells['code'] = sells['code'].astype(str).str.zfill(6)

    cb = buys[buys['code'].isin(pr['code'])].copy()
    print('  跨境买入 %d 笔 / 全部 %d 笔' % (len(cb), len(buys)))
    print()
    if len(cb):
        print('%-12s %-8s %-20s %10s %10s' % ('买入日', 'code', 'name', '溢价偏离', '该笔收益'))
        vals = []
        for _, x in cb.iterrows():
            dt = pd.Timestamp(x['date'])
            c = x['code']
            dv = np.nan
            if c in dev:
                s = dev[c]
                try:
                    dv = float(s.asof(dt))
                except Exception:
                    dv = np.nan
            # 找该笔的卖出收益（同 code、日期 >= 买入日的第一个 sell）
            sv = sells[(sells['code'] == c) & (pd.to_datetime(sells['date']) >= dt)]
            ret = float(sv.iloc[0]['ret']) if len(sv) else np.nan
            vals.append((dt, c, dv, ret))
            print('%-12s %-8s %-20s %9.2f%% %9.2f%%'
                  % (dt.date(), c, str(nm.get(c, ''))[:18],
                     dv * 100 if np.isfinite(dv) else float('nan'),
                     ret * 100 if np.isfinite(ret) else float('nan')))
        v = pd.DataFrame(vals, columns=['date', 'code', 'dev', 'ret']).dropna()
        print()
        if len(v) >= 4:
            print('  溢价偏离 与 该笔收益 的相关性 r = %.3f（n=%d）'
                  % (v['dev'].corr(v['ret']), len(v)))
            hi = v[v['dev'] > 0.05]
            lo = v[v['dev'] <= 0.05]
            if len(hi) and len(lo):
                print('    高溢价组(>5%%偏离) 平均 %.2f%% (n=%d)'
                      % (hi['ret'].mean() * 100, len(hi)))
                print('    常态组(<=5%%)     平均 %.2f%% (n=%d)'
                      % (lo['ret'].mean() * 100, len(lo)))
    print()
    print('  ⚠️ 说明：溢价偏离用「收盘后净值」计算，14:45 决策时只能用前一日，')
    print('     所以这里给出的是「事后看这笔买入踩在多高的溢价上」，不是可实盘复现的信号。')


if __name__ == '__main__':
    main()
