# -*- coding: utf-8 -*-
"""买入当天分批建仓的可行性（31 笔逐笔）。

回答：
  ① 当天最低点出现在什么时段？14:45 决策时是否已经错过？
  ② 14:45 之后（14:46~15:00）还能买到更低吗？能低多少？
  ③ 「先买一半、跌了再补」相对一次性买入，平均成本能省多少？
"""
import json
import os
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import cifang_api as cf

CSV = os.path.join(BASE, '回测输出', 'trades_full_2022_2026.csv')


def fetch_min(code, day):
    q = urllib.parse.urlencode({'symbol': code,
                                'start_time': '%s 09:30:00' % day,
                                'end_time': '%s 15:00:00' % day})
    req = urllib.request.Request(cf.BASE + '/fund/hist_min?' + q,
                                 headers={'x-api-key': cf.API_KEY})
    try:
        b = json.loads(urllib.request.urlopen(req, timeout=30).read().decode('utf-8'))
        return (b.get('data') or {}).get(code) or []
    except Exception:
        return []


def main():
    df = pd.read_csv(CSV, dtype={'code': str})
    df['code'] = df['code'].str.zfill(6)
    buys = df.copy()

    print('=' * 118)
    print('【逐笔】买入日的日内路径（价格均为该标的当日分钟收盘）')
    print('=' * 118)
    print('%-10s %-8s %8s %8s %8s %-7s %9s %9s %9s'
          % ('买入日', '标的', '14:45', '全天低', '低点时', '14:45后低', '距全天低', '14:45后空间', '收盘'))

    rows = []
    for _, x in buys.iterrows():
        rows_raw = fetch_min(x['code'], x['entry'])
        if len(rows_raw) < 200:
            print('%-10s %-8s  （分钟线不足 %d 根，跳过）' % (x['entry'], x['code'], len(rows_raw)))
            continue
        m = pd.DataFrame([{'t': str(r[0])[-8:], 'close': float(r[3]),
                           'low': float(r[4]), 'high': float(r[5])}
                          for r in rows_raw])
        p1445_row = m[m['t'] == '14:45:00']
        if not len(p1445_row):
            # 取最接近 14:45 的一根
            p1445_row = m[m['t'] <= '14:45:00'].tail(1)
        p0 = float(p1445_row['close'].iloc[0])

        low_all = float(m['low'].min())
        t_low = m.loc[m['low'].idxmin(), 't']
        after = m[m['t'] > '14:45:00']
        low_after = float(after['low'].min()) if len(after) else p0
        p_close = float(m['close'].iloc[-1])

        prem_all = (p0 / low_all - 1) * 100      # 14:45 比全天最低贵多少
        room = (p0 / low_after - 1) * 100        # 14:45 之后还能跌多少
        print('%-10s %-8s %8.4f %8.4f %-7s %9.4f %+8.2f%% %+9.2f%% %9.4f'
              % (x['entry'], x['code'], p0, low_all, t_low, low_after,
                 prem_all, room, p_close))
        rows.append({'entry': x['entry'], 'code': x['code'], 'p0': p0,
                     'low_all': low_all, 't_low': t_low, 'low_after': low_after,
                     'p_close': p_close, 'prem_all': prem_all, 'room': room})

    d = pd.DataFrame(rows)
    if not len(d):
        print('无有效样本')
        return

    print()
    print('=' * 100)
    print('【一】14:45 相对当天最低价：平均买贵了多少')
    print('=' * 100)
    print('  距全天最低：均值 %+.2f%% ｜ 中位 %+.2f%% ｜ 最小 %+.2f%% ｜ 最大 %+.2f%%'
          % (d['prem_all'].mean(), d['prem_all'].median(),
             d['prem_all'].min(), d['prem_all'].max()))
    print('  ⇒ 这是"策略无法吃到"的部分（低点已过去），不是分批建仓能解决的')

    print()
    print('  当天最低点出现的时段分布：')
    def bucket(t):
        hh = int(t[:2])
        if hh < 10:
            return '09:30-10:00'
        if hh < 11:
            return '10:00-11:00'
        if hh < 14:
            return '11:00-14:00'
        return '14:00-15:00'
    d['tb'] = d['t_low'].map(bucket)
    for k, g in d.groupby('tb'):
        print('    %-12s %2d 笔（%.0f%%）' % (k, len(g), len(g) / len(d) * 100))

    print()
    print('=' * 100)
    print('【二】14:45 之后（14:46~15:00）还有多少空间')
    print('=' * 100)
    print('  14:45 后最低价相对 14:45 价：均值 %+.2f%% ｜ 中位 %+.2f%%'
          % (d['room'].mean(), d['room'].median()))
    print('  仍有下跌（room>0）：%d/%d 笔（%.0f%%）'
          % ((d['room'] > 0).sum(), len(d),
             (d['room'] > 0).mean() * 100))
    for th in (0.3, 0.5, 1.0):
        print('  跌幅 >%.1f%% 的：%d 笔（%.0f%%）'
              % (th, (d['room'] > th).sum(), (d['room'] > th).mean() * 100))
    print()
    print('  14:45 到收盘的漂移：均值 %+.2f%%（收盘/14:45-1）'
          % ((d['p_close'] / d['p0'] - 1).mean() * 100))

    print()
    print('=' * 100)
    print('【三】三种建仓方式的实际平均成本对比')
    print('=' * 100)
    # A: 14:45 一次性
    cost_a = d['p0'].copy()
    # B: 14:45 买 50%，之后跌破 0.5% 用 0.5% 价位补剩余，否则收盘补
    cost_b = []
    # C: 14:45 买 1/3，之后跌破 0.5% 补 1/3、跌破 1.0% 再补 1/3，未触发则收盘补
    cost_c = []
    for _, x in d.iterrows():
        p0 = x['p0']
        la = x['low_after']
        pc = x['p_close']
        # B
        if la <= p0 * 0.995:
            cost_b.append(0.5 * p0 + 0.5 * p0 * 0.995)
        else:
            cost_b.append(0.5 * p0 + 0.5 * pc)
        # C
        fills = [(1 / 3, p0)]
        left = 2 / 3
        if la <= p0 * 0.995:
            fills.append((1 / 3, p0 * 0.995))
            left -= 1 / 3
            if la <= p0 * 0.99:
                fills.append((left, p0 * 0.99))
                left = 0
        if left > 1e-9:
            fills.append((left, pc))
        cost_c.append(sum(w * p for w, p in fills))
    d['costB'] = cost_b
    d['costC'] = cost_c

    print('  %-28s %10s %12s' % ('方式', '平均成本(相对)', '相对A的改善'))
    d['costA'] = cost_a
    print('  %-28s %9.4f%% %11s'
          % ('A 14:45 一次性买入', 100.0, '—'))
    for k, nm in (('costB', 'B 14:45买半 + 跌0.5%补/收盘补'),
                  ('costC', 'C 14:45买1/3 + 跌0.5%/1%补')):
        rel = (d[k] / d['costA'] - 1) * 100
        print('  %-28s %9.4f%% %+10.3f%%'
              % (nm, 100 + rel.mean(), rel.mean()))
    print()
    print('  ⇒ 改善幅度 = 平均建仓成本的百分比变化，负值代表更便宜。')
    print('  ⇒ 换算年化：按年换手 6.4 次，改善 0.1%% 约等于年化 +0.64pp（近似）')

    d.to_csv(os.path.join(BASE, '回测输出', 'entry_timing.csv'),
             index=False, encoding='utf-8-sig')
    print()
    print('已写出 回测输出/entry_timing.csv')


if __name__ == '__main__':
    main()
