# -*- coding: utf-8 -*-
"""_probe_data.py —— 数据源一致性核查（看板「数据健康」模块的依据）

核查四件事：
  1. all_etf_1119 到底是不是前复权？（用 510880 红利ETF 2021-2026 的长序列看分红跳变）
  2. 11-20（周五）收盘价在三个源里是否一致：all_etf_1119 / kline_cache_11-20 / 腾讯 qt
  3. 515880 当前状态：收盘价 vs 止损线
  4. 全池最新数据覆盖率：多少只在 11-20 有数据
"""
import json
import os
import sys
import urllib.request

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

D = os.path.join(BASE, "data")


def say(s=""):
    print(s)


say("=" * 90)
say("数据源一致性核查")
say("=" * 90)

# ---------- 1. 复权判定 ----------
say("\n[1] all_etf_1119 是否前复权？看 510880 红利ETF 的年度最大单日跌幅")
d = pd.read_parquet(os.path.join(D, "all_etf_1119.parquet"))
d["code"] = d["code"].astype(str)
d["date"] = d["date"].astype(str).str[:10]
for code, name in [("510880", "红利ETF"), ("515880", "通信ETF"), ("510300", "沪深300")]:
    s = d[d.code == code].sort_values("date")
    if s.empty:
        say("  %s 不在 all_etf_1119" % code)
        continue
    px = s.set_index("date")["close"].astype(float)
    r = px.pct_change().dropna()
    r = r[r.index >= "2021-01-01"]
    worst = r.nsmallest(3)
    say("  %s %s：%s~%s 共 %d 行 ｜ 最大单日跌幅 %s"
        % (code, name, px.index[0], px.index[-1], len(px),
           " / ".join("%s %.2f%%" % (k, v * 100) for k, v in worst.items())))

# qfq 源对照
q = pd.read_parquet(os.path.join(D, "etf_qfq_1119.parquet"))
q["code"] = q["code"].astype(str)
q["date"] = q["date"].astype(str).str[:10]
s = q[q.code == "510880"].sort_values("date")
if not s.empty:
    px = s.set_index("date")["close"].astype(float)
    r = px.pct_change().dropna()
    r = r[r.index >= "2021-01-01"]
    say("  %s qfq_1119：最大单日跌幅 %s"
        % ("510880", " / ".join("%s %.2f%%" % (k, v * 100) for k, v in r.nsmallest(3).items())))

# ---------- 2. 11-20 收盘价三源对照 ----------
say("\n[2] 11-20 收盘价：全量库 / 当日缓存 / 腾讯 qt")
cache = pd.read_parquet(os.path.join(D, "kline_cache_cifang_2026-11-20.parquet"))
cache["code"] = cache["code"].astype(str)
cache["date"] = cache["date"].astype(str).str[:10]
c20 = cache[cache.date == "2026-11-20"].set_index("code")["close"].astype(float)
a19 = d[d.date <= "2026-11-19"].groupby("code")["close"].last().astype(float)
say("  全量库最新日 = %s，11-20 有数据的标的 = %d / 缓存 %d"
    % (d.date.max(), len(c20), c20.shape[0]))

codes = ["515880", "510300", "510500", "159915", "510880", "511880", "512800", "515020"]
req = urllib.request.Request(
    "https://qt.gtimg.cn/q=" + ",".join(
        ("sh" if c[0] in "569" else "sz") + c for c in codes),
    headers={"User-Agent": "Mozilla/5.0"})
txt = urllib.request.urlopen(req, timeout=12).read().decode("gbk", errors="ignore")
qt = {}
for line in txt.split(";"):
    if '="' not in line:
        continue
    f = line.split('="', 1)[1].rstrip('"').split("~")
    if len(f) < 6:
        continue
    qt[f[2]] = (float(f[3] or 0), f[30] if len(f) > 30 else "")

say("  %-8s %10s %10s %10s %10s" % ("code", "全量库(11-19)", "缓存(11-20)", "腾讯qt", "缓存/qt"))
for c in codes:
    say("  %-8s %12.4f %12.4f %12.4f %11s"
        % (c, a19.get(c, np.nan), c20.get(c, np.nan), qt.get(c, (np.nan,))[0],
           ("%.3f%%" % ((c20.get(c, np.nan) / qt[c][0] - 1) * 100))
           if c in qt and c in c20 and qt[c][0] else "—"))

# ---------- 3. 515880 持仓状态 ----------
say("\n[3] 515880 持仓状态（成本 0.429429，-15% 止损 = 0.365015）")
pos = json.load(open(os.path.join(D, "positions.json"), encoding="utf-8"))
for c, info in pos.items():
    cost = info["avg_cost"]
    stop = cost * 0.85
    px20 = c20.get(c, np.nan)
    say("  %s 成本 %.4f ｜ 止损 %.6f ｜ 11-19 收 %.4f ｜ 11-20 收 %.4f ｜ 浮亏 %.2f%% ｜ %s"
        % (c, cost, stop, a19.get(c, np.nan), px20, (px20 / cost - 1) * 100,
           "已跌破止损" if px20 <= stop else "未跌破，距 %.2f%%" % ((px20 / stop - 1) * 100)))

# ---------- 4. 覆盖率 ----------
say("\n[4] 11-20 覆盖率")
pool = json.load(open(os.path.join(D, "fixed_pool.json"), encoding="utf-8"))
pc = [str(x) for x in pool["codes"]]
have = [c for c in pc if c in c20.index]
say("  冻结池 %d 只，11-20 有收盘价 %d 只（%.1f%%），缺 %d 只"
    % (len(pc), len(have), 100.0 * len(have) / len(pc), len(pc) - len(have)))
miss = [c for c in pc if c not in c20.index][:10]
if miss:
    say("  缺失示例：%s" % " ".join(miss))

# ---------- 5. 11-20 当日形态 ----------
say("\n[5] 11-20 全池当日涨跌分布（缓存口径）")
prev = cache[cache.date == "2026-11-19"].set_index("code")["close"].astype(float)
both = pd.DataFrame({"p19": prev, "p20": c20}).dropna()
both = both[both.index.isin(pc)]
both["r"] = both.p20 / both.p19 - 1
say("  n=%d ｜ 中位 %+.2f%% ｜ 上涨 %d 只 / 下跌 %d 只 ｜ 跌超 3%% 的 %d 只"
    % (len(both), both.r.median() * 100, (both.r > 0).sum(), (both.r < 0).sum(),
       (both.r < -0.03).sum()))
