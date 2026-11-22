# -*- coding: utf-8 -*-
"""买入当天分批建仓可行性：14:45 之后还有多少下跌空间？

关键问题：
  · 策略 14:45 决策，当天低点通常在什么时段？
  · 14:45 之后（14:46~15:00）还能不能买到更低的价？
  · 「先买一半、跌了再补」到底能省多少？

先探测分钟线可回溯范围。
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


def fetch_min(code, day):
    q = urllib.parse.urlencode({'symbol': code,
                                'start_time': '%s 09:30:00' % day,
                                'end_time': '%s 15:00:00' % day})
    req = urllib.request.Request(cf.BASE + '/fund/hist_min?' + q,
                                 headers={'x-api-key': cf.API_KEY})
    try:
        b = json.loads(urllib.request.urlopen(req, timeout=25).read().decode('utf-8'))
        rows = (b.get('data') or {}).get(code) or []
        return rows
    except Exception as e:
        return []


def main():
    print('=' * 96)
    print('【探测】分钟线可回溯多久')
    print('=' * 96)
    for d in ('2022-03-21', '2023-05-25', '2024-02-02', '2025-01-06',
              '2026-03-23', '2026-10-23'):
        rows = fetch_min('510300', d)
        print('  %s → %d 根' % (d, len(rows)))
        if rows and len(rows) > 100:
            print('     首根 %s 收 %.4f ｜ 末根 %s 收 %.4f'
                  % (str(rows[0][0])[-8:], float(rows[0][3]),
                     str(rows[-1][0])[-8:], float(rows[-1][3])))


if __name__ == '__main__':
    main()
