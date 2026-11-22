# -*- coding: utf-8 -*-
"""核对：本地行情是否早于 ETF 实际上市日（如有=本地回测存在幽灵交易）"""
import json

import pandas as pd
import tushare as ts

ts.set_token("405585c460d0d7d686644d58e138ea06d34915cee14e9c8914e5ea64")
pro = ts.pro_api()
pro._DataApi__http_url = "https://fast.xiaodefa.cn"

pool = json.load(open('data/fixed_pool.json', encoding='utf-8'))
codes = pool['codes']
big = pd.read_parquet('data/etf_qfq_cifang.parquet')
first = big.groupby('code')['date'].min()

# 场内基金名录（含上市日期）
lst = pro.fund_basic(market='E', status='L')
lst['c6'] = lst['ts_code'].str[:6]
loop = dict(zip(lst['c6'], lst['list_date'].astype(str)))

CHECK = ['513360', '515210', '512690', '513060', '512890', '159967',
         '588010', '513350', '159529', '515080']
print('%-8s %-12s %-12s %s' % ('代码', '本地首根', '上市日', '判定'))
print('-' * 58)
phantom = []
for c in CHECK:
    f = str(first.get(c, ''))[:10]
    ld = loop.get(c, '')
    ld_fmt = '%s-%s-%s' % (ld[:4], ld[4:6], ld[6:8]) if len(ld) == 8 else '?'
    if not f or ld_fmt == '?':
        verdict = '缺数据'
    elif f < ld_fmt:
        verdict = '⚠️ 早于上市 → 幽灵数据'
        phantom.append((c, f, ld_fmt))
    else:
        verdict = '正常'
    print('%-8s %-12s %-12s %s' % (c, f, ld_fmt, verdict))

if phantom:
    print('\n⚠️ 共 %d 只标的的本地行情早于上市日：' % len(phantom))
    for c, f, ld in phantom:
        print('   %s  本地首根 %s ｜ 实际上市 %s' % (c, f, ld))
else:
    print('\n✅ 抽查标的均未早于上市日')

# 全池统计
bad = []
for c in codes:
    f = str(first.get(c, ''))[:10]
    ld = loop.get(c, '')
    if not f or len(ld) != 8:
        continue
    ld_fmt = '%s-%s-%s' % (ld[:4], ld[4:6], ld[6:8])
    if f < ld_fmt:
        bad.append((c, f, ld_fmt))
print('\n全池：%d 只中 %d 只本地数据早于上市日' % (len(codes), len(bad)))
if bad[:15]:
    print('  样例:', bad[:15])
