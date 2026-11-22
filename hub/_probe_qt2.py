# -*- coding: utf-8 -*-
"""_probe_qt2.py —— 确认腾讯 qt 行情字段位置"""
import urllib.request

CODES = ["sh515020", "sh515880", "sz513290", "sh515450", "sz159915"]
URL = "https://qt.gtimg.cn/q=" + ",".join(CODES)
req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
t = urllib.request.urlopen(req, timeout=10).read().decode("gbk", errors="ignore")

for line in t.split(";"):
    line = line.strip()
    if '="' not in line:
        continue
    v = line.split('="', 1)[1].rstrip('"')
    f = v.split("~")
    print("n=%-3d code=%s name=%s price=%s pre=%s open=%s chg=%s pct=%s hi=%s lo=%s"
          % (len(f), f[2], f[1], f[3], f[4], f[5],
             f[31] if len(f) > 31 else "?",
             f[32] if len(f) > 32 else "?",
             f[33] if len(f) > 33 else "?",
             f[34] if len(f) > 34 else "?"))
