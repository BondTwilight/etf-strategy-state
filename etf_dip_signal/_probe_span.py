# -*- coding: utf-8 -*-
"""探测 hist_min 的时间跨度上限与错误详情"""
import json
import urllib.parse
import urllib.request

KEY = "ak_REPLACE_WITH_SECRET"
BASE = "https://www.cifangquant.com/api"


def get(params):
    url = BASE + "/fund/hist_min?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-api-key": KEY})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            b = json.loads(r.read().decode("utf-8"))
        return r.status, b.get("code"), "", b.get("data")
    except urllib.error.HTTPError as e:
        return e.code, None, e.read().decode("utf-8", "replace")[:260], None
    except Exception as e:
        return -1, None, str(e)[:100], None


CASES = [
    ("同日 14:40-15:00", "2026-10-20 14:40:00", "2026-10-20 15:00:00"),
    ("同日 09:30-15:00", "2026-10-20 09:30:00", "2026-10-20 15:00:00"),
    ("跨2日", "2026-10-19 14:40:00", "2026-10-20 15:00:00"),
    ("跨5日", "2026-10-14 14:40:00", "2026-10-20 15:00:00"),
    ("跨1月", "2026-09-20 14:40:00", "2026-10-20 15:00:00"),
]
for name, s, e in CASES:
    st, c, m, d = get({"symbol": "510300", "start_time": s, "end_time": e})
    n = 0
    if isinstance(d, dict) and "510300" in d:
        n = len(d["510300"])
    print("%-16s HTTP %-4s code=%-5s 行数 %-6d %s" % (name, st, c, n, m[:150]))
