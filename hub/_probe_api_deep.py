# -*- coding: utf-8 -*-
"""_probe_api_deep.py —— 次方 API 能力与权限的实证盘点

目的不是"能不能调通"（早就通了），而是回答四个决定架构的问题：
  ① 官方 /api/fund/momentum 能不能算加权斜率 V2 → 能否用来校验浏览器端移植的公式
  ② /api/fund/hist_intraday 拿每天 14:30 的价 → 与收盘价差多少（这决定预测精度）
  ③ /api/fund/spot 的 IOPV → 溢价率能不能算（腾讯没有这个字段）
  ④ /api/fund/exchange_rank 覆盖多少只 → 能不能用来选池
"""
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = "https://www.cifangquant.com/api"
KEY = ""
kp = r"E:\workbuddy1.0\量化agent\_localdata\cifang_api_key.txt"
if os.path.exists(kp):
    KEY = open(kp, encoding="utf-8").read().strip()

MOMO = ["518880", "159509", "588000", "501225", "513100", "513310",
        "159915", "162719", "159985", "513030", "513290", "513520"]


def call(path, params=None, method="GET", body=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None
    hdr = {"x-api-key": KEY}
    if body is not None:
        data = json.dumps(body).encode()
        hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdr, method=method)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


def main():
    if not KEY:
        print("没有 API Key，退出")
        return 1

    # ---------- ① 官方动量（加权斜率 V2，收盘价版） ----------
    print("=" * 90)
    print("① POST /api/fund/momentum  weighted_slope_close_v2, period=20, pool=12")
    try:
        j = call("/fund/momentum",
                 {"momentum_calculation_type": "weighted_slope_close_v2",
                  "momentum_period": 20, "etf_pool": MOMO,
                  "end_date": "2026-11-20"},
                 method="POST",
                 body={"momentum_calculation_type": "weighted_slope_close_v2",
                       "momentum_period": 20, "etf_pool": MOMO,
                       "end_date": "2026-11-20"})
        rows = j.get("data") or []
        print("    code      official_momentum   name")
        off = {}
        for x in rows:
            off[x["etf_code"]] = x["momentum_value"]
            print("    %-9s %-19s %s" % (x["etf_code"], x["momentum_value"], x.get("etf_name")))
        # 与 _verify_predict.py 算的 score 比
        mine = {"518880": -0.495497, "159509": -0.497259, "588000": 0.002566,
                "501225": -0.384696, "513100": -0.422387, "513310": -0.425322,
                "159915": -0.614731, "162719": -0.645715, "159985": -0.097267,
                "513030": -0.002177, "513290": -0.005656, "513520": -0.705463}
        print("\n    官方 vs 本地 score（比值应恒定 —— 说明只差一个量纲）")
        ratios = []
        for c in MOMO:
            o, m = off.get(c), mine.get(c)
            if o is None or m is None or abs(m) < 1e-9:
                continue
            ratios.append(o / m)
            print("      %-7s official=%-12s mine=%-12.6f  ratio=%.4f" % (c, o, m, o / m))
        if ratios:
            print("    ratio 中位 %.4f ｜ 极差 %.4f~%.4f"
                  % (sorted(ratios)[len(ratios) // 2], min(ratios), max(ratios)))
    except Exception as e:
        print("    FAIL %r" % (e,))

    # ---------- ② hist_intraday 14:30 vs 收盘 ----------
    print("\n" + "=" * 90)
    print("② GET /api/fund/hist_intraday time=14:30 vs hist_em 收盘（偏差）")
    try:
        a = call("/fund/hist_intraday",
                 {"symbol": ",".join(MOMO[:6]), "start_date": "2026-11-01",
                  "end_date": "2026-11-20", "time": "14:30", "adjust": "qfq"})
        b = call("/fund/hist_em",
                 {"symbol": ",".join(MOMO[:6]), "start_date": "2026-11-01",
                  "end_date": "2026-11-20", "adjust": "qfq"})
        print("    code    date        14:30     close    diff%")
        diffs = []
        for c in MOMO[:6]:
            ra = (a.get("data") or {}).get(c) or []
            rb = (b.get("data") or {}).get(c) or []
            if not ra or not rb:
                continue
            x, y = ra[-1], rb[-1]
            p1430, close = x[2], y[2]
            d = (p1430 / close - 1) * 100
            diffs.append(abs(d))
            print("    %-7s %-11s %-8.4f %-8.4f %+.3f" % (c, x[0], p1430, close, d))
        if diffs:
            print("    |偏差| 平均 %.3f%%  最大 %.3f%%" % (sum(diffs) / len(diffs), max(diffs)))
    except Exception as e:
        print("    FAIL %r" % (e,))

    # ---------- ③ spot 的 IOPV → 溢价 ----------
    print("\n" + "=" * 90)
    print("③ GET /api/fund/spot —— IOPV 与五档（腾讯没有的字段）")
    try:
        j = call("/fund/spot", {"symbol": ",".join(MOMO)})
        d = j.get("data") or {}
        print("    code    last     iopv     prem%    bid1/ask1 额(亿)")
        for c in MOMO:
            q = d.get(c)
            if not q:
                print("    %-7s 无数据" % c)
                continue
            iopv = q.get("iopv")
            prem = (q["last"] / iopv - 1) * 100 if iopv else None
            amt = (q.get("amount") or 0) / 1e8
            print("    %-7s %-8.3f %-8s %-8s %s/%s %6.2f"
                  % (c, q["last"], ("%.4f" % iopv) if iopv else "null",
                     ("%+.2f" % prem) if prem is not None else "—",
                     q.get("bid_price1"), q.get("ask_price1"), amt))
    except Exception as e:
        print("    FAIL %r" % (e,))

    # ---------- ④ exchange_rank 覆盖 ----------
    print("\n" + "=" * 90)
    print("④ GET /api/fund/exchange_rank —— 覆盖多少只")
    try:
        j = call("/fund/exchange_rank", {"sort_by": "1yzf", "sort_order": "desc", "limit": 5})
        rows = j.get("data") or []
        print("    limit=5 返回 %d 条，样例：%s" % (len(rows), rows[0] if rows else None))
        j2 = call("/fund/exchange_rank", {"sort_by": "1yzf", "sort_order": "desc", "limit": 30000})
        print("    limit=30000 返回 %d 条 ⇒ 可用于选池" % len(j2.get("data") or []))
    except Exception as e:
        print("    FAIL %r" % (e,))

    print("=" * 90)
    return 0


if __name__ == "__main__":
    sys.exit(main())
