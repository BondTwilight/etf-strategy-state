# -*- coding: utf-8 -*-
import urllib.request
req = urllib.request.Request(
    'https://qt.gtimg.cn/q=sh515880,sh510300,sz159509,sh511880,sh512800',
    headers={'User-Agent': 'Mozilla/5.0'})
t = urllib.request.urlopen(req, timeout=10).read().decode('gbk', errors='ignore')
for line in t.split(';'):
    line = line.strip()
    if '="' not in line:
        continue
    v = line.split('="', 1)[1].rstrip('"')
    f = v.split('~')
    name = f[1]
    px = float(f[3] or 0)
    prev = float(f[4] or 0)
    iopv = float(f[78] or 0) if len(f) > 78 and f[78] else 0.0
    nav = float(f[81] or 0) if len(f) > 81 and f[81] else 0.0
    print('%-22s px=%.4f prev=%.4f f78=%.4f f81=%.4f  px/78-1=%+.2f%%  px/81-1=%+.2f%%'
          % (name, px, prev, iopv, nav,
             (px / iopv - 1) * 100 if iopv else float('nan'),
             (px / nav - 1) * 100 if nav else float('nan')))
print()
print('--- 515880 全字段 ---')
v = t.split(';')[0].split('="', 1)[1].rstrip('"')
for i, x in enumerate(v.split('~')[:60]):
    print(i, repr(x))
