# -*- coding: utf-8 -*-
"""从现行聚宽版派生出「商品剔除版」：只把 5 只商品 ETF 的阈值 -11 改成 -18。

-18 已被验证与「直接从池子移除」逐位同值（39.37% / -13.20% / Calmar 2.98 / 43 笔），
保留代码在池子里是为了让两版池子数量一致、便于对账。
"""
import hashlib
import os
import re

SRC = '../deliverables/jq_etf_dip_current_20261102.py'
DST = '../deliverables/jq_etf_dip_v45_商品剔除_20261102.py'
GOODS = ['159831', '159981', '159985', '510170', '518600']
NEW_TH = -18

s = open(SRC, encoding='utf-8').read()
orig = s

# 1) 改阈值
for c in GOODS:
    pat = re.compile(re.escape(c) + r':-11')
    s, n = pat.subn('%s:%d' % (c, NEW_TH), s)
    print('%-8s 替换 %d 处' % (c, n))

# 2) 改头部标识
s = s.replace(
    '# 固定池 381 只（code:阈值）｜ -16=A股/港股/中概(339) -11=跨境/商品(32) -5=红利(10)',
    '# 固定池 381 只（code:阈值）｜ -16=A股/港股/中概(339) -11=跨境(27) -5=红利(10)\n'
    '# ★ v4.5 改动：5 只商品 ETF 阈值 -11 → -18（等价剔除）。原 -11 档 32 只变 27 只。\n'
    '#   依据：商品组前瞻 10 日 +1.30%（胜率 53.7%，五组最差）、4 笔历史交易全拖累。\n'
    '#   预期：39.37% / -13.20% / Calmar 2.98 / 43 笔（对照现行 38.73% / -18.87% / 2.05 / 40 笔）')

# 3) 在文件最上方插入用途说明
head = '''# -*- coding: utf-8 -*-
# ==================================================================
# v4.5 = 现行线上口径 + 「商品 ETF 剔除」
#
# 与 jq_etf_dip_current_20261102.py 的唯一差别：
#   159831 / 159981 / 159985 / 510170 / 518600 五只的阈值 -11 → -18
#   （-18 已被验证与「从池子移除」逐位同值）
#
# 本地回测（2021-01-04 ~ 2026-10-20，分钟近似 14:45，滑点 0.2%）：
#   现行版  38.73% / -18.87% / Calmar 2.05 / 40 笔
#   本版    39.37% / -13.20% / Calmar 2.98 / 43 笔
#   ⇒ 年化 +0.64pp（噪声内）、回撤改善 5.67pp、Calmar +45%
#
# ⚠️ walk-forward：检验段（2024-2026）增量为 0.00pp，因为 4 笔商品交易
#    全部发生在 2021-2023。这是「先验充分 + 全段同向 + 检验段中性」的改动，
#    不是显著改进。聚宽跑出来的差异若在 ±3~5pp 内属正常。
# ==================================================================
'''
if s.startswith('# -*- coding: utf-8 -*-'):
    s = s.replace('# -*- coding: utf-8 -*-', head, 1)

open(DST, 'w', encoding='utf-8').write(s)

# 4) 校验
print()
print('原文件 %d 字节 / 新文件 %d 字节' % (len(orig.encode('utf-8')), len(s.encode('utf-8'))))
for c in GOODS:
    m = re.search(c + r':(-?\d+)', s)
    print('  %s -> %s' % (c, m.group(1) if m else '缺失'))
# 池子条目数
th = re.findall(r'\d{6}:-?\d+', s)
print('池子条目数 %d（应为 381）' % len(th))
from collections import Counter
print('阈值分布', dict(Counter(x.split(':')[1] for x in th)))
print('EXEC_TIME:', re.search(r'EXEC_TIME\s*=\s*[\'\"]([^\'\"]+)', s).group(1))
print('MAX_HOLD :', re.search(r'^MAX_HOLD\s*=\s*(\d+)', s, re.M).group(1))
