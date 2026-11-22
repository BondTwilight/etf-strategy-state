# -*- coding: utf-8 -*-
"""校验生成的聚宽脚本：池子解析、代码映射、指标函数与本地一致"""
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
JQ = os.path.join(os.path.dirname(BASE), 'deliverables', 'jq_etf_dip_v42.py')

spec = importlib.util.spec_from_file_location('jq_mod', JQ)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print('[OK] 模块可导入（未调用聚宽 API）')

# ---------- 1. 池子 ----------
pool = mod._parse_pool(mod._POOL_RAW)
raw = json.load(open('data/fixed_pool.json', encoding='utf-8'))
orig = {c: int(raw['bmap'].get(c, -16)) for c in raw['codes']}

print('\n[1] 池子解析：生成 %d 只 / 原始 %d 只' % (len(pool), len(orig)))
miss = [c for c in orig if c not in pool]
extra = [c for c in pool if c not in orig]
bad = [(c, pool[c], orig[c]) for c in orig if c in pool and pool[c] != orig[c]]
print('    缺失 %d 只 ｜ 多余 %d 只 ｜ 阈值不符 %d 只' % (len(miss), len(extra), len(bad)))
if bad[:5]:
    print('    不符样例：', bad[:5])

from collections import Counter
print('    阈值分布：', dict(sorted(Counter(pool.values()).items())),
      '（原始', dict(sorted(Counter(orig.values()).items())), '）')

# ---------- 2. 代码映射 ----------
print('\n[2] 代码映射抽查')
for c in ['159831', '510170', '588020', '562800']:
    print('    %s -> %s' % (c, mod.to_jq(c)))
mapped = [mod.to_jq(c) for c in pool]
print('    沪市 %d ｜ 深市 %d ｜ 异常 %d' % (
    sum(1 for x in mapped if x.endswith('.XSHG')),
    sum(1 for x in mapped if x.endswith('.XSHE')),
    sum(1 for x in mapped if not x.endswith(('.XSHG', '.XSHE')))))

# ---------- 3. 指标函数 vs 本地 ----------
print('\n[3] _bias_bundle 与本地 calculate_bias 同源比对')
big = pd.read_parquet('data/etf_qfq_cifang.parquet')
sample = ['159967', '588020', '513310', '515080', '159831']
rows = []
for code in sample:
    g = big[big['code'] == code].sort_values('date')
    closes = g['close'].astype(float).to_numpy()
    if len(closes) < 60:
        continue
    seg = closes[-52:]
    b20, b50, bmin5 = mod._bias_bundle(seg)

    # 本地口径：完全相同的公式，独立实现一遍
    last = seg[-1]
    l20 = (last / seg[-20:].mean() - 1) * 100
    l50 = (last / seg[-50:].mean() - 1) * 100
    mins = []
    for k in range(5):
        idx = len(seg) - 5 + k
        sub = seg[:idx + 1]
        mins.append((sub[-1] / sub[-20:].mean() - 1) * 100)
    rows.append((code, b20 - l20, b50 - l50, bmin5 - min(mins)))

print('    %-8s %12s %12s %12s' % ('代码', 'Δbias20', 'Δbias50', 'Δbmin5'))
ok = True
for code, d1, d2, d3 in rows:
    flag = '' if max(abs(d1), abs(d2), abs(d3)) < 1e-9 else '  ← 不一致'
    ok = ok and not flag
    print('    %-8s %12.2e %12.2e %12.2e%s' % (code, d1, d2, d3, flag))
print('    %s' % ('✅ 全部一致' if ok else '❌ 存在不一致'))

# ---------- 4. 关键参数核对 ----------
print('\n[4] 参数核对')
for k in ['MAX_HOLD', 'STOP_LOSS_PCT', 'SELL_PROFIT_PCT', 'SELL_BIAS_TH',
          'HOLD_MAX_DAYS', 'BIAS_BUY_DAYS', 'BIAS_SORT_DAYS', 'OVERSOLD_LOOKBACK',
          'TRAIL_STOP_PCT', 'BREAKEVEN_STOP_PCT']:
    print('    %-22s = %s' % (k, getattr(mod, k)))
print('    %-22s = %s' % ('ENABLE_TRAIL', mod.ENABLE_TRAIL))
print('    %-22s = %s' % ('ENABLE_BREAKEVEN', mod.ENABLE_BREAKEVEN))
print('    %-22s = %s' % ('ENABLE_TJ', mod.ENABLE_TJ))
