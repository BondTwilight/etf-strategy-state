# -*- coding: utf-8 -*-
"""拉全池日线（含 iopv），算精确溢价率，检查策略买入时的溢价暴露。

为什么重拉：现有 parquet 只存了 OHLC+volume+amount，丢掉了第 9 列 iopv。
iopv 是盘中净值估算，用它算的溢价率**无 T-1 滞后、不受份额折算影响**，
比之前用 tushare fund_nav 的做法精确得多（513100 的 523% 极差就是折算造成的假象）。

输出：
  data/etf_qfq_iopv.parquet   （含 iopv 与 prem 列）
  回测输出/premium_by_class.csv
  回测输出/premium_at_buy.csv  （策略历史买入时的溢价）
"""
import os
import sys
import json
import time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cifang_api as cf
import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

CACHE = 'data/etf_qfq_iopv.parquet'
START, END = '2015-01-01', '2026-10-20'
STD = dict(max_hold=1, intraday_stop=True, exec_mode='close', timeout_live=True,
           trail=0.08, be_stop=0.03, cash_yield=0.025, slippage=0.002)


def fetch(codes):
    if os.path.exists(CACHE):
        df = pd.read_parquet(CACHE)
        print('[缓存] %s（%d 行）' % (CACHE, len(df)))
        return df
    print('[次方] 拉取 %d 只（含 iopv）...' % len(codes))
    t0 = time.time()
    rows = []
    for i in range(0, len(codes), 50):
        batch = codes[i:i + 50]
        data = cf._get('/fund/hist_em', {
            'symbol': ','.join(batch), 'start_date': START,
            'end_date': END, 'adjust': 'qfq'}) or {}
        for code, arr in data.items():
            if not arr:
                continue
            for r in arr:
                rows.append({'code': str(code), 'date': str(r[0])[:10],
                             'open': r[1], 'close': r[2], 'high': r[3],
                             'low': r[4], 'volume': r[6], 'amount': r[7],
                             'iopv': r[8] if len(r) > 8 else np.nan})
        print('  批次 %d/%d  累计 %d 行  %.0fs'
              % (i // 50 + 1, (len(codes) + 49) // 50, len(rows), time.time() - t0),
              flush=True)
        time.sleep(0.8)
    df = pd.DataFrame(rows)
    for c in ('open', 'close', 'high', 'low', 'volume', 'amount', 'iopv'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['prem'] = df['close'] / df['iopv'] - 1.0
    os.makedirs('data', exist_ok=True)
    df.to_parquet(CACHE, index=False)
    print('[次方] 已缓存 %s（%d 行）' % (CACHE, len(df)))
    return df


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


def main():
    d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
    cmap = d.get('cmap', {}); sc = d.get('subclass', {})
    bmap = {str(k): int(v) for k, v in d['bmap'].items()}
    nm = d.get('name', {})
    codes = [str(c) for c in d['codes']]

    df = fetch(codes)
    df['code'] = df['code'].astype(str).str.zfill(6)
    print('覆盖 %d 只 / %d 行 ｜ iopv 有效率 %.1f%%'
          % (df['code'].nunique(), len(df),
             100.0 * df['iopv'].notna().mean()))
    print()

    # ---------- 1. 各组溢价水平 ----------
    df['grp'] = df['code'].map(lambda c: grp_of(c, cmap, sc, bmap))
    ok = df[np.isfinite(df['prem'])].copy()
    print('=' * 104)
    print('【1】各组溢价率分布（收盘价/iopv−1，日频，2021 年后）')
    print('=' * 104)
    ok21 = ok[ok['date'] >= '2021-01-01']
    print('%-8s %6s %10s %10s %10s %10s %10s'
          % ('组', '只数', '均值', 'P5', '中位', 'P95', 'P95-P5'))
    for g, gg in ok21.groupby('grp'):
        p = gg['prem']
        print('%-8s %6d %9.2f%% %9.2f%% %9.2f%% %9.2f%% %9.2f%%'
              % (g, gg['code'].nunique(), p.mean() * 100, p.quantile(.05) * 100,
                 p.median() * 100, p.quantile(.95) * 100,
                 (p.quantile(.95) - p.quantile(.05)) * 100))
    print()

    # ---------- 2. 高溢价标的排名 ----------
    print('=' * 104)
    print('【2】溢价最高的 12 只（2021 年后中位溢价）')
    print('=' * 104)
    st = ok21.groupby('code').agg(n=('prem', 'size'), med=('prem', 'median'),
                                  p95=('prem', lambda x: x.quantile(.95)),
                                  mx=('prem', 'max')).reset_index()
    st = st[st['n'] >= 100].sort_values('med', ascending=False)
    print('%-8s %-22s %-6s %6s %10s %10s %10s'
          % ('code', 'name', '组', '样本', '中位', 'P95', '最大'))
    for _, r in st.head(12).iterrows():
        print('%-8s %-22s %-6s %6d %9.2f%% %9.2f%% %9.2f%%'
              % (r['code'], str(nm.get(r['code'], ''))[:20],
                 grp_of(r['code'], cmap, sc, bmap), int(r['n']),
                 r['med'] * 100, r['p95'] * 100, r['mx'] * 100))
    print()

    # ---------- 3. 策略买入时的溢价 ----------
    print('=' * 104)
    print('【3】策略历史买入时，该标的的当日溢价')
    print('=' * 104)
    raw = df[['code', 'date', 'open', 'close', 'low']].copy()
    hist = {}
    for code, g in raw.groupby('code', sort=False):
        f, _ = data_quality.repair_prices(g.reset_index(drop=True))
        hist[code] = f
    m = bt1.build_matrices(hist, start='2021-01-01', end='2026-10-20')
    r = bt.run(m, bmap, **STD)
    tr = r['trades']
    b = tr[tr['action'] == 'buy'].copy()
    b['code'] = b['code'].astype(str).str.zfill(6)
    s = tr[tr['action'] == 'sell'].copy()
    s['code'] = s['code'].astype(str).str.zfill(6)
    pm = ok.set_index(['code', 'date'])['prem']

    print('%-12s %-8s %-20s %9s %9s %9s' % ('买入日', 'code', 'name', '买入溢价', '卖出溢价', '溢价变化'))
    print('-' * 104)
    recs = []
    for _, x in b.iterrows():
        c = x['code']; dt = str(x['date'])[:10]
        pin = pm.get((c, dt), np.nan)
        sv = s[(s['code'] == c) & (s['date'].astype(str) >= dt)]
        pout = np.nan
        if len(sv):
            pout = pm.get((c, str(sv.iloc[0]['date'])[:10]), np.nan)
        chg = (pout - pin) * 100 if np.isfinite(pin) and np.isfinite(pout) else np.nan
        recs.append({'date': dt, 'code': c, 'grp': grp_of(c, cmap, sc, bmap),
                     'prem_in': pin, 'prem_out': pout, 'prem_chg': chg})
        if np.isfinite(pin) and abs(pin) > 0.02:
            print('%-12s %-8s %-20s %8.2f%% %8.2f%% %8.2f%%'
                  % (dt, c, str(nm.get(c, ''))[:18], pin * 100,
                     pout * 100 if np.isfinite(pout) else float('nan'), chg))
    rr = pd.DataFrame(recs)
    print()
    print('  买入溢价绝对值 >2%% 的笔数: %d / %d'
          % ((rr['prem_in'].abs() > 0.02).sum(), len(rr)))
    print()
    v = rr.dropna(subset=['prem_in', 'prem_chg'])
    if len(v) >= 5:
        print('  买入溢价 与 持有期溢价变化 的相关性 r = %.3f (n=%d)'
              % (v['prem_in'].corr(v['prem_chg']), len(v)))
        hi = v[v['prem_in'] > 0.02]
        lo = v[v['prem_in'] <= 0.02]
        print('    高溢价买入(>2%%) %d 笔，平均溢价变化 %+.2f%%'
              % (len(hi), hi['prem_chg'].mean() if len(hi) else float('nan')))
        print('    低溢价买入(<=2%%) %d 笔，平均溢价变化 %+.2f%%'
              % (len(lo), lo['prem_chg'].mean() if len(lo) else float('nan')))

    os.makedirs('回测输出', exist_ok=True)
    st.to_csv('回测输出/premium_by_class.csv', index=False, encoding='utf-8-sig')
    rr.to_csv('回测输出/premium_at_buy.csv', index=False, encoding='utf-8-sig')
    print()
    print('已写出 回测输出/premium_by_class.csv / premium_at_buy.csv')


if __name__ == '__main__':
    main()
