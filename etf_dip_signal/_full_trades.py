# -*- coding: utf-8 -*-
"""2022 至今全量逐笔：买卖配对、持仓交易日、盈亏、标的分布。

口径 = 原版（无移动止盈/无保本止损）+ 2 tick + timeout_live=True
      与聚宽 v4.6 对齐（聚宽实测 41.13% / 17.71%）。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

START = '2022-01-01'
END = '2026-11-04'
NEW = os.path.join(BASE, 'data', 'etf_qfq_cifang_1104.parquet')
PARK = os.path.join(BASE, 'data', 'etf_qfq_cifang.parquet')


def make_hist():
    d = pd.read_parquet(NEW, columns=['code', 'date', 'open', 'close', 'low'])
    d['date'] = d['date'].astype(str).str[:10]
    hist = {}
    for code, g in d.groupby('code', sort=False):
        g = g.sort_values('date').reset_index(drop=True)
        f, _ = data_quality.repair_prices(g, jump_th=0.30)
        hist[code] = f.reset_index(drop=True)
    return hist


def main():
    pool = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'),
                          encoding='utf-8'))
    bmap = pool['bmap']
    cmap = pool.get('cmap', {})
    sub = pool.get('subclass', {})
    nm = pool.get('name', {}) or pool.get('names', {}) or {}

    hist = make_hist()
    m = bt1.build_matrices(hist, start=START, end=END)
    th_map = dict((c, bmap.get(c, -16)) for c in m['codes'])
    r = bt.run(m, th_map, max_hold=1, intraday_stop=False, exec_mode='close',
               timeout_live=True, trail=None, be_stop=None, cash_yield=0.025,
               slippage=0.0010, tick_frac=2.0)

    dates = list(m['dates'])
    idx = {d: i for i, d in enumerate(dates)}
    t = r['trades'].copy()
    t['d'] = t['date'].astype(str).str[:10]

    buys = t[t['action'] == 'buy'].reset_index(drop=True)
    sells = t[t['action'] == 'sell'].reset_index(drop=True)
    n = min(len(buys), len(sells))

    rows = []
    for i in range(n):
        b, s = buys.loc[i], sells.loc[i]
        ed, xd = b['d'], s['d']
        hold_td = idx.get(xd, 0) - idx.get(ed, 0)
        edt, xdt = pd.Timestamp(ed), pd.Timestamp(xd)
        rows.append({
            'seq': i + 1,
            'code': b['code'],
            'name': nm.get(b['code'], ''),
            'cmap': cmap.get(b['code'], ''),
            'sub': sub.get(b['code'], ''),
            'th': bmap.get(b['code'], -16),
            'entry': ed, 'entry_px': round(float(b['price']), 4),
            'exit': xd, 'exit_px': round(float(s['price']), 4),
            'hold_td': hold_td,
            'hold_cal': (xdt - edt).days,
            'ret': float(s['ret']) if pd.notna(s.get('ret')) else np.nan,
            'reason': s.get('reason', ''),
            'win': 1 if (pd.notna(s.get('ret')) and float(s['ret']) > 0) else 0,
        })
    # 期末未平仓
    if len(buys) > len(sells):
        b = buys.loc[len(sells)]
        last_px = float(hist[b['code']].iloc[-1]['close'])
        rows.append({
            'seq': len(rows) + 1, 'code': b['code'],
            'name': nm.get(b['code'], ''), 'cmap': cmap.get(b['code'], ''),
            'sub': sub.get(b['code'], ''), 'th': bmap.get(b['code'], -16),
            'entry': b['d'], 'entry_px': round(float(b['price']), 4),
            'exit': '持仓中', 'exit_px': round(last_px, 4),
            'hold_td': idx.get(dates[-1], 0) - idx.get(b['d'], 0),
            'hold_cal': (pd.Timestamp(dates[-1]) - pd.Timestamp(b['d'])).days,
            'ret': last_px / float(b['price']) - 1,
            'reason': '(未平仓)',
            'win': 1 if last_px > float(b['price']) else 0,
        })

    df = pd.DataFrame(rows)
    closed = df[df['reason'] != '(未平仓)'].copy()

    # ---------- 输出 ----------
    print('=' * 132)
    print('【逐笔明细】%s ~ %s ｜ %d 笔买入 / %d 笔卖出 ｜ 期末 %s'
          % (START, END, len(buys), len(sells),
             df.iloc[-1]['code'] if len(df) and df.iloc[-1]['reason'] == '(未平仓)' else '空仓'))
    print('=' * 132)
    print('%-4s %-10s %-8s %-8s %-6s %-8s %-10s %-8s %5s %5s %9s  %s'
          % ('#', '买入日', '标的', '名称', '类别', '买入价', '卖出日', '卖出价',
             '持日', '持历', '收益', '原因'))
    for _, x in df.iterrows():
        print('%-4d %-10s %-8s %-8s %-6s %8.4f %-10s %8.4f %5d %5d %+8.2f%%  %s'
              % (x['seq'], x['entry'], x['code'], str(x['name'])[:8],
                 str(x['cmap'])[:4] or '-', x['entry_px'], x['exit'], x['exit_px'],
                 x['hold_td'], x['hold_cal'], x['ret'] * 100, x['reason']))

    # ---------- 汇总 ----------
    print()
    print('=' * 100)
    print('【一】核心统计（已平仓 %d 笔）' % len(closed))
    print('=' * 100)
    w = closed[closed['win'] == 1]
    l = closed[closed['win'] == 0]
    r_all = closed['ret']
    print('  胜率           %.1f%%（%d 胜 / %d 负）' % (len(w) / len(closed) * 100, len(w), len(l)))
    print('  平均单笔       %+.2f%% ｜ 中位 %+.2f%%'
          % (r_all.mean() * 100, r_all.median() * 100))
    print('  平均盈利       %+.2f%%（最大 %+.2f%%）'
          % (w['ret'].mean() * 100, w['ret'].max() * 100))
    if len(l):
        print('  平均亏损       %+.2f%%（最深 %+.2f%%）'
              % (l['ret'].mean() * 100, l['ret'].min() * 100))
        print('  盈亏比(均值)   %.2f : 1' % (abs(w['ret'].mean() / l['ret'].mean())))
        print('  盈亏平衡胜率   %.1f%%'
              % (abs(l['ret'].mean()) / (w['ret'].mean() + abs(l['ret'].mean())) * 100))
    print('  单笔最差       %+.2f%% ｜ 单笔最好 %+.2f%%'
          % (r_all.min() * 100, r_all.max() * 100))
    print('  收益 >+15%%     %d 笔 ｜ >+10%% %d 笔 ｜ >+5%% %d 笔 ｜ 负收益 %d 笔'
          % ((r_all > 0.15).sum(), (r_all > 0.10).sum(),
             (r_all > 0.05).sum(), (r_all <= 0).sum()))
    eq = r['equity']
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    print('  区间年化       %+.2f%%（%.2f 年）｜ 最大回撤 %.2f%%'
          % (((eq.iloc[-1] / 100000) ** (1 / yrs) - 1) * 100, yrs,
             (eq / eq.cummax() - 1).min() * 100))

    print()
    print('=' * 100)
    print('【二】持仓时长')
    print('=' * 100)
    print('  交易日：均值 %.1f ｜ 中位 %.0f ｜ 最短 %d ｜ 最长 %d'
          % (closed['hold_td'].mean(), closed['hold_td'].median(),
             closed['hold_td'].min(), closed['hold_td'].max()))
    print('  日历日：均值 %.1f ｜ 中位 %.0f ｜ 最短 %d ｜ 最长 %d'
          % (closed['hold_cal'].mean(), closed['hold_cal'].median(),
             closed['hold_cal'].min(), closed['hold_cal'].max()))
    print('  分布：≤3日 %d 笔 ｜ 4~10日 %d 笔 ｜ 11~20日 %d 笔 ｜ >20日 %d 笔'
          % ((closed['hold_td'] <= 3).sum(), ((closed['hold_td'] > 3) & (closed['hold_td'] <= 10)).sum(),
             ((closed['hold_td'] > 10) & (closed['hold_td'] <= 20)).sum(),
             (closed['hold_td'] > 20).sum()))
    print('  持有占比（交易日）：%.1f%%'
          % (closed['hold_td'].sum() / len(dates) * 100))
    print('  ⇒ 按交易日算，年换手约 %.1f 次'
          % (len(closed) / yrs))

    print()
    print('=' * 100)
    print('【三】按卖出原因')
    print('=' * 100)
    print('  %-10s %5s %8s %9s %9s %9s' % ('原因', '笔数', '胜率', '平均收益', '平均持日', '合计贡献'))
    for rsn, g in closed.groupby('reason'):
        print('  %-10s %5d %7.0f%% %+8.2f%% %9.1f %+8.1f%%'
              % (rsn, len(g), g['win'].mean() * 100, g['ret'].mean() * 100,
                 g['hold_td'].mean(), g['ret'].sum() * 100))

    print()
    print('=' * 100)
    print('【四】按类别（cmap）')
    print('=' * 100)
    print('  %-12s %5s %8s %9s %9s' % ('类别', '笔数', '胜率', '平均收益', '合计贡献'))
    for c, g in closed.groupby('cmap'):
        print('  %-12s %5d %7.0f%% %+8.2f%% %+8.1f%%'
              % (str(c) or '(空)', len(g), g['win'].mean() * 100,
                 g['ret'].mean() * 100, g['ret'].sum() * 100))

    print()
    print('=' * 100)
    print('【五】按年度')
    print('=' * 100)
    closed['yr'] = pd.to_datetime(closed['entry']).dt.year
    print('  %-6s %5s %8s %10s %10s' % ('年份', '笔数', '胜率', '平均收益', '合计贡献'))
    for y, g in closed.groupby('yr'):
        print('  %-6d %5d %7.0f%% %+9.2f%% %+9.1f%%'
              % (y, len(g), g['win'].mean() * 100, g['ret'].mean() * 100,
                 g['ret'].sum() * 100))

    print()
    print('=' * 100)
    print('【六】标的复买情况')
    print('=' * 100)
    cc = closed.groupby('code').agg(
        n=('ret', 'size'), wins=('win', 'sum'),
        avg=('ret', 'mean'), tot=('ret', 'sum')).sort_values('n', ascending=False)
    rep = cc[cc['n'] > 1]
    print('  共买过 %d 只不同标的，其中 %d 只被买过 2 次以上' % (len(cc), len(rep)))
    if len(rep):
        print('  %-8s %-14s %3s %5s %9s %9s' % ('代码', '名称', '次数', '胜', '平均', '合计'))
        for c, x in rep.iterrows():
            print('  %-8s %-14s %3d %5d %+8.2f%% %+8.1f%%'
                  % (c, str(nm.get(c, ''))[:14], int(x['n']), int(x['wins']),
                     x['avg'] * 100, x['tot'] * 100))

    # 导出
    out = os.path.join(BASE, '回测输出', 'trades_full_2022_2026.csv')
    df.to_csv(out, index=False, encoding='utf-8-sig')
    print()
    print('已写出 回测输出/trades_full_2022_2026.csv（%d 行）' % len(df))


if __name__ == '__main__':
    main()
