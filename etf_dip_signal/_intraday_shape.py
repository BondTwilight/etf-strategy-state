# -*- coding: utf-8 -*-
"""11-04 反弹的时间分布：跳空还是尾盘？

决定性问题：
  - 如果反弹集中在开盘 30 分钟（跳空），那"错过"的根因是「只在 14:45 决策」，
    不是冷却期；任何盘中买入都吃不到。
  - 如果反弹在尾盘延续，那"14:45 买入"能吃到一部分，冷却期才是主因。
"""
import json
import os
import sys
import urllib.parse
import urllib.request

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import cifang_api as cf

CODES = ['588170', '515880', '159967', '588020', '510300']
PREV_CLOSE = {'588170': 0.5790, '515880': 0.4030, '159967': 0.4710,
              '588020': 0.5250, '510300': 4.0920}
SELL_PX = {'588170': 0.583, '159967': 0.524}     # 聚宽昨日卖出价


def fetch_min(code, s, e):
    q = urllib.parse.urlencode({'symbol': code, 'start_time': s, 'end_time': e})
    req = urllib.request.Request(cf.BASE + '/fund/hist_min?' + q,
                                 headers={'x-api-key': cf.API_KEY})
    b = json.loads(urllib.request.urlopen(req, timeout=25).read().decode('utf-8'))
    rows = (b.get('data') or {}).get(code) or []
    out = []
    for r in rows:
        out.append({'time': str(r[0])[-8:], 'open': float(r[2]),
                    'close': float(r[3])})
    return out


def main():
    print('=' * 90)
    print('【11-04 反弹的时间分布】')
    print('=' * 90)
    for c in CODES:
        try:
            rows = fetch_min(c, '2026-11-04 09:30:00', '2026-11-04 15:00:00')
        except Exception as e:
            print('%s 取失败：%s' % (c, str(e)[:80]))
            continue
        if not rows:
            continue
        pc = PREV_CLOSE[c]
        op = rows[0]['open']
        print()
        print('  %s（昨收 %.4f，分钟线 %d 根，首根 %s 末根 %s）'
              % (c, pc, len(rows), rows[0]['time'], rows[-1]['time']))

        def at(hhmm):
            for r in rows:
                if r['time'] == hhmm:
                    return r['close']
            # 容错：找最接近且不晚于 hhmm 的一根
            cand = [r for r in rows if r['time'] <= hhmm]
            return cand[-1]['close'] if cand else None

        p0935, p1000, p1130, p1445, p1457 = (at('09:35'), at('10:00'),
                                             at('11:30'), at('14:45'), at('14:57'))
        close = rows[-1]['close']
        print('    开盘 %.4f  %+6.2f%%' % (op, (op / pc - 1) * 100))
        for nm, v in (('09:35', p0935), ('10:00', p1000), ('11:30', p1130),
                      ('14:45', p1445), ('14:57', p1457), ('收盘', close)):
            if v:
                print('    %-6s %.4f  %+6.2f%%（相对昨收）' % (nm, v, (v / pc - 1) * 100))
        if p1445:
            print('    ⇒ 若 14:45 买入到收盘：%+.2f%%' % ((close / p1445 - 1) * 100))
            gap_move = (op / pc - 1) * 100
            full = (p1445 / pc - 1) * 100
            print('    ⇒ 全日到14:45涨幅 %.2f%% 中，跳空 %.2f%%、盘中 %.2f%%'
                  % (full, gap_move, (p1445 / op - 1) * 100))
        if c in SELL_PX:
            base_px = SELL_PX[c]
            if p1445:
                print('    ⇒ 若昨日未卖、今日 14:45 卖：%+.2f%%（vs 昨日卖价 %.4f）'
                      % ((p1445 / base_px - 1) * 100, base_px))
            print('    ⇒ 若昨日未卖、今日开盘卖：  %+.2f%%'
                  % ((op / base_px - 1) * 100))
            print('    ⇒ 若昨日未卖、今日收盘卖：  %+.2f%%'
                  % ((close / base_px - 1) * 100))


if __name__ == '__main__':
    main()
