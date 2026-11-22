# -*- coding: utf-8 -*-
"""溢价闸门 v2：用 iopv 精确溢价（无 T-1 滞后、无份额折算问题）。

v1 失败的原因（用 tushare fund_nav）：
  · 净值 T-1/T-2 滞后，QDII 尤甚
  · 513100/513500 的净值含份额折算，极差算出 523%/133% 的假值
  · 用「相对 250 日中位数的偏离」而非绝对溢价，语义模糊

v2 改用次方日线的 iopv 列，直接算 收盘价/iopv−1。

核心先验（上一轮实测）：
  买入溢价 与 持有期溢价变化 r = -0.600
  低溢价/折价买入 30 笔 → 持有期溢价 +3.03%
  高溢价买入 9 笔 → 持有期溢价 +0.47%
⇒ 折价回归是额外收益来源，值得做闸门

★ 14:45 决策时当日 iopv 未定，只能用「前一日溢价」，本脚本严格如此。
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
NOISE = 3.9


def go(m, bmap, **kw):
    a = dict(STD); a.update(kw)
    r = bt.run(m, bmap, **a)
    return r, bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])


def nb(r):
    t = r['trades']
    return int((t['action'] == 'buy').sum()) if len(t) else 0


def line(name, p, n):
    wr = p['win_rate'] * 100 if np.isfinite(p['win_rate']) else float('nan')
    print('%-32s %+8.2f%% %+8.2f%% %8.2f%% %7.2f %6.2f %5.1f%% %4d'
          % (name, p['total_return'] * 100, p['cagr'] * 100, p['max_dd'] * 100,
             p['calmar'], p['sharpe'], wr, n))


def main():
    d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
    cmap = d.get('cmap', {}); sc = d.get('subclass', {})
    bmap = {str(k): int(v) for k, v in d['bmap'].items()}

    iop = pd.read_parquet('data/etf_qfq_iopv.parquet')
    iop['code'] = iop['code'].astype(str).str.zfill(6)
    iop['date'] = iop['date'].astype(str).str[:10]

    raw = iop[['code', 'date', 'open', 'close', 'low']].copy()
    hist = {}
    for code, g in raw.groupby('code', sort=False):
        f, _ = data_quality.repair_prices(g.reset_index(drop=True))
        hist[code] = f
    m = bt1.build_matrices(hist, start=START, end=END)
    codes = list(m['codes']); n = m['close'].shape[0]
    dates = pd.to_datetime(m['dates'])
    print('矩阵 %d x %d' % (n, len(codes)))

    # 溢价矩阵（前一日值）
    PREM = np.full((n, len(codes)), np.nan)
    col = {c: i for i, c in enumerate(codes)}
    filled = 0
    for c in codes:
        g = iop[iop['code'] == c][['date', 'prem']].dropna()
        if len(g) < 100:
            continue
        s = pd.Series(g['prem'].to_numpy(float),
                      index=pd.to_datetime(g['date'])).sort_index()
        s = s[~s.index.duplicated(keep='last')]
        v = s.reindex(dates).ffill().shift(1).to_numpy(float)
        PREM[:, col[c]] = v
        filled += 1
    fin = np.isfinite(PREM)
    print('溢价矩阵填入 %d 只 ｜ 有效值 %.1f%%' % (filled, 100.0 * fin.mean()))
    print('  注：A股 ETF 溢价恒在 ±0.2%%，闸门对它们几乎无影响；主要作用于跨境。')
    print()

    # ---------- 基线 ----------
    r0, p0 = go(m, bmap)
    print('=' * 106)
    print('【1】溢价闸门（用前一日 iopv 溢价，14:45 决策时可得）')
    print('=' * 106)
    print('%-32s %9s %9s %9s %7s %6s %6s %4s'
          % ('', '总收益', '年化', '回撤', 'Calmar', '夏普', '胜率', '笔数'))
    print('-' * 106)
    line('基准（无溢价过滤）', p0, nb(r0))

    store = {}
    for cap in (0.00, 0.02, 0.05, 0.10, 0.20):
        mask = ~(np.isfinite(PREM) & (PREM > cap))
        r, p = go(m, bmap, liq=mask)
        store[cap] = (r, p, mask)
        line('前一日溢价 > %.0f%% 不买' % (cap * 100), p, nb(r))
    # 反向：只买折价
    mask_neg = ~(np.isfinite(PREM) & (PREM > 0))
    r, p = go(m, bmap, liq=mask_neg)
    store['neg'] = (r, p, mask_neg)
    line('只买折价（溢价<=0）', p, nb(r))
    print()

    # ---------- walk-forward ----------
    print('=' * 106)
    print('【2】walk-forward（拟合 2021-2023 / 检验 2024-2026）')
    print('=' * 106)

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
    print('%-28s %13s %13s %12s' % ('', '拟合段', '检验段', '判定'))
    print('-' * 106)
    print('%-28s %12.2f%% %12.2f%%' % ('基准', bf, bh))
    for k, (r, p, mask) in store.items():
        tag = '只买折价' if k == 'neg' else ('溢价>%.0f%%不买' % (k * 100))
        cf = go(mf, bmap, liq=mask[idf])[1]['cagr'] * 100
        ch = go(mh, bmap, liq=mask[idh])[1]['cagr'] * 100
        df_, dh = cf - bf, ch - bh
        if df_ > NOISE * 0.5 and dh > NOISE * 0.5:
            flag = '✅ 两段显著'
        elif df_ > 0 and dh > 0:
            flag = '△ 两段同向'
        elif (df_ > 0) != (dh > 0):
            flag = '⚠️ 方向不一致'
        else:
            flag = '❌ 两段同负'
        print('%-28s %12.2f%% %12.2f%%  %s (Δ%+.1f/%+.1f)'
              % (tag, cf, ch, flag, df_, dh))
    print()

    # ---------- 起点敏感性（新铁律） ----------
    print('=' * 106)
    print('【3】起点敏感性扫描（铁律：符号翻转即判噪声）')
    print('=' * 106)
    print('%-24s %14s %14s %14s' % ('配置', '2021起', '2022起', '2023起'))
    print('-' * 106)
    for tag, kw in [('基准', {}), ('只买折价', dict(liq=store['neg'][2])),
                    ('溢价>5%不买', dict(liq=store[0.05][2]))]:
        vals = []
        for st in ('2021-01-01', '2022-01-01', '2023-01-01'):
            mm = bt1.build_matrices(hist, start=st, end=END)
            # 重新对齐掩码（行数变了）
            dd = pd.to_datetime(mm['dates'])
            idx = np.array([np.where(dates == x)[0][0] for x in dd])
            kk = dict(kw)
            if 'liq' in kk:
                kk['liq'] = kk['liq'][idx]
            vals.append(go(mm, bmap, **kk)[1]['cagr'] * 100)
        sign = '同号' if (vals[1] - vals[0]) * (vals[2] - vals[0]) > 0 else '**翻转**'
        print('%-24s %13.2f%% %13.2f%% %13.2f%%  %s'
              % (tag, vals[0], vals[1], vals[2], sign))
    print()

    os.makedirs('回测输出', exist_ok=True)
    rows = [{'variant': 'base', 'cagr': p0['cagr'], 'max_dd': p0['max_dd'],
             'calmar': p0['calmar'], 'trades': nb(r0)}]
    for k, (r, p, _) in store.items():
        rows.append({'variant': str(k), 'cagr': p['cagr'], 'max_dd': p['max_dd'],
                     'calmar': p['calmar'], 'trades': nb(r)})
    pd.DataFrame(rows).to_csv('回测输出/premium_gate_v2.csv', index=False,
                              encoding='utf-8-sig')
    print('已写出 回测输出/premium_gate_v2.csv')


if __name__ == '__main__':
    main()
