# -*- coding: utf-8 -*-
"""用真实行情校验聚宽版 signals_at 与本地公式是否逐位一致"""
import importlib.util
import json
import os
import sys
import types

import numpy as np
import pandas as pd

# 本地没有 jqdata 模块，打个桩再导入（聚宽环境下是真实存在的）
sys.modules.setdefault('jqdata', types.ModuleType('jqdata'))

BASE = os.path.dirname(os.path.abspath(__file__))
JQ = os.path.join(os.path.dirname(BASE), 'deliverables', 'jq_etf_dip_v44.py')
spec = importlib.util.spec_from_file_location('jq44', JQ)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print('[OK] v4.4 模块可导入')

raw = json.load(open('data/fixed_pool.json', encoding='utf-8'))
pool = mod._parse_pool(mod._POOL_RAW)
print('[池子] 解析 %d 只 ｜ 原始 %d 只 ｜ 阈值全等 %s'
      % (len(pool), len(raw['codes']),
         all(pool[c] == int(raw['bmap'].get(c, -16)) for c in raw['codes'])))

# 取一批真实行情
big = pd.read_parquet('data/etf_qfq_cifang.parquet')
big = big[big['code'].isin(raw['codes'])]
last_date = big['date'].max()
sub = big[big['date'] <= last_date]

SAMPLE = ['159967', '588020', '513310', '515080', '159831',
          '510300', '512100', '159915']
SAMPLE = [c for c in SAMPLE if c in set(big['code'])]
print('[样本]', SAMPLE)

# 构造 C（前 60 根，截至 T-1）与 P（T 日价）—— 模拟"上一交易日 + 今日实时价"
rows = {}
for c in SAMPLE:
    s = sub[sub['code'] == c].sort_values('date')['close'].astype(float).values
    if len(s) < 61:
        continue
    rows[c] = s[-61:]
codes = list(rows.keys())
C = np.column_stack([rows[c][:60] for c in codes])     # 60 根历史
P = np.array([rows[c][60] for c in codes], dtype=float)  # 今日价

b20, b50, bmin5 = mod.signals_at(C, P)

print('\n%-8s %12s %12s %12s' % ('代码', 'bias20', 'bias50', 'bmin5'))
for k, c in enumerate(codes):
    print('%-8s %11.4f %12.4f %12.4f' % (c, b20[k], b50[k], bmin5[k]))

# 参考实现：逐只按本地 indicators.calculate_bias 的公式重算
print('\n逐位比对（本地公式独立实现）：')
allok = True
for k, c in enumerate(codes):
    closes = np.concatenate([C[:, k], [P[k]]])
    ref_b20 = (closes[-1] / closes[-20:].mean() - 1) * 100
    ref_b50 = (closes[-1] / closes[-50:].mean() - 1) * 100
    mins = []
    for j in range(5):
        seg = closes[:len(closes) - 5 + j + 1]
        mins.append((seg[-1] / seg[-20:].mean() - 1) * 100)
    ref_min5 = min(mins)
    d1, d2, d3 = b20[k] - ref_b20, b50[k] - ref_b50, bmin5[k] - ref_min5
    ok = max(abs(d1), abs(d2), abs(d3)) < 1e-9
    allok = allok and ok
    print('  %-8s Δb20 %+.2e  Δb50 %+.2e  Δbmin5 %+.2e  %s'
          % (c, d1, d2, d3, 'OK' if ok else '❌'))

print('\n结论：%s' % ('✅ 与本地公式完全一致' if allok else '❌ 存在偏差'))

# 边界：P 含 nan 时的行为
P2 = P.copy()
P2[0] = np.nan
bb20, bb50, bbmin5 = mod.signals_at(C, P2)
print('边界：单只无价 → b20[0]=%s（应为 nan）｜ b20[1]=%.4f（应正常）'
      % (bb20[0], bb20[1]))
