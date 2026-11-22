# -*- coding: utf-8 -*-
"""冻结池的存活偏差量化：各时点池内实际有多少只在世。"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

NEW = os.path.join(BASE, 'data', 'etf_qfq_cifang_1104.parquet')


def main():
    d = pd.read_parquet(NEW, columns=['code', 'date', 'close'])
    d['date'] = d['date'].astype(str).str[:10]
    d = d[d['close'] > 0]

    first = d.groupby('code')['date'].min()
    print('=' * 88)
    print('【冻结池的存活偏差】池子 381 只（2026-10-14 冻结），各时点实际在世数')
    print('=' * 88)
    print('  %-12s %8s %8s %10s' % ('时点', '在世数', '占全池', '说明'))
    for t, note in (('2015-01-05', '池子起点'), ('2018-01-01', ''),
                    ('2021-01-04', '主回测起点'), ('2022-01-01', '本次起点'),
                    ('2024-01-01', ''), ('2026-11-04', '现在')):
        n = int((first <= t).sum())
        print('  %-12s %8d %7.1f%% %10s'
              % (t, n, n / len(first) * 100, note))

    print()
    print('  按年份看新增上市（首次出现）数：')
    yr = pd.to_datetime(first).dt.year.value_counts().sort_index()
    cum = 0
    for y in range(2015, 2027):
        k = int(yr.get(y, 0))
        cum += k
        if y >= 2021 or k:
            print('    %d 年：新增 %3d 只 ｜ 累计 %3d 只（%.0f%%）'
                  % (y, k, cum, cum / len(first) * 100))

    print()
    print('=' * 88)
    print('【含义】')
    print('=' * 88)
    n22 = int((first <= '2022-01-01').sum())
    print('  2022 起点时池内只有 %d 只（%.0f%%），其余 %d 只是 2022 年之后才上市的。'
          % (n22, n22 / len(first) * 100, len(first) - n22))
    print('  ⇒ 回测里 2022 年初的"候选池"实际可选标的远少于 381 只，')
    print('     但回测程序按"今天存在的 381 只"去取历史数据，')
    print('     未上市的自然没数据、不会进入候选 —— 这一点是【良性】的，')
    print('     真正的偏差在于：**已退市/清盘的 ETF 不在池子里**，')
    print('     它们当年的暴跌-不反弹样本被系统性排除了。')

    # 极端低价/低流动性标的占比
    last = d[d['date'] == d['date'].max()]
    print()
    print('  当前池内最新收盘价分布：')
    print('    <0.3 元：%d 只 ｜ 0.3~0.5：%d 只 ｜ 0.5~1：%d 只 ｜ >1：%d 只'
          % ((last['close'] < 0.3).sum(),
             ((last['close'] >= 0.3) & (last['close'] < 0.5)).sum(),
             ((last['close'] >= 0.5) & (last['close'] < 1)).sum(),
             (last['close'] >= 1).sum()))
    print('  ⇒ 池内最低价 %.3f 元；低价 ETF 的 1 个报价单位相对成本更高'
          % last['close'].min())


if __name__ == '__main__':
    main()
