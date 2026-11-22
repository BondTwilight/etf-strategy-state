# -*- coding: utf-8 -*-
"""探测次方分钟线接口：能否取到 14:50 / 14:57 / 收盘 三个价"""
import json
import urllib.parse
import urllib.request

KEY = "ak_REPLACE_WITH_SECRET"
BASE = "https://www.cifangquant.com/api"


def get(path, params=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"x-api-key": KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
        return body.get("code"), body.get("message"), body.get("data")
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, e), None


TRIES = [
    ("/fund/hist_min", {"symbol": "510300", "start_date": "2026-10-20",
                        "end_date": "2026-10-20", "freq": "1min"}),
    ("/fund/hist_min", {"symbol": "510300", "start_date": "2026-10-20",
                        "end_date": "2026-10-20"}),
    ("/fund/hist_min", {"symbol": "510300", "date": "2026-10-20"}),
    ("/fund/hist_min", {"symbol": "510300", "period": "1m",
                        "start_date": "2026-10-20", "end_date": "2026-10-20"}),
]

for path, p in TRIES:
    code, msg, data = get(path, p)
    print("=" * 70)
    print(path, p)
    print("  code=%s msg=%s" % (code, msg))
    if data is None:
        continue
    if isinstance(data, dict):
        k = list(data.keys())[:3]
        print("  返回 dict，键样例 %s，共 %d 键" % (k, len(data)))
        v = data.get(k[0]) if k else None
        if isinstance(v, list) and v:
            print("  行数 %d ｜ 首行 %s" % (len(v), v[0]))
            print("  末行 %s" % (v[-1],))
    elif isinstance(data, list):
        print("  返回 list，长度 %d" % len(data))
        if data:
            print("  首行 %s" % (data[0],))
            print("  末行 %s" % (data[-1],))
    break
