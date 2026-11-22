# -*- coding: utf-8 -*-
"""策略与市场环境的关系：用数据回答「适合什么行情」。

三个测度：
  1. 年度对照：沪深300 / 中证1000 的年收益、波动率、最大回撤 vs 策略年收益
  2. 机会供给：每年「有候选的天数」——这是策略的"开工率"
  3. 条件收益：把每个交易日按「市场处于什么状态」分组，看后续策略触发后的结果
     状态定义（全部只用当日及之前数据）：
       牛/熊   = 指数相对 250 日前的涨跌（>+15% 牛 / <-15% 熊 / 其余震荡）
       高波动  = 指数 20 日已实现波动率 > 过去 250 日的中位数
"""
import os
import sys
import json
import numpy as np
import pandas as pd

BASE = r'E:\workbuddy1.0\量化agent\etf_dip_signal'
sys.path.insert(0, BASE)
import bt_etf_dip as bt1
import data_quality

PARQ = os.path.join(BASE, 'data', 'etf_qfq_cifang.parquet')
POOL = os.path.join(BASE, 'data', 'fixed_pool.json')


def load_market():
    """用 510300（沪深300ETF）与 512100（中证1000ETF）代表市场。"""
    df = pd.read_parquet(PARQ, columns=['code', 'date', 'close'])
    df['date'] = pd.to_datetime(df['date'])
    out = {}
    for c, nm in (('510300', '沪深300'), ('512100', '中证1000')):
        g = df[df['code'] == c].sort_values('date')
        if len(g) < 200:
            continue
        s = g.set_index('date')['close'].astype(float)
        out[nm] = s
    return out


def year_stats(s):
    r = s.pct_change().dropna()
    rows = []
    for y, g in r.groupby(r.index.year):
        px = s[s.index.year == y]
        if len(px) < 20:
            continue
        tot = px.iloc[-1] / px.iloc[0] - 1
        vol = g.std() * np.sqrt(244)
        dd = (px / px.cummax() - 1).min()
        rows.append({'year': y, 'ret': tot, 'vol': vol, 'dd': dd,
                     'n': len(g)})
    return pd.DataFrame(rows)


