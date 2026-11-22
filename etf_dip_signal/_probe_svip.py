# -*- coding: utf-8 -*-
"""SVIP 接口实测：hist_min（分钟线）+ hist_intraday（每日固定时点累计行情）"""
import json
import os
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

KEY = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "_localdata", "cifang_api_key.txt"), encoding="utf-8").read().strip()
BASE = "https://www.cifangquant.com/api"
HDR = {"x-api-key": KEY, "User-Agent": "Mozilla/5.0"}


def call(path, **params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            d = json.loads(r.read().decode("utf-8"))
        return r.status, d
    except Exception as e:
        body = ""
        if hasattr(e, "read"):
            try:
                body = e.read().decode("utf-8")[:300]
            except Exception:
                pass
        return getattr(e, "code", None), {"_err": repr(e), "_body": body}


print("=" * 72)
print("1) hist_min  分钟线（2026-11-20 14:25-14:35, 510300）")
st, d = call("/fund/hist_min", symbol="510300",
             start_time="2026-11-20 14:25:00", end_time="2026-11-20 14:35:00",
             adjust="none")
print("   status =", st)
if st == 200 and d.get("code") == 0:
    rows = d["data"].get("510300") or []
    print("   行数 =", len(rows))
    for r in rows:
        print("   ", r[:6])
else:
    print("   ", json.dumps(d, ensure_ascii=False)[:300])

print()
print("=" * 72)
print("2) hist_intraday  每日 14:30 累计行情（510300, 2026-11-01~11-20）")
st, d = call("/fund/hist_intraday", symbol="510300",
             start_date="2026-11-01", end_date="2026-11-20", time="14:30",
             adjust="none")
print("   status =", st)
if st == 200 and d.get("code") == 0:
    rows = d["data"].get("510300") or []
    print("   行数 =", len(rows))
    for r in rows:
        print("   ", r)
else:
    print("   ", json.dumps(d, ensure_ascii=False)[:300])

print()
print("=" * 72)
print("3) 14:30 价 vs 收盘价：偏差分布（510300, 2026-10-01~11-20）")
st, d = call("/fund/hist_intraday", symbol="510300",
             start_date="2026-10-01", end_date="2026-11-20", time="14:30",
             adjust="none")
st2, d2 = call("/fund/hist_em", symbol="510300",
               start_date="2026-10-01", end_date="2026-11-20", adjust="none")
if st == 200 and d.get("code") == 0 and st2 == 200:
    intra = pd.DataFrame(d["data"]["510300"],
                         columns=["date", "o", "c1430", "h", "l", "chg", "vol", "iopv"])
    intra["date"] = pd.to_datetime(intra["date"])
    daily = pd.DataFrame(d2["data"]["510300"],
                         columns=["date", "o", "c", "h", "l", "chg", "v", "amt", "iopv"])
    daily["date"] = pd.to_datetime(daily["date"])
    m = intra.merge(daily[["date", "c"]], on="date")
    m["dev"] = (m["c1430"] / m["c"] - 1) * 100
    print("   配对交易日 =", len(m))
    print("   偏差 中位 %+.3f%% ｜ 均值 %+.3f%% ｜ std %.3f ｜ |偏差| 中位 %.3f%% ｜ P90 %.3f%% ｜ 最大 %.3f%%"
          % (m["dev"].median(), m["dev"].mean(), m["dev"].std(),
             m["dev"].abs().median(), m["dev"].abs().quantile(0.9), m["dev"].abs().max()))
    print("   尾部（|偏差|>0.5%）：")
    for _, r in m.reindex(m["dev"].abs().sort_values(ascending=False).index).head(5).iterrows():
        print("      %s  14:30 %.4f  收盘 %.4f  %+.3f%%"
              % (r["date"].strftime("%Y-%m-%d"), r["c1430"], r["c"], r["dev"]))
    m.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "_probe1430.csv"), index=False, encoding="utf-8-sig")
else:
    print("   失败", st, st2)
