# -*- coding: utf-8 -*-
"""查今日实时行情：验证 11-03 止损的两只是否卖在低点。"""
import urllib.request

CODES = ['sz159967', 'sh588170', 'sh515880', 'sh510300',
         'sz159915', 'sh588020', 'sz159667', 'sh513350', 'sh513360']

url = 'https://qt.gtimg.cn/q=' + ','.join(CODES)
req = urllib.request.Request(url, headers={
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://finance.sina.com.cn',
})
raw = urllib.request.urlopen(req, timeout=15).read().decode('gbk', 'replace')

print('%-10s %-18s %10s %10s %10s %12s' % ('code', 'name', 'last', 'pre_close', 'chg%', 'amount(万)'))
for line in raw.strip().split('\n'):
    if '=' not in line:
        continue
    body = line.split('=', 1)[1].strip().strip(';').strip('"')
    f = body.split('~')
    if len(f) < 38:
        continue
    try:
        last = float(f[3])
        pre = float(f[4])
        chg = (last / pre - 1) * 100
        amt = float(f[37]) / 1e4 if f[37] else 0
        print('%-10s %-18s %10.4f %10.4f %+9.2f%% %12.0f'
              % (f[2], f[1][:16], last, pre, chg, amt))
    except Exception as e:
        print(f[2], 'parse fail:', str(e)[:60], f[:7])
