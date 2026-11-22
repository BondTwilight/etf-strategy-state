# -*- coding: utf-8 -*-
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
            b = json.loads(r.read().decode("utf-8"))
        return r.status, b.get("code"), (b.get("message") or ""), b.get("data")
    except urllib.error.HTTPError as e:
        return e.code, None, e.read().decode("utf-8", "replace")[:200], None
    except Exception as e:
        return -1, None, str(e)[:80], None


TRIES = [
    ("datetime", {"symbol": "510300", "start_time": "2026-10-20 14:40:00",
                  "end_time": "2026-10-20 15:00:00"}),
    ("date only", {"symbol": "510300", "start_time": "2026-10-20",
                   "end_time": "2026-10-20"}),
    ("full day", {"symbol": "510300", "start_time": "2026-10-20 09:30:00",
                  "end_time": "2026-10-20 15:00:00"}),
]

for name, p in TRIES:
    st, c, m, d = get("/fund/hist_min", p)
    print("=" * 74)
    print("%-10s HTTP %s code=%s msg=%s" % (name, st, c, m[:80]))
    if not d:
        continue
    if isinstance(d, dict):
        ks = list(d.keys())[:2]
        print("  dict 键 %s" % ks)
        v = d[ks[0]]
    else:
        v = d
    print("  类型 %s 长度 %d" % (type(v).__name__, len(v) if hasattr(v, "__len__") else -1))
    if isinstance(v, list) and v:
        print("  首行 %s" % (v[0],))
        print("  末行 %s" % (v[-1],))
    break

print("\n=== hist_intraday（另一端点，可能要 start_date/end_date）===")
st, c, m, d = get("/fund/hist_intraday",
                  {"symbol": "510300", "start_date": "2026-10-20",
                   "end_date": "2026-10-20"})
print("HTTP %s code=%s msg=%s" % (st, c, m[:120]))
if d:
    print("  类型", type(d).__name__, "长度", len(d) if hasattr(d, "__len__") else "-")
    if isinstance(d, list) and d:
        print("  首行", d[0])
    elif isinstance(d, dict):
        k = list(d.keys())[:2]
        print("  键", k)
        print("  样例", str(d[k[0]])[:300])
