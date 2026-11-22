# -*- coding: utf-8 -*-
"""测 14:45 / 14:50 / 14:57 相对收盘价的实际偏差分布（分块拉取）"""
import json
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

KEY = "ak_REPLACE_WITH_SECRET"
BASE = "https://www.cifangquant.com/api"

CODES = ["510300", "159967", "513350", "588010", "562660", "512890",
         "159509", "515880", "513060", "513360", "159851", "515210"]
# 每段 10 个自然日（约 7 个交易日 ≈ 1700 根），远低于单次上限
SEGMENTS = [("2025-01-06", "2025-01-17"), ("2025-03-03", "2025-03-14"),
            ("2025-07-07", "2025-07-18"), ("2025-09-01", "2025-09-12"),
            ("2026-04-06", "2026-04-17"), ("2026-06-01", "2026-06-12")]


def get(params, retry=3):
    url = BASE + "/fund/hist_min?" + urllib.parse.urlencode(params)
    for i in range(retry + 1):
        req = urllib.request.Request(url, headers={"x-api-key": KEY})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                b = json.loads(r.read().decode("utf-8"))
            if b.get("code") != 0:
                raise RuntimeError(b.get("message"))
            return b.get("data")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 + 3 * i)
                continue
            print("    HTTP %s" % e.code, end=" ")
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None


rows, miss = [], 0
t0 = time.time()
for code in CODES:
    for s, e in SEGMENTS:
        d = get({"symbol": code, "start_time": s + " 14:40:00",
                 "end_time": e + " 15:00:00"})
        if not d or code not in d:
            miss += 1
            continue
        df = pd.DataFrame(d[code], columns=["t", "o", "c", "h", "l", "pct",
                                            "vol", "amt", "iopv"])
        df["t"] = pd.to_datetime(df["t"])
        df["day"] = df["t"].dt.date
        df["hm"] = df["t"].dt.strftime("%H:%M")
        for day, g in df.groupby("day"):
            g = g.set_index("hm")["c"]
            if not {"14:45", "14:50", "14:57"}.issubset(set(g.index)):
                continue
            close = float(g.iloc[-1])          # 最后一根 = 收盘
            if close <= 0:
                continue
            rows.append((code, str(day), float(g["14:45"]), float(g["14:50"]),
                         float(g["14:57"]), close))
        time.sleep(0.35)
    print("  %-8s 累计 %4d 个交易日  %.0fs" % (code, len(rows), time.time() - t0), flush=True)

d = pd.DataFrame(rows, columns=["code", "day", "p1445", "p1450", "p1457", "close"])
if d.empty:
    print("无数据"); raise SystemExit

for k, c in (("r45", "p1445"), ("r50", "p1450"), ("r57", "p1457")):
    d[k] = d[c] / d["close"] - 1
d.to_csv("data/minute_calib.csv", index=False, encoding="utf-8-sig")

print("\n" + "=" * 74)
print("样本 %d 只 × %d 个交易日 = %d 观测 ｜ 失败段 %d"
      % (d.code.nunique(), d.day.nunique(), len(d), miss))
print("=" * 74)
print("%-8s %10s %10s %10s %10s %10s" % ("时点", "均值", "中位", "标准差", "5%分位", "95%分位"))
for k, nm in (("r45", "14:45"), ("r50", "14:50"), ("r57", "14:57")):
    x = d[k]
    print("%-8s %9.4f%% %9.4f%% %9.4f%% %9.4f%% %9.4f%%"
          % (nm, x.mean() * 100, x.median() * 100, x.std() * 100,
             x.quantile(0.05) * 100, x.quantile(0.95) * 100))
print("\n绝对偏差 90%% 分位：14:45 %.3f%% ｜ 14:50 %.3f%% ｜ 14:57 %.3f%%"
      % (d.r45.abs().quantile(0.9) * 100, d.r50.abs().quantile(0.9) * 100,
         d.r57.abs().quantile(0.9) * 100))
print("相邻时点之差 std：14:45−14:50 %.4f%% ｜ 14:50−14:57 %.4f%%"
      % ((d.r45 - d.r50).std() * 100, (d.r50 - d.r57).std() * 100))
print("\n按标的看 14:50 偏差 std（前 6）：")
print((d.groupby("code")["r50"].std() * 100).sort_values(ascending=False)
      .head(6).round(4).to_string())
