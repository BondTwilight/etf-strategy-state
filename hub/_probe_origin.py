# -*- coding: utf-8 -*-
"""_probe_origin.py —— 逐端点、逐 Origin 测放行情况

为什么：file:// 下 spot 通、hist_em 不通，说明不是「全站 CORS」而是「端点级」。
必须测清楚每个端点在每种 Origin 下的真实表现，否则又会得出错误结论。
"""
import os
import urllib.request

KEY = ""
kp = r"E:\workbuddy1.0\量化agent\_localdata\cifang_api_key.txt"
if os.path.exists(kp):
    KEY = open(kp, encoding="utf-8").read().strip()

ORIGINS = [
    ("无 Origin", None),
    ("null (file://)", "null"),
    ("发布域", "https://etf-strategy-live.app.workbuddy.host"),
    ("本地服务", "http://127.0.0.1:8899"),
]

EPS = [
    ("/fund/spot?symbol=510300", "spot"),
    ("/strategy/my-running", "my-running"),
    ("/fund/hist_em?symbol=510300&start_date=2026-11-01&end_date=2026-11-20&adjust=qfq", "hist_em"),
    ("/fund/hist_intraday?symbol=510300&start_date=2026-11-14&end_date=2026-11-20&time=14:30&adjust=qfq", "hist_intraday"),
    ("/fund/exchange_rank?sort_by=1yzf&limit=2", "exchange_rank"),
]

print("=" * 104)
print("%-14s %-16s %-8s %-6s %s" % ("端点", "Origin", "状态", "ACAO", "结论"))
print("-" * 104)
for path, name in EPS:
    for label, org in ORIGINS:
        h = {"x-api-key": KEY, "User-Agent": "Mozilla/5.0"}
        if org:
            h["Origin"] = org
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                "https://www.cifangquant.com" + path, headers=h), timeout=20)
            acao = r.headers.get("Access-Control-Allow-Origin")
            r.read()
            verdict = "放行" if acao else "✗ 浏览器会挡"
            print("%-14s %-16s %-8s %-6s %s" % (name, label, r.status, acao or "无", verdict))
        except Exception as e:
            print("%-14s %-16s %-8s %-6s %s" % (name, label, "-", "-", "FAIL %r" % (e,)))
    print("-" * 104)
