# -*- coding: utf-8 -*-
"""次方量化官方 API 探针：验证 Key、真实持仓、实时快照、历史日线（含 IOPV）"""
import json
import os
import urllib.parse
import urllib.request

KEY = "ak_REPLACE_WITH_SECRET"
BASE = "https://www.cifangquant.com/api"
HDR = {"x-api-key": KEY, "User-Agent": "Mozilla/5.0"}

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "_api_probe.json")


def get(path, **params):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except Exception as e:
        body = ""
        if hasattr(e, "read"):
            try:
                body = e.read().decode("utf-8")[:400]
            except Exception:
                pass
        return getattr(e, "code", None), {"_err": repr(e), "_body": body}


def show(tag, st, d, n=800):
    print("=" * 70)
    print("== %s  status=%s" % (tag, st))
    if isinstance(d, dict) and "_err" in d:
        print("   ERR", d["_err"], d["_body"])
        return
    s = json.dumps(d, ensure_ascii=False)
    print("   len=%d" % len(s))
    print("   " + s[:n])


res = {}

# 1 我发布的运行中策略（真实持仓来源）
st, d = get("/strategy/my-running")
show("my-running", st, d, 2000)
res["my_running"] = d

# 2 自动化交易策略列表
st, d = get("/trading/list")
show("trading/list", st, d, 1200)
res["trading_list"] = d

# 3 实时行情快照（含 iopv 与五档）
st, d = get("/fund/spot", symbol="515880,513290,159100,510300,159552,515020,515450")
show("fund/spot", st, d, 1600)
res["spot"] = d

# 4 历史日线（含 IOPV）
st, d = get("/fund/hist_em", symbol="510300", start_date="2026-05-26",
            end_date="2026-11-22", adjust="none")
show("hist_em 510300", st, d, 600)
res["hist_510300"] = d

# 5 公开策略收益排行
st, d = get("/strategy/list/rank", start_date="2026-10-01", top_n=10)
show("list/rank", st, d, 1200)
res["rank"] = d

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print("\n已存 %s" % OUT)
