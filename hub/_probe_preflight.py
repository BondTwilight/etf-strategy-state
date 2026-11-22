# -*- coding: utf-8 -*-
"""_probe_preflight.py —— 预检到底放不放行 x-api-key

CORS 真正的关卡不是 GET 的 ACAO，而是 OPTIONS 预检：
自定义头 x-api-key 会触发预检，服务端必须在 Access-Control-Allow-Headers 里放行它，
否则浏览器直接拒绝发实际请求。
"""
import json
import os
import urllib.request

KEY = ""
kp = r"E:\workbuddy1.0\量化agent\_localdata\cifang_api_key.txt"
if os.path.exists(kp):
    KEY = open(kp, encoding="utf-8").read().strip()

ORIGINS = [
    "https://etf-strategy-live.app.workbuddy.host",
    "https://example.com",
    "http://127.0.0.1:8899",
    "null",
]

print("=" * 100)
print("OPTIONS 预检响应头全量（x-api-key 能不能过）")
print("=" * 100)
for org in ORIGINS:
    req = urllib.request.Request(
        "https://www.cifangquant.com/api/fund/spot?symbol=510300",
        headers={
            "Origin": org,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-api-key",
            "User-Agent": "Mozilla/5.0",
        }, method="OPTIONS")
    try:
        r = urllib.request.urlopen(req, timeout=20)
        h = r.headers
        print("\nOrigin: %s  → %s" % (org, r.status))
        for k in ("Access-Control-Allow-Origin", "Access-Control-Allow-Methods",
                  "Access-Control-Allow-Headers", "Access-Control-Max-Age",
                  "Access-Control-Allow-Credentials", "Vary"):
            print("    %-34s %s" % (k, h.get(k)))
    except Exception as e:
        print("\nOrigin: %s  → FAIL %r" % (org, e))
        h = getattr(e, "headers", None)
        if h:
            for k in ("Access-Control-Allow-Origin", "Access-Control-Allow-Headers"):
                print("    %-34s %s" % (k, h.get(k)))

# 带 Origin 的实际 GET，看是否真的能拿到 body
print("\n" + "=" * 100)
print("带 Origin 的实际 GET（ACAO + 数据完整性）")
print("=" * 100)
req = urllib.request.Request(
    "https://www.cifangquant.com/api/fund/spot?symbol=510300,515020",
    headers={"Origin": "https://etf-strategy-live.app.workbuddy.host",
             "x-api-key": KEY, "User-Agent": "Mozilla/5.0"})
r = urllib.request.urlopen(req, timeout=20)
j = json.loads(r.read())
print("  ACAO:", r.headers.get("Access-Control-Allow-Origin"))
print("  code:", j.get("code"), " 标的数:", len(j.get("data") or {}))
for c, q in list((j.get("data") or {}).items())[:2]:
    print("   ", c, "last=", q["last"], "iopv=", q.get("iopv"))
print("=" * 100)
