# -*- coding: utf-8 -*-
"""11-03 → 11-04 的反弹全貌 + 冷却期代价。

三问：
  ① 11-03 是恐慌底吗？（候选池当日跌幅 vs 全池）
  ② 11-04 全面反弹了多少？（候选池涨幅排名）
  ③ 若 11-04 无冷却、按 14:45 买入榜首，到今天收盘赚多少？
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import cifang_api as cf

CANDS = ['515880', '159967', '588020', '560780', '159327', '159516', '159259',
         '159243', '561980', '159597', '159582', '512220', '588300', '588360',
         '588170', '588320', '563210', '588200', '588010', '588100', '588450',
         '159100']
BENCH = ['510300', '159915', '588000']


def main():
    codes = CANDS + BENCH
    hist = cf.fetch_pool_history(codes, '2026-10-26', '2026-11-04', force=True)
    print('拉到 %d/%d 只' % (len(hist), len(codes)))
    print()

    rows = []
    for c in codes:
        if c not in hist:
            continue
        g = hist[c].sort_values('date')
        dates = list(g['date'].astype(str))
        cl = g['close'].to_numpy(float)
        if '2026-11-04' not in dates:
            continue
        i4 = dates.index('2026-11-04')
        # 前一日（11-03）
        p3 = cl[i4 - 1] if i4 >= 1 else np.nan
        # 近 5 日累计（10-28 ~ 11-03）
        i5 = max(i4 - 5, 0)
        r5 = (cl[i4 - 1] / cl[i5] - 1) * 100 if i4 >= 2 else np.nan
        rows.append({
            'code': c,
            'close_1103': p3,
            'close_1104': cl[i4],
            'chg_1103': (p3 / cl[i4 - 2] - 1) * 100 if i4 >= 2 else np.nan,
            'chg_1104': (cl[i4] / p3 - 1) * 100,
            'pre5d': r5,
        })
    df = pd.DataFrame(rows)
    df['is_cand'] = df['code'].isin(CANDS)

    print('=' * 88)
    print('【一】候选池 vs 基准：11-03 跌多少 / 11-04 涨多少')
    print('=' * 88)
    print('%-8s %10s %10s %10s %10s %10s'
          % ('code', '11-03收', '11-04收', '11-03涨跌', '11-04涨跌', '前5日累计'))
    for _, r in df.sort_values('chg_1104', ascending=False).iterrows():
        tag = '' if r['is_cand'] else '  ←基准'
        print('%-8s %10.4f %10.4f %+9.2f%% %+9.2f%% %+9.2f%%%s'
              % (r['code'], r['close_1103'], r['close_1104'],
                 r['chg_1103'], r['chg_1104'], r['pre5d'], tag))

    cand = df[df['is_cand']]
    bench = df[~df['is_cand']]
    print('-' * 88)
    print('  候选池 %d 只：11-03 均值 %+.2f%% ｜ 11-04 均值 %+.2f%%（中位 %+.2f%%）｜ 前5日 %+.2f%%'
          % (len(cand), cand['chg_1103'].mean(), cand['chg_1104'].mean(),
             cand['chg_1104'].median(), cand['pre5d'].mean()))
    print('  基准 %d 只：  11-03 均值 %+.2f%% ｜ 11-04 均值 %+.2f%%'
          % (len(bench), bench['chg_1103'].mean(), bench['chg_1104'].mean()))
    print('  ⇒ 候选池 11-04 跑赢基准 %.2fpp'
          % (cand['chg_1104'].mean() - bench['chg_1104'].mean()))

    # 若 11-04 14:45 买入榜首
    print()
    print('=' * 88)
    print('【二】若 11-04 无冷却、14:45 买入榜首 515880')
    print('=' * 88)
    import json
    import urllib.parse
    import urllib.request
    try:
        q = urllib.parse.urlencode({'symbol': '515880',
                                    'start_time': '2026-11-04 14:40:00',
                                    'end_time': '2026-11-04 15:00:00'})
        req = urllib.request.Request(cf.BASE + '/fund/hist_min?' + q,
                                     headers={'x-api-key': cf.API_KEY})
        b = json.loads(urllib.request.urlopen(req, timeout=25).read().decode('utf-8'))
        rows = (b.get('data') or {}).get('515880') or []
        print('   分钟线 %d 根：' % len(rows))
        for r in rows:
            print('   %s  开 %.4f 收 %.4f' % (str(r[0])[-8:], float(r[2]), float(r[3])))
        p1445 = None
        for r in rows:
            if '14:45' in str(r[0]):
                p1445 = float(r[3])
        if p1445:
            g = hist['515880'].sort_values('date')
            c4 = float(g['close'].iloc[-1])
            print('   ⇒ 14:45 买 %.4f → 收盘 %.4f：%+.2f%%'
                  % (p1445, c4, (c4 / p1445 - 1) * 100))
    except Exception as e:
        print('   分钟线取失败：%s' % str(e)[:120])


if __name__ == '__main__':
    main()
