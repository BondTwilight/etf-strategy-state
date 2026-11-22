# -*- coding: utf-8 -*-
"""跨境 ETF 的「涨跌停卡单」风险量化 + 159529 溢价异常核查。

跨境 ETF 的标的在海外，一夜可以跌 20%，但 A 股场内 ETF 有 10% 涨跌停：
  - 持仓遇跌停 -> 卖出挂不出去（保护位失效）
  - 候选日遇涨停 -> 买不进来（信号空转，之前日志里 513350 就是）

对比各组单日「接近涨跌停」的频率。
"""
import os
import sys
import json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data_quality

LIM = 0.095      # 10% 涨跌停，留 0.5pp 缓冲（ETF 价格取整到 0.001）


def main():
    d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
    cmap = d.get('cmap', {}); sc = d.get('subclass', {}); bmap = d['bmap']
    nm = d.get('name', {})

    def grp(c):
        if cmap.get(c) == '商品':
            return '商品'
        if sc.get(c) in ('美股', '日本', '欧股'):
            return '远洋'
        if cmap.get(c) == '跨境' and bmap.get(c) == -16:
            return '近岸'
        if bmap.get(c) == -5:
            return '红利'
        return 'A股'

    px = pd.read_parquet('data/etf_qfq_cifang.parquet',
                         columns=['code', 'date', 'open', 'close', 'high', 'low'])
    px['date'] = pd.to_datetime(px['date'])
    px = px.sort_values(['code', 'date']).reset_index(drop=True)

    # 涨跌停要用不复权价算（复权后百分比不变，但绝对价会缩放，
    # 用 close/prev_close 的百分比判断与复权无关，可以直接用）
    recs = []
    for code, g in px.groupby('code', sort=False):
        if code not in bmap:
            continue
        g = g.sort_values('date').reset_index(drop=True)
        f, _ = data_quality.repair_prices(g[['date', 'open', 'close', 'low']])
        c = f['close'].to_numpy(float)
        prev = np.concatenate([[np.nan], c[:-1]])
        with np.errstate(invalid='ignore', divide='ignore'):
            r = c / prev - 1.0
        ok = np.isfinite(r)
        if ok.sum() < 100:
            continue
        recs.append({'code': code, 'grp': grp(code), 'n': int(ok.sum()),
                     'up': int((r[ok] >= LIM).sum()),
                     'dn': int((r[ok] <= -LIM).sum()),
                     'max_up': float(np.nanmax(r)), 'max_dn': float(np.nanmin(r))})
    df = pd.DataFrame(recs)

    print('=' * 96)
    print('【1】单日触及涨跌停的频率（|涨跌| >= 9.5%%，11 年样本）')
    print('=' * 96)
    print('%-8s %5s %10s %10s %12s %12s %12s'
          % ('组', '只数', '总交易日', '涨停次数', '涨停占比', '跌停占比', '单日最大跌幅'))
    for g, gg in df.groupby('grp'):
        n = gg['n'].sum()
        print('%-8s %5d %10d %10d %11.2f%% %11.2f%% %11.2f%%'
              % (g, len(gg), n, gg['up'].sum(), 100.0 * gg['up'].sum() / n,
                 100.0 * gg['dn'].sum() / n, gg['max_dn'].min() * 100))
    print()
    print('（涨停买不进 / 跌停卖不出 的直接来源）')
    print()

    # 单只最危险
    print('=' * 96)
    print('【2】跌停次数最多的 8 只（保护位在这些标的上可能失效）')
    print('=' * 96)
    top = df.nlargest(8, 'dn')
    print('%-8s %-20s %-6s %6s %6s %10s'
          % ('code', 'name', '组', '跌停', '涨停', '最大单日跌幅'))
    for _, r in top.iterrows():
        print('%-8s %-20s %-6s %6d %6d %9.2f%%'
              % (r['code'], str(nm.get(r['code'], ''))[:18], r['grp'],
                 r['dn'], r['up'], r['max_dn'] * 100))
    print()

    # 159529 溢价异常核查
    print('=' * 96)
    print('【3】159529 标普消费ETF 溢价异常核查（触发时 +16.14%）')
    print('=' * 96)
    nav = pd.read_parquet('data/etf_nav_cifang.parquet')
    n1 = nav[nav['code'] == '159529'].sort_values('nav_date')
    p1 = px[px['code'] == '159529'].sort_values('date')
    print('  净值记录 %d 行  %s ~ %s' % (len(n1), n1['nav_date'].min().date(),
                                     n1['nav_date'].max().date()))
    print('  价格记录 %d 行  %s ~ %s' % (len(p1), p1['date'].min().date(),
                                     p1['date'].max().date()))
    # 净值是否有跳变（分红/拆分会导致）
    v = n1['unit_nav'].to_numpy(float)
    jump = np.where(np.abs(v[1:] / v[:-1] - 1) > 0.15)[0]
    print('  净值单日跳变 >15%% 的次数: %d' % len(jump))
    for k in jump[:5]:
        print('    %s  %.4f -> %.4f  (%+.2f%%)'
              % (n1['nav_date'].iloc[k + 1].date(), v[k], v[k + 1],
                 (v[k + 1] / v[k] - 1) * 100))
    # 价格/净值比值的时间序列
    j = n1.merge(p1[['date', 'close']], left_on='nav_date', right_on='date', how='inner')
    j['ratio'] = j['close'] / j['unit_nav']
    print('  价格/净值比值: 最小 %.4f  中位 %.4f  最大 %.4f  极差 %.1f%%'
          % (j['ratio'].min(), j['ratio'].median(), j['ratio'].max(),
             (j['ratio'].max() / j['ratio'].min() - 1) * 100))
    print('  ---- 极值前后 5 行 ----')
    imax = j['ratio'].idxmax(); imin = j['ratio'].idxmin()
    for tag, i in (('最高', imax), ('最低', imin)):
        print('  [%s] %s  close %.4f  nav %.4f  ratio %.4f'
              % (tag, j.loc[i, 'nav_date'].date(), j.loc[i, 'close'],
                 j.loc[i, 'unit_nav'], j.loc[i, 'ratio']))
    print()
    print('  该只涨跌停：跌停 %d 次 / 涨停 %d 次 / 最大单日 %+.2f%%'
          % (int(df[df['code'] == '159529']['dn'].iloc[0]),
             int(df[df['code'] == '159529']['up'].iloc[0]),
             float(df[df['code'] == '159529']['max_dn'].iloc[0]) * 100))

    df.to_csv('回测输出/limit_hit_by_class.csv', index=False, encoding='utf-8-sig')
    print()
    print('已写出 回测输出/limit_hit_by_class.csv')


if __name__ == '__main__':
    main()
