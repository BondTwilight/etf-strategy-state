# -*- coding: utf-8 -*-
"""两个决定性检验，回答「策略赚的是均值回归还是别的」。

检验 A：把 41 笔交易按「买入日的市场状态」分组，看各状态下的单笔收益
        状态定义（只用当日及之前数据）：
          · 趋势：沪深300 相对 250 日前涨跌  → 牛(>+15%) / 震荡 / 熊(<-15%)
          · 波动：沪深300 20日已实现波动率 相对 过去 250 日中位数 → 高/低
          · 位置：沪深300 距 250 日最高点  → 深跌(<-20%) / 浅跌 / 接近高位

检验 B：合成随机游走证伪（TrustedQuant 的批评）
        生成 381 条 GBM 序列，drift 和 vol 从真实池子的历史均值抽取，
        **完全不含均值回归结构**。若策略在它上面仍能赚钱，
        说明收益来自「正 drift + 逢跌买入」，而不是真正的均值回归。
"""
import os
import sys
import json
import numpy as np
import pandas as pd

BASE = r'E:\workbuddy1.0\量化agent\etf_dip_signal'
sys.path.insert(0, BASE)
import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

PARQ = os.path.join(BASE, 'data', 'etf_qfq_cifang.parquet')
POOL = os.path.join(BASE, 'data', 'fixed_pool.json')
IDX = os.path.join(BASE, 'data', 'index_daily.parquet')
TX = r'C:\Users\Twilight\Desktop\无敌2\transaction.csv'
STD = dict(max_hold=1, intraday_stop=True, exec_mode='close', timeout_live=True,
           trail=0.08, be_stop=0.03, cash_yield=0.025, slippage=0.002)


def load_index():
    d = pd.read_parquet(IDX)
    s = d[d['name'] == '沪深300'].set_index('trade_date')['close'].astype(float)
    return s.sort_index()


def load_trades():
    df = pd.read_csv(TX, encoding='gbk')
    df['日期'] = pd.to_datetime(df['日期'])
    df['code'] = df['标的'].str.extract(r'\((\d{6})\.')[0]
    df['name'] = df['标的'].str.replace(r'\(\d{6}\.\w+\)', '', regex=True).str.strip()
    df['side'] = df['交易类型'].map({'买': 'buy', '卖': 'sell'})
    df['qty'] = df['成交数量'].str.replace('股', '', regex=False).astype(float).abs()
    df['px'] = df['成交价'].astype(float)
    df['pnl'] = df['平仓盈亏'].astype(float)
    lots, out = {}, []
    for _, r in df.sort_values(['日期', '委托时间']).iterrows():
        if r['side'] == 'buy':
            lots.setdefault(r['code'], []).append(r)
        else:
            L = lots.get(r['code'], [])
            if not L:
                continue
            b = L.pop(0)
            out.append({'code': r['code'], 'name': r['name'],
                        'entry': b['日期'], 'exit': r['日期'],
                        'ret': r['pnl'] / (b['px'] * b['qty'])})
    return pd.DataFrame(out)


def test_a():
    print('=' * 104)
    print('【检验 A】41 笔交易按「买入日的市场状态」分组')
    print('=' * 104)
    hs = load_index()
    p = load_trades()
    p['entry'] = pd.to_datetime(p['entry'])

    def state_at(dt):
        s = hs[hs.index <= dt]
        if len(s) < 260:
            return None
        cur = s.iloc[-1]
        r250 = cur / s.iloc[-251] - 1
        hi = s.iloc[-250:].max()
        pos = cur / hi - 1
        vol20 = s.iloc[-21:].pct_change().std() * np.sqrt(244)
        volmed = (s.pct_change().rolling(250).std() * np.sqrt(244)).iloc[-1]
        trend = '牛市' if r250 > 0.15 else ('熊市' if r250 < -0.15 else '震荡')
        vstate = '高波动' if vol20 > volmed else '低波动'
        pstate = '深跌(距高点<-20%)' if pos < -0.20 else (
            '回调(-5~-20%)' if pos < -0.05 else '接近高位')
        return trend, vstate, pstate, r250, vol20

    rows = []
    for _, r in p.iterrows():
        st = state_at(r['entry'])
        if st is None:
            continue
        rows.append({'entry': r['entry'], 'ret': r['ret'], 'name': r['name'],
                     'trend': st[0], 'vol': st[1], 'pos': st[2],
                     'r250': st[3], 'v20': st[4]})
    d = pd.DataFrame(rows)
    print('可归类 %d 笔' % len(d))
    print()
    for key, nm in (('trend', '市场趋势（沪深300 250日）'),
                    ('vol', '市场波动（20日 vs 250日中位）'),
                    ('pos', '市场位置（距250日高点）')):
        print('--- %s ---' % nm)
        print('%-20s %5s %6s %12s %12s %10s'
              % ('状态', '笔数', '胜率', '平均收益', '中位收益', '合计盈亏'))
        for k, g in d.groupby(key):
            print('%-20s %5d %5.0f%% %+11.2f%% %+11.2f%% %+10.0f'
                  % (k, len(g), 100.0 * (g['ret'] > 0).mean(),
                     g['ret'].mean() * 100, g['ret'].median() * 100,
                     g['ret'].sum() * 100000))
        print()
    d.to_csv(os.path.join(BASE, '回测输出', 'trades_by_market_state.csv'),
             index=False, encoding='utf-8-sig')
    return d


