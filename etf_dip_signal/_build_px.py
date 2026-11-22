# -*- coding: utf-8 -*-
"""_build_px.py —— 重建统一行情库 data/all_etf_1120.parquet

为什么重建而不是「在 1119 上加一行」：
  all_etf_1119 是 11-19 抓的，前复权基准是 11-19；若 11-20 有 ETF 分红，
  11-19 及以前的价格本应被缩放，但旧文件不会自动调整 ⇒ 拼接会在分红日留一根假跳变。
  重拉一次（400 只 / 8 请求 / ~40 秒）可保证「单一来源、单一时点、统一复权」。

口径：
  源   = 次方量化 /api/fund/hist_em，adjust=qfq
  窗口 = 2015-01-05 ~ 2026-11-20（momo 需要 2018 起，线C/96863 需要 2020 起）
  清洗 = data_quality.repair_prices（尖峰式 + 台阶式跳变）
  输出 = long 表 code/date/open/high/low/close/volume/amount
"""
import datetime
import json
import os
import sys
import time

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import cifang_api
import data_quality

# 🔴 END 以前写死 2026-11-20，导致「每日刷新」永远停在 11-20。
# 现在默认取今天：源当天还没出日线时，max(date) 自然停在上一交易日，不会造假行。
# 需要复现历史时用 PX_END=2026-11-20 覆盖。
END = os.environ.get("PX_END") or datetime.date.today().strftime("%Y-%m-%d")
START = "2015-01-01"
# 文件名是历史遗留（首次建成于 11-20），内容每天都重建；改文件名会牵动 hub_build/_industry。
OUT = os.path.join("data", "all_etf_1120.parquet")

pool = json.load(open("data/fixed_pool.json", encoding="utf-8"))
P381 = [str(c) for c in pool["codes"]]
CONSUME = ["162411", "513100", "161128", "588000", "162415", "515450"]
MOMO = ["518880", "159509", "588000", "501225", "513100", "513310",
        "159915", "162719", "159985", "513030", "513290", "513520"]
BENCH = ["510300", "510500", "512100", "159915", "510880"]
WATCH = ["515880", "511880", "512800", "515020", "159552", "563300", "159967",
         "159100", "511990"]

codes = list(dict.fromkeys(P381 + CONSUME + MOMO + BENCH + WATCH))
print("需要 %d 只（去重后）" % len(codes))

t0 = time.time()
raw = cifang_api.hist_em(codes, START, END, adjust="qfq")
print("次方返回 %d 只，耗时 %.0fs" % (len(raw), time.time() - t0))

frames, bad, last_days = [], [], {}
for c in codes:
    df = raw.get(c)
    if df is None or len(df) == 0:
        bad.append(c)
        continue
    d = df.copy()
    d["date"] = d["date"].astype(str).str[:10]
    d = d.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    cols = ["date", "open", "high", "low", "close", "volume"]
    if "amount" in d.columns:
        cols.append("amount")
    s = d[cols].copy()
    s2, hits = data_quality.repair_prices(s)
    if len(hits):
        print("   [修复] %s %d 根：%s" % (c, len(hits), ",".join(hits[:4])))
    s2["code"] = c
    frames.append(s2)
    last_days[c] = s2["date"].iloc[-1]

print("\n缺失 %d 只：%s" % (len(bad), " ".join(bad[:20])))
vc = pd.Series(last_days).value_counts().sort_index()
print("最新日分布：")
print(vc.to_string())

if not frames:
    raise SystemExit("无数据")

big = pd.concat(frames, ignore_index=True)
big = big[["code", "date", "open", "high", "low", "close", "volume", "amount"]]
for c in ("open", "high", "low", "close", "volume", "amount"):
    big[c] = pd.to_numeric(big[c], errors="coerce")
big = big.dropna(subset=["close"]).sort_values(["code", "date"]).reset_index(drop=True)
big.to_parquet(OUT, index=False)

print("\n写出 %s" % OUT)
print("  %d 行 × %d 只 ｜ %s ~ %s ｜ %.1f MB"
      % (len(big), big.code.nunique(), big.date.min(), big.date.max(),
         os.path.getsize(OUT) / 1024 / 1024))

# 体检：单日涨跌 >25% 的残留
r = big.groupby("code")["close"].pct_change()
ext = big[(r.abs() > 0.25)]
print("  |单日涨跌|>25%% 残留 %d 根" % len(ext))
if len(ext):
    print(ext[["code", "date", "close"]].head(12).to_string(index=False))

# 与旧库一致性：重叠日价格比值
try:
    old = pd.read_parquet("data/all_etf_1119.parquet")
    old["code"] = old["code"].astype(str)
    old["date"] = old["date"].astype(str).str[:10]
    j = big.merge(old[["code", "date", "close"]], on=["code", "date"],
                  suffixes=("_new", "_old"))
    ratio = (j["close_new"] / j["close_old"]).replace([np.inf, -np.inf], np.nan).dropna()
    print("  与 1119 重叠 %d 行 ｜ 比值中位 %.6f ｜ std %.6f ｜ >0.1%% 偏离 %d 行"
          % (len(ratio), ratio.median(), ratio.std(), int((ratio - 1).abs().gt(0.001).sum())))
    dev = j[(j["close_new"] / j["close_old"] - 1).abs() > 0.001]
    if len(dev):
        print("  偏离最大 8 行：")
        dev = dev.assign(r=dev["close_new"] / dev["close_old"] - 1)
        print(dev.reindex(dev.r.abs().sort_values(ascending=False).index)
              [["code", "date", "close_new", "close_old", "r"]].head(8).to_string(index=False))
except Exception as e:
    print("  一致性检查跳过：%r" % (e,))
