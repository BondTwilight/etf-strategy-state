# -*- coding: utf-8 -*-
"""探测：跨境 ETF 的溢价率（IOPV）数据是否可得。

如果拿不到 IOPV/净值，就无法分解「价格乖离」里有多少是标的下跌、
有多少是溢价崩塌 —— 而后者不构成均值回归的理由。
"""
import json
import urllib.request
import urllib.error

import cifang_api as cf

BASE = cf.BASE
K = cf.API_KEY


def call(path, timeout=15):
    url = BASE + path
    req = urllib.request.Request(url, headers={'x-api-key': K,
                                              'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            try:
                j = json.loads(body.decode('utf-8'))
            except Exception:
                j = {'_raw': body[:300].decode('utf-8', 'replace')}
            return r.status, j
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return -1, str(e)[:120]


CANDS = [
    '/api/fund/spot?symbols=513100,513050',
    '/api/fund/spot?symbol=513100',
    '/api/fund/info?symbol=513100',
    '/api/fund/nav?symbol=513100&start_date=2026-10-01&end_date=2026-10-20',
    '/api/fund/iopv?symbol=513100',
    '/api/fund/detail?symbol=513100',
]

for p in CANDS:
    st, j = call(p)
    tag = ''
    if isinstance(j, dict):
        keys = list(j.keys())[:8]
        data = j.get('data')
        if isinstance(data, list) and data:
            item = data[0]
            tag = 'data[0] keys=' + str(list(item.keys())[:14] if isinstance(item, dict) else type(item).__name__)
        elif isinstance(data, dict):
            tag = 'data keys=' + str(list(data.keys())[:14])
        else:
            tag = 'msg=' + str(j.get('message') or j.get('msg') or j.get('_raw') or '')[:70]
        print('%-62s HTTP %-4s %-6s %s' % (p[:62], st, '|'.join(map(str, keys))[:40], tag))
    else:
        print('%-62s HTTP %-4s %s' % (p[:62], st, str(j)[:60]))

print()
# tushare 侧：场内 ETF 单位净值
try:
    import tushare as ts
    ts.set_token('405585c460d0d7d686644d58e138ea06d34915cee14e9c8914e5ea64')
    pro = ts.pro_api()
    pro._DataApi__http_url = 'https://fast.xiaodefa.cn'
    for fn, kw in (('fund_nav', dict(ts_code='513100.SH', start_date='20261010', end_date='20261020')),
                   ('fund_daily', dict(ts_code='513100.SH', start_date='20261010', end_date='20261020')),
                   ('index_dailybasic', dict(ts_code='000300.SH', start_date='20261010', end_date='20261020'))):
        try:
            d = getattr(pro, fn)(**kw)
            print('tushare %-16s 行 %-5d 列 %s' % (fn, len(d), list(d.columns)[:10]))
        except Exception as e:
            print('tushare %-16s FAIL %s' % (fn, str(e)[:100]))
except Exception as e:
    print('tushare 不可用:', e)
