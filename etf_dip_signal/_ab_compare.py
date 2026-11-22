# -*- coding: utf-8 -*-
"""A/B 对比（引擎同构判定）：次方前复权 vs 腾讯/新浪（当前腾讯 501 → 实际新浪不复权）

判定与 engine/indicators 完全一致：
  1) 当日价三种口径（日线末根=今天→替换；rt==末根收盘→不追加；否则→追加）
  2) 近 5 根 bias20 的最小值 < 该标的阈值 ⇒ 进候选池（TREND_FILTER_MODE=0，无趋势过滤）
"""
import json
import time
import numpy as np
import pandas as pd

import config as cfg
import tdx_api
import indicators as ind
import cifang_quote
import web_quote

POOL = json.load(open('data/fixed_pool.json', encoding='utf-8'))
CODES = POOL['codes']
BMAP = POOL.get('bmap', {})
TODAY = pd.Timestamp.today().strftime('%Y-%m-%d')
NEED = max(cfg.BIAS_SORT_DAYS, cfg.BIAS_BUY_DAYS)

rt = tdx_api.get_realtime(CODES)
PMAP = dict(zip(rt['code'], rt['price'])) if len(rt) else {}
print('实时行情 %d 只，交易日 %s' % (len(rt), TODAY))


def build(cifang: bool):
    t0 = time.time()
    if cifang:
        km = cifang_quote.prefetch_batch(CODES, count=NEED + 12)
        src = '次方qfq'
    else:
        web_quote.SRC_STATS.update({'tencent': 0, 'sina': 0})
        web_quote.clear_kline_cache()
        km = web_quote.fetch_daily_kline_batch(CODES, count=NEED + 2)
        src = 'web(腾讯%d/新浪%d)' % (web_quote.SRC_STATS['tencent'],
                                     web_quote.SRC_STATS['sina'])
    print('[%s] %d 只，%.1fs' % (src, len(km), time.time() - t0))
    return km


def evaluate(km):
    """返回 DataFrame: code / bias20 / bias50 / bmin5 / th / 是否候选"""
    recs = []
    for code in CODES:
        df = km.get(code)
        px = PMAP.get(code)
        if df is None or len(df) == 0 or px is None or px <= 0:
            continue
        closes = pd.to_numeric(df['close'], errors='coerce').dropna().to_numpy(dtype=float)
        if len(closes) < NEED:
            continue
        closes = np.asarray(ind._sanitize(closes), dtype=float)
        last_d = str(df['date'].iloc[-1])[:10]
        if last_d == TODAY:                       # 情况A：替换末根
            s = list(closes[:-1]) + [float(px)]
        elif abs(float(px) - closes[-1]) < 1e-9:  # 情况B：同一根
            s = list(closes)
        else:                                     # 情况C：追加
            s = list(closes) + [float(px)]
        ser = pd.Series(s[-24:]).reset_index(drop=True)
        b20 = (ser / ser.rolling(20).mean() - 1) * 100
        bmin5 = float(b20.iloc[-5:].min())
        full = pd.Series(s[-NEED:]).reset_index(drop=True)
        bias20 = float((full.iloc[-1] / full.rolling(20).mean().iloc[-1] - 1) * 100)
        bias50 = float((full.iloc[-1] / full.rolling(50).mean().iloc[-1] - 1) * 100)
        th = BMAP.get(code, cfg.BUY_BIAS_TH)
        recs.append({'代码': code, 'bias20': bias20, 'bias50': bias50,
                     'bmin5': bmin5, '阈值': th, '候选': bool(bmin5 < th)})
    return pd.DataFrame(recs)


A = evaluate(build(True))
B = evaluate(build(False))

print('\n次方可评估 %d 只，候选 %d 只' % (len(A), int(A['候选'].sum())))
print('web  可评估 %d 只，候选 %d 只' % (len(B), int(B['候选'].sum())))

m = A.merge(B, on='代码', suffixes=('_cf', '_web'))
for col in ('bias20', 'bias50'):
    d = (m[col + '_cf'] - m[col + '_web']).abs()
    print('%s |差|：均值 %.3fpp 中位 %.3fpp P95 %.3fpp 最大 %.3fpp'
          % (col, d.mean(), d.median(), d.quantile(.95), d.max()))

flip = m[m['候选_cf'] != m['候选_web']]
print('\n【判定翻转】%d 只' % len(flip))
if len(flip):
    cols = ['代码', 'bmin5_cf', 'bmin5_web', '阈值_web', '候选_cf', '候选_web']
    print(flip[cols].to_string(index=False))
