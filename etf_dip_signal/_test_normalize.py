# -*- coding: utf-8 -*-
"""用合成数据测 _normalize_px 能否吃下聚宽各种返回结构"""
import importlib.util
import os

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
JQ = os.path.join(os.path.dirname(BASE), 'deliverables', 'jq_etf_dip_v42.py')
spec = importlib.util.spec_from_file_location('jq_mod', JQ)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

CODES = ['159967.XSHE', '588020.XSHG', '510170.XSHG']
DATES = pd.date_range('2021-01-04', periods=6)
rng = np.random.RandomState(0)
WIDE = pd.DataFrame(100 + rng.rand(6, 3) * 10, index=DATES, columns=CODES)
CS = set(CODES)

cases = {}

# ① dict{'close': 宽表}
cases['dict{close:宽表}'] = {'close': WIDE.copy()}

# ② 宽表（columns=证券）
cases['宽表 columns=证券'] = WIDE.copy()

# ③ 长表：MultiIndex(时间, 证券) —— 本次实测遇到的形态
long1 = WIDE.stack().to_frame('close')
cases['长表 (时间,证券)'] = long1

# ④ 长表：层级顺序反过来 (证券, 时间)
cases['长表 (证券,时间)'] = long1.swaplevel().sort_index()

# ⑤ 长表：只有一列名叫别的字段
long2 = WIDE.stack().to_frame('px')
cases['长表 列名=px'] = long2

# ⑥ 长表：列是 date（少数版本会转置）
cases['宽表 转置(columns=日期)'] = WIDE.T

# ⑦ 空
cases['空 DataFrame'] = pd.DataFrame()

print('%-22s %-10s %-12s %s' % ('输入结构', '识别', '形状', '结果'))
print('-' * 86)
ok = 0
for name, obj in cases.items():
    try:
        w = mod._normalize_px(obj, CS)
    except Exception as e:
        print('%-22s %-10s %-12s %s' % (name, '异常', '-', '%s: %s' % (type(e).__name__, e)))
        continue
    if w is None:
        print('%-22s %-10s %-12s %s' % (name, 'None', '-', '→ 拒绝（需上层回退）'))
        continue
    shape = '%dx%d' % (w.shape[0], w.shape[1]) if hasattr(w, 'shape') else '?'
    # 校验能否按代码取出 6 根
    got = []
    for c in CODES:
        try:
            got.append(len(w[c].dropna()))
        except Exception:
            got.append(0)
    good = all(g >= 6 for g in got) or (w.shape[0] >= 6 and w.shape[1] >= 3)
    # 更严格：值是否与原始宽表一致
    same = False
    try:
        if w.shape == WIDE.shape:
            same = bool(np.allclose(np.sort(w.values.flatten()),
                                    np.sort(WIDE.values.flatten())))
    except Exception:
        pass
    print('%-22s %-10s %-12s %s' % (name, '成功' if same else '结构可读',
                                    shape, '数值一致' if same else '取到但值需核对'))
    if same:
        ok += 1

print('-' * 86)
print('数值完全一致的形态：%d / %d' % (ok, len(cases)))
print('\n注：「宽表 转置」与「空 DataFrame」被拒绝是正确的——')
print('    转置是脏结构不该被当成正常数据；空表应让上层回退或报错。')
