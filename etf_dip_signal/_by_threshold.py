# -*- coding: utf-8 -*-
"""按「阈值档位」重新分组（cmap 有分类错误，不能用）。

发现：159967 创业板成长被 cmap 归为「股票-股息红利」，但阈值是 -16。
若按 cmap 统计，会把 -18.01% 那笔算进"红利"，得出"红利是唯一负贡献"的错误结论。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

CSV = os.path.join(BASE, '回测输出', 'trades_full_2022_2026.csv')


def main():
    df = pd.read_csv(CSV, dtype={'code': str})
    df['code'] = df['code'].str.zfill(6)
    closed = df[df['reason'] != '(未平仓)'].copy()

    print('=' * 100)
    print('【按阈值档位分组】（正确口径；cmap 有误，如 159967 被归为红利但阈值 -16）')
    print('=' * 100)
    print('  %-10s %5s %8s %10s %11s %s'
          % ('档位', '笔数', '胜率', '平均收益', '合计贡献', '标的'))
    for th, g in closed.groupby('th'):
        codes = ', '.join(sorted(set(g['code'])))
        print('  %-10s %5d %7.0f%% %+9.2f%% %+10.1f%%  %s'
              % ('%d%%' % th, len(g), g['win'].mean() * 100,
                 g['ret'].mean() * 100, g['ret'].sum() * 100, codes[:40]))

    print()
    print('=' * 100)
    print('【红利的真实表现】（只取阈值 -5 的 5 笔）')
    print('=' * 100)
    div = closed[closed['th'] == -5]
    for _, x in div.iterrows():
        print('  %-10s %-8s %+7.2f%%  %s' % (x['entry'], x['code'],
                                             x['ret'] * 100, x['reason']))
    print('  ⇒ %d 笔，胜率 %.0f%%，平均 %+.2f%%，合计 %+.1f%%'
          % (len(div), div['win'].mean() * 100, div['ret'].mean() * 100,
             div['ret'].sum() * 100))
    print('  ⇒ 修正前按 cmap 算出的「红利 -1.1%%」是把 159967(-18.01%%) 错算进来的结果')

    print()
    print('=' * 100)
    print('【唯一亏损那笔的完整解剖】')
    print('=' * 100)
    loss = closed[closed['ret'] < 0]
    for _, x in loss.iterrows():
        print('  买入 %s %s(%s) @%.4f  阈值 %d%%'
              % (x['entry'], x['code'], x['name'], x['entry_px'], x['th']))
        print('  卖出 %s @%.4f  持有 %d 个交易日  收益 %+.2f%%  原因：%s'
              % (x['exit'], x['exit_px'], x['hold_td'], x['ret'] * 100, x['reason']))
    print()
    print('  ⇒ 这一笔是全期唯一亏损，也是唯一触发止损的样本。')
    print('     n=1 意味着：无法验证「-15%% 止损」到底该设多宽，也无法估计平均亏损。')

    print()
    print('=' * 100)
    print('【标的贡献排名】（前 10 / 后 5）')
    print('=' * 100)
    cc = closed.groupby('code').agg(
        n=('ret', 'size'), avg=('ret', 'mean'), tot=('ret', 'sum')).sort_values('tot', ascending=False)
    nm = json.load(open(os.path.join(BASE, 'data', 'fixed_pool.json'),
                        encoding='utf-8')).get('name', {})
    print('  %-8s %-16s %3s %10s %10s' % ('代码', '名称', '次', '平均', '合计'))
    for c, x in pd.concat([cc.head(10), cc.tail(5)]).iterrows():
        print('  %-8s %-16s %3d %+9.2f%% %+9.1f%%'
              % (c, str(nm.get(c, ''))[:16], int(x['n']), x['avg'] * 100, x['tot'] * 100))


if __name__ == '__main__':
    main()
