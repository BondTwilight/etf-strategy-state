# -*- coding: utf-8 -*-
import json
import pandas as pd
import config as cfg
import cifang_quote
import tdx_api
import indicators as ind

CODES = json.load(open('data/fixed_pool.json', encoding='utf-8'))['codes']
print('DATA_SOURCE =', cfg.DATA_SOURCE)

rt = tdx_api.get_realtime(CODES[:5])
print('\n[实时] rows=%d cols=%s' % (len(rt), list(rt.columns)))
if len(rt):
    print(rt.head())

cifang_quote.clear_cache()
km = cifang_quote.prefetch_batch(CODES, count=62)
c0 = CODES[0]
df = km.get(c0)
print('\n[K线] %s rows=%s cols=%s' % (c0, 0 if df is None else len(df), None if df is None else list(df.columns)))
if df is not None and len(df):
    print(df.tail(3).to_string())

rt2 = tdx_api.get_realtime(CODES)
print('\n[实时全池] rows=%d, 有价 %d' % (
    len(rt2), int((pd.to_numeric(rt2['price'], errors='coerce') > 0).sum()) if len(rt2) else 0))

bias = ind.calculate_bias(CODES, rt2)
print('\n[乖离率] rows=%d' % len(bias))
print(bias.head().to_string() if len(bias) else '（空）')
