# -*- coding: utf-8 -*-
"""分钟数据可得性总探测：次方多参数组合 + tushare 代理 stk_mins"""
import json
import urllib.parse
import urllib.request

KEY = "ak_REPLACE_WITH_SECRET"
BASE = "https://www.cifangquant.com/api"


def get(path, params=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"x-api-key": KEY})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            b = json.loads(r.read().decode("utf-8"))
        return r.status, b.get("code"), (b.get("message") or "")[:40], b.get("data")
    except urllib.error.HTTPError as e:
        return e.code, None, e.read()[:120].decode("utf-8", "replace"), None
    except Exception as e:
        return -1, None, str(e)[:60], None


print("=== 0. 先确认鉴权正常 ===")
st, c, m, d = get("/fund/list", {"key_word": "510300"})
print("  /fund/list -> HTTP %s code=%s msg=%s" % (st, c, m))
print("  data 类型", type(d).__name__, "长度", len(d) if hasattr(d, "__len__") else "-")

print("\n=== 1. 次方分钟线参数矩阵 ===")
COMMON = [
    ("symbol", "510300"),
    ("start_date", "2026-10-20"),
    ("end_date", "2026-10-20"),
]
VARIANTS = [
    ("baseline+adjust", COMMON + [("adjust", "qfq")]),
    ("symbols 复数", [("symbols", "510300"), ("start_date", "2026-10-20"),
                   ("end_date", "2026-10-20")]),
    ("freq=1", COMMON + [("freq", "1")]),
    ("period=1", COMMON + [("period", "1")]),
    ("frequency=1m", COMMON + [("frequency", "1m")]),
    ("trade_date", [("symbol", "510300"), ("trade_date", "2026-10-20")]),
    ("start/end datetime", [("symbol", "510300"),
                            ("start_date", "2026-10-20 09:30:00"),
                            ("end_date", "2026-10-20 15:00:00")]),
]
for name, p in VARIANTS:
    st, c, m, d = get("/fund/hist_min", p)
    ok = "OK" if (isinstance(d, (list, dict)) and d) else "-"
    print("  %-20s HTTP %-4s code=%-4s %-40s %s" % (name, st, c, m, ok))

print("\n=== 2. 其它可能含分钟数据的端点 ===")
for path, p in [("/fund/hist_intraday", {"symbol": "510300"}),
                ("/fund/spot", {"symbol": "510300"}),
                ("/fund/hist", {"symbol": "510300", "start_date": "2026-10-20",
                                "end_date": "2026-10-20"})]:
    st, c, m, d = get(path, p)
    print("  %-24s HTTP %-4s code=%-4s %s" % (path, st, c, m))

print("\n=== 3. tushare 代理：ETF 分钟线 ===")
try:
    import tushare as ts
    ts.set_token("405585c460d0d7d686644d58e138ea06d34915cee14e9c8914e5ea64")
    pro = ts.pro_api()
    pro._DataApi__http_url = "https://fast.xiaodefa.cn"
    for code in ("510300.SH", "159967.SZ"):
        try:
            df = pro.stk_mins(ts_code=code, freq="1min",
                              start_date="2026-10-20 14:40:00",
                              end_date="2026-10-20 15:00:00")
            print("  stk_mins %-12s 行数 %s" % (code, len(df)))
            if len(df):
                print(df.head(3).to_string(index=False))
        except Exception as e:
            print("  stk_mins %-12s 失败 %s: %s" % (code, type(e).__name__, str(e)[:90]))
except Exception as e:
    print("  tushare 初始化失败：", e)