def test_b(n_sim=3):
    print('=' * 104)
    print('【检验 B】合成随机游走证伪：381 条 GBM，无任何均值回归结构')
    print('=' * 104)
    d = json.load(open(POOL, encoding='utf-8'))
    bmap = {str(k): int(v) for k, v in d['bmap'].items()}
    codes0 = [str(c) for c in d['codes']]

    real = pd.read_parquet(PARQ, columns=['code', 'date', 'close'])
    real['date'] = pd.to_datetime(real['date'])
    piv = real.pivot_table(index='date', columns='code', values='close')
    piv = piv[[c for c in codes0 if c in piv.columns]]
    n = len(piv)
    r = piv.pct_change()
    mu = float(r.mean().mean())        # 全池日均漂移
    sd = float(r.std().mean())         # 全池日均波动
    print('  真实池子：%d 只 × %d 天 ｜ 日均漂移 %.5f%% ｜ 日均波动 %.4f%%'
          % (piv.shape[1], n, mu * 100, sd * 100))
    print('  （年化漂移 %.2f%%、年化波动 %.1f%%）'
          % ((np.exp(mu * 244) - 1) * 100, sd * np.sqrt(244) * 100))
    print()
    print('  生成 GBM（drift=%.5f, vol=%.4f），跑 %d 次策略…' % (mu, sd, n_sim))
    print()
    print('%-6s %10s %10s %10s %8s %8s' % ('次', '总收益', '年化', '回撤', '笔数', '胜率'))
    print('-' * 104)
    res = []
    rng = np.random.default_rng(20261104)
    idx = piv.index
    for k in range(n_sim):
        arr = rng.normal(mu, sd, size=(n, piv.shape[1]))
        px = np.exp(np.cumsum(arr, axis=0)) * 100.0
        hist = {}
        for j, c in enumerate(piv.columns):
            hist[c] = pd.DataFrame({
                'date': idx.strftime('%Y-%m-%d'),
                'open': px[:, j], 'close': px[:, j], 'low': px[:, j]})
        m = bt1.build_matrices(hist, start='2022-01-01', end='2026-11-03')
        rr = bt.run(m, bmap, **STD)
        pp = bt1.perf(rr['equity'], rr['trades'], 100000.0, rr['exposure'])
        nb = int((rr['trades']['action'] == 'buy').sum()) if len(rr['trades']) else 0
        wr = pp['win_rate'] * 100 if np.isfinite(pp['win_rate']) else float('nan')
        print('%-6d %+9.1f%% %+9.2f%% %9.2f%% %8d %7.1f%%'
              % (k + 1, pp['total_return'] * 100, pp['cagr'] * 100,
                 pp['max_dd'] * 100, nb, wr))
        res.append(pp['cagr'] * 100)
    res = np.array(res)
    print()
    print('  合成世界年化：均值 %+.2f%% ｜ σ %.2fpp ｜ 区间 %.2f ~ %.2f'
          % (res.mean(), res.std(ddof=1) if len(res) > 1 else 0,
             res.min(), res.max()))
    print()
    print('  判读：')
    print('    若合成世界也大幅盈利 ⇒ 收益主要来自「正 drift + 逢跌买入」，')
    print('       不是真正的均值回归 alpha，策略应理解为「条件性做多」；')
    print('    若合成世界接近 0 或亏损 ⇒ 真实池子确实存在均值回归结构。')


if __name__ == '__main__':
    test_a()
    print()
    test_b()
