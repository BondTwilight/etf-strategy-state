# -*- coding: utf-8 -*-
"""_probe_cors_all.py —— 把次方 19 个接口的 CORS 全测一遍

之前只测了 hist_em 和 spot 就断言"全部无 CORS"，这不严谨。
逐个测，包括 SVIP 专享的 hist_intraday / hist_min —— 万一有哪个带 ACAO，就能浏览器直连。
"""
import json
import os
import urllib.parse
import urllib.request

BASE = "https://www.cifangquant.com/api"
KEY = ""
kp = r"E:\workbuddy1.0\量化agent\_localdata\cifang_api_key.txt"
if os.path.exists(kp):
    KEY = open(kp, encoding="utf-8").read().strip()


def head(path, params=None, method="GET", body=None, hdr_extra=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    hdr = {"x-api-key": KEY}
    if hdr_extra:
        hdr.update(hdr_extra)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdr, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=20)
        return r.status, r.headers.get("Access-Control-Allow-Origin"), len(r.read())
    except Exception as e:
        code = getattr(e, "code", None)
        h = getattr(e, "headers", None)
        acao = h.get("Access-Control-Allow-Origin") if h else None
        return code, acao, str(e)[:40]


CASES = [
    ("GET  /fund/list", "/fund/list", {"key_word": "510300"}, "GET", None),
    ("GET  /fund/hist_em", "/fund/hist_em",
     {"symbol": "510300", "start_date": "2026-11-01", "end_date": "2026-11-20", "adjust": "qfq"}, "GET", None),
    ("GET  /fund/hist_intraday", "/fund/hist_intraday",
     {"symbol": "510300", "start_date": "2026-11-18", "end_date": "2026-11-20",
      "time": "14:30", "adjust": "qfq"}, "GET", None),
    ("GET  /fund/hist_min", "/fund/hist_min",
     {"symbol": "510300", "start_time": "2026-11-20 14:30:00",
      "end_time": "2026-11-20 14:35:00", "adjust": "qfq"}, "GET", None),
    ("GET  /fund/spot", "/fund/spot", {"symbol": "510300,515020"}, "GET", None),
    ("GET  /fund/exchange_rank", "/fund/exchange_rank",
     {"sort_by": "1yzf", "sort_order": "desc", "limit": 3}, "GET", None),
    ("POST /fund/momentum", "/fund/momentum", None, "POST",
     {"momentum_calculation_type": "weighted_slope_close_v2",
      "momentum_period": 20, "etf_pool": ["510300", "159915"]}),
    ("GET  /strategy/my-running", "/strategy/my-running", None, "GET", None),
    ("GET  /trading/list", "/trading/list", None, "GET", None),
]

print("=" * 100)
print("次方 API 全端点 CORS 实测（%s）" % ("有 Key" if KEY else "无 Key"))
print("=" * 100)
print("%-28s %-6s %-10s %s" % ("接口", "状态", "ACAO", "备注"))
print("-" * 100)
hits = []
for name, path, params, method, body in CASES:
    st, acao, extra = head(path, params, method, body)
    flag = "★ 有 CORS" if acao else ""
    if acao:
        hits.append((name, acao))
    print("%-28s %-6s %-10s %s %s" % (name, st, acao or "无", extra if isinstance(extra, str) else "", flag))

print("-" * 100)
print("带 CORS 的接口：%s" % (hits if hits else "一个都没有"))

# 再试：加 Origin 头，看是否回显（有些服务端只对白名单 Origin 回 ACAO）
print("\n再试：带 Origin: https://etf-strategy-live.app.workbuddy.host")
for name, path, params, method, body in CASES[:6]:
    st, acao, extra = head(path, params, method, body,
                           hdr_extra={"Origin": "https://etf-strategy-live.app.workbuddy.host"})
    print("  %-28s %-6s ACAO=%s" % (name, st, acao or "无"))

# 试 OPTIONS 预检（浏览器发实际请求前会先发 OPTIONS）
print("\n再试：OPTIONS 预检")
for name, path, params, method, body in CASES[:6]:
    st, acao, extra = head(path, None, "OPTIONS", None,
                           hdr_extra={"Origin": "https://etf-strategy-live.app.workbuddy.host",
                                      "Access-Control-Request-Method": "GET",
                                      "Access-Control-Request-Headers": "x-api-key"})
    print("  %-28s %-6s ACAO=%s" % (name, st, acao or "无"))
print("=" * 100)
