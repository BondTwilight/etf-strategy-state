# -*- coding: utf-8 -*-
"""次方数据源接入验证：
  A. 覆盖与耗时（API 调用次数、只数）
  B. 次方实盘链路 vs 回测缓存（同源，应完全一致）
  C. 次方前复权 vs 新浪不复权（量化"不复权失真"，证明为何必须切）
"""
import json
import time
import os
import sys

import numpy as np
import pandas as pd

import config as cfg
import cifang_quote
import web_quote
import indicators as ind

POOL = json.load(open('data/fixed_pool.json', encoding='utf-8'))
CODES = POOL['codes']
BMAP = POOL.get('bmap', {})
print('池子 %d 只，DATA_SOURCE=%s' % (len(CODES), cfg.DATA_SOURCE))

# ---------- A. 覆盖与耗时 ----------
t0 = time.time()
cifang_quote.clear_cache()
kmap_cf = cifang_quote.prefetch_batch(CODES, count=62, force=True)
elapsed = time.time() - t0
st = cifang_quote.stats()
print('\n[A] 次方预取：%d/%d 只，API 请求 %d 次，耗时 %.1fs'
      % (len(kmap_cf), len(CODES), st['calls'], elapsed))
miss = [c for c in CODES if c not in kmap_cf]
print('    缺失 %d 只%s' % (len(miss), ('：' + str(miss[:10])) if miss else ''))

# ---------- B. vs 回测缓存（同源一致性）----------
cache_p = os.path.join('data', 'etf_qfq_cifang.parquet')
if os.path.exists(cache_p):
    big = pd.read_parquet(cache_p)
    cache_map = {c: g.sort_values('date').reset_index(drop=True)
                 for c, g in big.groupby('code')}
    diffs = []
    for code in CODES:
        if code not in kmap_cf or code not in cache_map:
            continue
        a = kmap_cf[code].set_index('date')['close']
        b = cache_map[code].set_index('date')['close']
        common = a.index.intersection(b.index)
        if len(common) < 20:
            continue
        d = (a.loc[common] - b.loc[common]).abs().max()
        diffs.append((code, float(d), len(common)))
    arr = np.array([x[1] for x in diffs])
    bad = [x for x in diffs if x[1] > 0.005]
    print('\n[B] 次方实盘 vs 回测缓存（%d 只可比）：最大绝对价差 = %.6f，'
          '超 0.005 元的标的 %d 只' % (len(diffs), arr.max() if len(arr) else -1, len(bad)))
    if bad:
        print('    前 10：', [(c, round(d, 4)) for c, d, _ in bad[:10]])
    else:
        print('    ✅ 完全一致（同一数据源，链路正确）')
else:
    print('\n[B] 跳过：回测缓存不存在')

# ---------- C. vs 新浪不复权（量化失真）----------
print('\n[C] 正在用新浪不复权做对照（慢，逐只）...')
ok = cmp = 0
worst = []
for code in CODES[:120]:          # 抽样 120 只，控制耗时
    if code not in kmap_cf:
        continue
    try:
        sdf = web_quote._kline_sina(code, 62) if hasattr(web_quote, '_kline_sina') else None
    except Exception:
        sdf = None
    if sdf is None or getattr(sdf, 'empty', True):
        continue
    a = kmap_cf[code].set_index('date')['close']
    b = sdf.copy()
    b['date'] = b['date'].astype(str).str[:10]
    b = b.set_index('date')['close']
    common = a.index.intersection(b.index)
    if len(common) < 20:
        continue
    cmp += 1
    ra = a.loc[common] / a.loc[common].iloc[-1]
    rb = b.loc[common] / b.loc[common].iloc[-1]
    delta = float((ra - rb).abs().max() * 100)
    worst.append((code, delta))
worst.sort(key=lambda x: -x[1])
if cmp:
    over1 = [x for x in worst if x[1] > 1.0]
    print('    可比 %d 只；序列形状偏差 >1%% 的 %d 只，>5%% 的 %d 只'
          % (cmp, len(over1), len([x for x in worst if x[1] > 5])))
    print('    偏差最大 10 只（%）：', [(c, round(d, 2)) for c, d in worst[:10]])
else:
    print('    新浪对照未取到数据（接口不可用）')
print('\n完成。')
