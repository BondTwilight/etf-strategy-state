# -*- coding: utf-8 -*-
"""用真实指数（非 ETF）重算年度市场环境，避免 ETF 分红/复权造成的偏差。

数据源：tushare 中转站 index_daily
  000300.SH 沪深300 ｜ 000852.SH 中证1000 ｜ 000905.SH 中证500
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, r'E:\workbuddy1.0\量化agent\etf_dip_signal')

TOKEN = '405585c460d0d7d686644d58e138ea06d34915cee14e9c8914e5ea64'
URL = 'https://fast.xiaodefa.cn'
CACHE = r'E:\workbuddy1.0\量化agent\etf_dip_signal\data\index_daily.parquet'


def fetch():
    if os.path.exists(CACHE):
        return pd.read_parquet(CACHE)
    import tushare as ts
    ts.set_token(TOKEN)
    pro = ts.pro_api()
    pro._DataApi__http_url = URL
    rows = []
    for code, nm in (('000300.SH', '沪深300'), ('000852.SH', '中证1000'),
                     ('000905.SH', '中证500'), ('000001.SH', '上证指数')):
        try:
            d = pro.index_daily(ts_code=code, start_date='20210101', end_date='20261110')
        except Exception as e:
            print('%s 失败: %s' % (nm, str(e)[:80]))
            continue
        if d is None or len(d) == 0:
            print('%s 无数据' % nm)
            continue
        d = d[['trade_date', 'close']].copy()
        d['name'] = nm
        rows.append(d)
        print('%-8s %d 行  %s ~ %s' % (nm, len(d), d['trade_date'].min(), d['trade_date'].max()))
    if not rows:
        return pd.DataFrame()
    df = pd.concat(rows, ignore_index=True)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values(['name', 'trade_date'])
    df.to_parquet(CACHE, index=False)
    return df


def main():
    df = fetch()
    if df.empty:
        print('无数据')
        return
    print()
    print('=' * 100)
    print('【指数年度收益（真实指数，非 ETF）】')
    print('=' * 100)
    names = list(dict.fromkeys(df['name']))
    years = list(range(2022, 2027))
    print('%-8s' % '指数' + ''.join('%12d' % y for y in years))
    print('-' * 100)
    tab = {}
    for nm in names:
        g = df[df['name'] == nm].set_index('trade_date')['close'].astype(float)
        line = '%-8s' % nm
        tab[nm] = {}
        for y in years:
            sub = g[g.index.year == y]
            if len(sub) < 20:
                line += '%12s' % '-'
                continue
            r = sub.iloc[-1] / sub.iloc[0] - 1
            tab[nm][y] = r
            line += '%11.2f%%' % (r * 100)
        print(line)
    print()

    print('=' * 100)
    print('【指数年度波动率 / 最大回撤】')
    print('=' * 100)
    print('%-8s' % '指数' + ''.join('%18d' % y for y in years))
    print('-' * 100)
    for nm in names:
        g = df[df['name'] == nm].set_index('trade_date')['close'].astype(float)
        line = '%-8s' % nm
        for y in years:
            sub = g[g.index.year == y]
            if len(sub) < 20:
                line += '%18s' % '-'
                continue
            r = sub.pct_change().dropna()
            vol = r.std() * np.sqrt(244)
            dd = (sub / sub.cummax() - 1).min()
            line += '%10.1f%%/%6.1f%%' % (vol * 100, dd * 100)
        print(line)
    print('  （格式：波动率/最大回撤）')
    print()

    # 策略 vs 市场
    print('=' * 100)
    print('【策略年收益 vs 市场年收益】')
    print('=' * 100)
    strat = {2022: 0.4822, 2023: 0.0358, 2024: 0.6719, 2025: 0.1943, 2026: 0.4360}
    ntr = {2022: 14, 2023: 1, 2024: 8, 2025: 7, 2026: 11}
    cand = {2022: (39, 262), 2023: (5, 5), 2024: (28, 143),
            2025: (31, 338), 2026: (51, 780)}
    hs = tab.get('沪深300', {})
    zz = tab.get('中证1000', {})
    print('%-6s %5s %9s %9s %9s %9s %12s'
          % ('年份', '笔数', '策略', '沪深300', '中证1000', '超额(vs300)', '候选日/候选数'))
    for y in years:
        if y not in strat or y not in hs:
            continue
        print('%-6d %5d %+8.2f%% %+8.2f%% %+8.2f%% %+8.2f%% %6d/%-6d'
              % (y, ntr[y], strat[y] * 100, hs[y] * 100, zz.get(y, np.nan) * 100,
                 (strat[y] - hs[y]) * 100, cand[y][0], cand[y][1]))
    print()

    # 相关性
    print('=' * 100)
    print('【年度层面：策略收益 与 市场收益 的相关性（n=5，仅方向参考）】')
    print('=' * 100)
    ys = [y for y in years if y in strat and y in hs]
    a = np.array([strat[y] for y in ys])
    b = np.array([hs[y] for y in ys])
    print('  年份 %s' % ys)
    print('  策略 %s' % np.round(a * 100, 1))
    print('  沪深300 %s' % np.round(b * 100, 1))
    print('  相关系数 r = %.3f（n=%d，样本太少，只能看方向）'
          % (np.corrcoef(a, b)[0, 1], len(ys)))
    print()
    print('  下跌年（300 为负）：策略 %s' % np.round([strat[y] * 100 for y in ys if hs[y] < 0], 2))
    print('  上涨年（300 为正）：策略 %s' % np.round([strat[y] * 100 for y in ys if hs[y] > 0], 2))


if __name__ == '__main__':
    main()
