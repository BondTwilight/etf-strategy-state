# -*- coding: utf-8 -*-
"""_probe_cors.py —— 决定架构可行性的三个探测

浏览器要「不带本机」地算策略，必须能直连拿到：
  1. 历史 K 线（算 20/26/50 日乖离、加权斜率）
  2. 实时快照（已有腾讯 qt，已验证 CORS）
  3. 次方 API（有 IOPV、有官方口径，但未知是否允许浏览器直连）
"""
import json
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"}


def probe(name, url, extra_headers=None):
    h = dict(UA)
    if extra_headers:
        h.update(extra_headers)
    try:
        req = urllib.request.Request(url, headers=h)
        r = urllib.request.urlopen(req, timeout=12)
        body = r.read()
        acao = r.headers.get("Access-Control-Allow-Origin")
        acah = r.headers.get("Access-Control-Allow-Headers")
        print("%-34s %s  len=%-7d ACAO=%-6s ACAH=%s"
              % (name, r.status, len(body), acao or "无", acah or "无"))
        return body, acao
    except Exception as e:
        print("%-34s FAIL  %r" % (name, e))
        return None, None


print("=" * 96)
print("① 历史 K 线 —— 腾讯 ifzq")
b, _ = probe("腾讯 fqkline (sh515020,60,qfq)",
             "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
             "?param=sh515020,day,,,60,qfq")
if b:
    try:
        j = json.loads(b)
        d = j["data"]["sh515020"]
        k = d.get("qfqday") or d.get("day") or []
        print("    解析：%d 根，首 %s 末 %s" % (len(k), k[0][0] if k else "-", k[-1][0] if k else "-"))
        print("    末根样例：", k[-1] if k else None)
    except Exception as e:
        print("    解析失败 %r  body[:180]=%r" % (e, b[:180]))

print("-" * 96)
print("② 历史 K 线 —— 东财 push2his")
b2, _ = probe("东财 kline (1.515020,101,60)",
              "https://push2his.eastmoney.com/api/qt/stock/kline/get"
              "?secid=1.515020&klt=101&fqt=1&lmt=60&fields1=f1,f2,f3,f4,f5"
              "&fields2=f51,f52,f53,f54,f55,f56,f57,f58")
if b2:
    try:
        j = json.loads(b2)
        k = j["data"]["klines"]
        print("    解析：%d 根，末根 %s" % (len(k), k[-1]))
    except Exception as e:
        print("    解析失败 %r  body[:180]=%r" % (e, b2[:180]))

print("-" * 96)
print("③ 次方官方 API（带 Key，看是否允许浏览器跨域）")
KEY = open(r"E:\workbuddy1.0\量化agent\_localdata\cifang_api_key.txt",
           encoding="utf-8").read().strip() if __import__("os").path.exists(
    r"E:\workbuddy1.0\量化agent\_localdata\cifang_api_key.txt") else ""
if not KEY:
    print("    Key 文件不存在，跳过")
else:
    u = ("https://www.cifangquant.com/api/fund/hist_em?symbol=515020"
         "&start_date=2026-09-01&end_date=2026-11-22&adjust=qfq")
    b3, _ = probe("次方 hist_em", u, {"x-api-key": KEY})
    if b3:
        try:
            j = json.loads(b3)
            rows = j["data"]["515020"]
            print("    解析：%d 行，末行 %s" % (len(rows), rows[-1]))
        except Exception as e:
            print("    解析失败 %r  body[:200]=%r" % (e, b3[:200]))
    probe("次方 spot", "https://www.cifangquant.com/api/fund/spot?symbol=515020,510300",
          {"x-api-key": KEY})

print("=" * 96)