def main():
    mk = load_market()
    print('市场数据：', {k: (v.index.min().date(), v.index.max().date(), len(v))
                     for k, v in mk.items()})
    print()

    # ---------- 1. 年度对照 ----------
    print('=' * 108)
    print('【1】年度对照（策略取聚宽实测净值节点）')
    print('=' * 108)
    strat = {2022: 0.4822, 2023: 0.0358, 2024: 0.6719, 2025: 0.1943, 2026: 0.4360}
    ntr = {2022: 14, 2023: 1, 2024: 8, 2025: 7, 2026: 11}
    tabs = []
    for nm, s in mk.items():
        t = year_stats(s)
        t['name'] = nm
        tabs.append(t)
    hs = tabs[0]
    print('%-6s %6s %10s %10s %10s %10s %8s %6s'
          % ('年份', '笔数', '策略', '沪深300', '中证1000', '300波动率', '300回撤', '超额'))
    for _, r in hs.iterrows():
        y = int(r['year'])
        if y not in strat:
            continue
        try:
            zz = tabs[1][tabs[1]['year'] == y]['ret'].iloc[0]
        except Exception:
            zz = np.nan
        print('%-6d %6d %+9.2f%% %+9.2f%% %+9.2f%% %9.2f%% %7.2f%% %+7.2f%%'
              % (y, ntr[y], strat[y] * 100, r['ret'] * 100, zz * 100,
                 r['vol'] * 100, r['dd'] * 100, (strat[y] - r['ret']) * 100))
    print()

    # ---------- 2. 机会供给 ----------
    print('=' * 108)
    print('【2】机会供给：每年「有候选的天数」（= 策略的开工率）')
    print('=' * 108)
    d = json.load(open(POOL, encoding='utf-8'))
    bmap = {str(k): int(v) for k, v in d['bmap'].items()}
    raw = pd.read_parquet(PARQ, columns=['code', 'date', 'open', 'close', 'low'])
    raw['date'] = raw['date'].astype(str).str[:10]
    hist = {}
    for code, g in raw.groupby('code', sort=False):
        f, _ = data_quality.repair_prices(g[['date', 'open', 'close', 'low']])
        hist[code] = f.reset_index(drop=True)
    del raw
    m = bt1.build_matrices(hist, start='2022-01-01', end='2026-11-03')
    codes = list(m['codes'])
    th = np.array([bmap.get(c, -16) for c in codes], dtype=float)
    cand = (m['bmin5'] < th[None, :]) & m['valid']
    ncand = cand.sum(axis=1)
    dates = pd.to_datetime(m['dates'])
    print('%-6s %8s %10s %12s %12s %14s'
          % ('年份', '交易日', '有候选日', '占比', '候选总数', '单日候选均值'))
    for y in range(2022, 2027):
        msk = dates.year == y
        if msk.sum() == 0:
            continue
        print('%-6d %8d %10d %11.1f%% %12d %14.1f'
              % (y, msk.sum(), (ncand[msk] > 0).sum(),
                 100.0 * (ncand[msk] > 0).mean(), ncand[msk].sum(),
                 ncand[msk].mean()))
    print()

    # ---------- 3. 市场状态条件化 ----------
    print('=' * 108)
    print('【3】把「沪深300 所处状态」与「策略是否有候选」交叉')
    print('=' * 108)
    hs300 = mk['沪深300']
    px = hs300.reindex(dates).ffill()
    ret250 = (px / px.shift(250) - 1)
    vol20 = px.pct_change().rolling(20).std() * np.sqrt(244)
    volmed = vol20.rolling(250).median()

    state = np.where(ret250 > 0.15, '牛市(250日涨>15%)',
                     np.where(ret250 < -0.15, '熊市(250日跌>15%)', '震荡'))
    hivol = (vol20 > volmed)
    df = pd.DataFrame({'date': dates, 'state': state,
                       'hivol': hivol.reindex(dates).fillna(False).values,
                       'ncand': ncand})
    df = df[df['date'] >= '2022-01-01']
    print('%-22s %8s %10s %12s %12s' % ('市场状态', '交易日', '有候选日', '占比', '平均候选数'))
    for st in ('牛市(250日涨>15%)', '震荡', '熊市(250日跌>15%)'):
        g = df[df['state'] == st]
        if len(g) == 0:
            continue
        print('%-22s %8d %10d %11.1f%% %12.2f'
              % (st, len(g), (g['ncand'] > 0).sum(),
                 100.0 * (g['ncand'] > 0).mean(), g['ncand'].mean()))
    print()
    print('%-22s %8s %10s %12s %12s' % ('波动状态', '交易日', '有候选日', '占比', '平均候选数'))
    for hv, nm in ((True, '高波动(v20>250中位)'), (False, '低波动')):
        g = df[df['hivol'] == hv]
        if len(g) == 0:
            continue
        print('%-22s %8d %10d %11.1f%% %12.2f'
              % (nm, len(g), (g['ncand'] > 0).sum(),
                 100.0 * (g['ncand'] > 0).mean(), g['ncand'].mean()))
    print()

    # ---------- 4. 月度相关性 ----------
    print('=' * 108)
    print('【4】策略月度收益 vs 沪深300 月度收益（用交易盈亏近似）')
    print('=' * 108)
    tx = pd.read_csv(r'C:\Users\Twilight\Desktop\无敌2\transaction.csv', encoding='gbk')
    tx['日期'] = pd.to_datetime(tx['日期'])
    tx['pnl'] = tx['平仓盈亏'].astype(float)
    mon = tx.set_index('日期')['pnl'].resample('ME').sum()
    mon = mon[mon != 0]
    mk_mon = px.resample('ME').last().pct_change()
    j = pd.concat([mon.rename('strat_pnl'), mk_mon.rename('hs300')], axis=1).dropna()
    print('  有交易且可比对的月份 %d 个' % len(j))
    if len(j) >= 6:
        print('  月度盈亏 与 沪深300 月度收益 的相关系数 r = %.3f'
              % j['strat_pnl'].corr(j['hs300']))
        # 按市场涨跌分组
        up = j[j['hs300'] > 0]['strat_pnl']
        dn = j[j['hs300'] <= 0]['strat_pnl']
        print('    市场上行月 %d 个，策略平均盈亏 %+.0f 元' % (len(up), up.mean() if len(up) else 0))
        print('    市场下行月 %d 个，策略平均盈亏 %+.0f 元' % (len(dn), dn.mean() if len(dn) else 0))
    print()

    os.makedirs(os.path.join(BASE, '回测输出'), exist_ok=True)
    df.to_csv(os.path.join(BASE, '回测输出', 'market_state_vs_candidates.csv'),
              index=False, encoding='utf-8-sig')
    print('已写出 回测输出/market_state_vs_candidates.csv')


if __name__ == '__main__':
    main()
