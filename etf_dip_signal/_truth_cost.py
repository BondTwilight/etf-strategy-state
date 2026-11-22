# -*- coding: utf-8 -*-
"""① 用不复权真实价重算 tick 成本 ② 检验「移动止盈」是否等价于「把止损收到 -8%」"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_etf_dip as bt1
import bt_multi as bt
import cifang_api
import data_quality

tr = pd.read_csv("回测输出/trades_main_final.csv")
tr["code"] = tr["code"].astype(str).str.zfill(6)
buys = tr[tr["action"] == "buy"].copy()
codes = sorted(buys["code"].unique())
print("建仓 %d 笔，涉及 %d 只标的" % (len(buys), len(codes)))

# ---------- 不复权真实价 ----------
raw = cifang_api.hist_em(codes, "2020-06-01", "2026-10-22", adjust="none")
print("不复权取到 %d/%d 只" % (len(raw), len(codes)))
real = {}
for c, df in raw.items():
    real[c] = dict(zip(df["date"].astype(str).str[:10], df["close"]))

rows = []
for r in buys.itertuples():
    d = str(r.date)[:10]
    p = real.get(r.code, {}).get(d)
    if p is None or p <= 0:
        continue
    rows.append((d, r.code, float(p), 0.001 / float(p) * 100))
tk = pd.DataFrame(rows, columns=["date", "code", "real_px", "tick_pct"])
print("\n可算 tick 的建仓 %d 笔" % len(tk))
print("真实成交价：最低 %.3f ｜ 中位 %.3f ｜ 最高 %.3f"
      % (tk["real_px"].min(), tk["real_px"].median(), tk["real_px"].max()))
print("一个 tick 的相对成本：中位 %.3f%% ｜ 均值 %.3f%% ｜ 最大 %.3f%%"
      % (tk["tick_pct"].median(), tk["tick_pct"].mean(), tk["tick_pct"].max()))
print("单边 tick 成本 > 0.10%% 的建仓占比：%.0f%%" % ((tk["tick_pct"] > 0.10).mean() * 100))
print("单边 tick 成本 > 0.20%% 的建仓占比：%.0f%%" % ((tk["tick_pct"] > 0.20).mean() * 100))
print("\n最贵 8 笔：")
print(tk.nlargest(8, "tick_pct").to_string(index=False))
print("\n【结论】若只能按对手价成交，最低滑点 ≈ 半个 tick：")
print("  中位 %.3f%%/边 → 往返 %.3f%%，对应回测中「滑点 %.3f%%」的情形"
      % (tk["tick_pct"].median() / 2, tk["tick_pct"].median(),
         tk["tick_pct"].median() / 2 / 100))

# ---------- 止损位扫描 ----------
print("\n" + "=" * 92)
print("止损位扫描（关闭移动止盈/保本，仅改 STOP_LOSS）——检验「移动止盈8%」是否只是收紧止损")
print("=" * 92)
d = json.load(open("data/fixed_pool.json", encoding="utf-8"))
POOL, BMAP = d["codes"], {str(k): int(v) for k, v in d["bmap"].items()}
hist = cifang_api.fetch_pool_history(POOL, cache_path="data/etf_qfq_cifang.parquet")
hist, _ = data_quality.audit(hist, verbose=False)
m = bt1.build_matrices(hist, start="2021-01-01", end="2026-10-20")


def show(name, **kw):
    r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode="close",
               timeout_live=True, **kw)
    p = bt1.perf(r["equity"], r["trades"], 100000.0, r["exposure"])
    wr = p["win_rate"] * 100 if np.isfinite(p["win_rate"]) else float("nan")
    print("  %-30s %8.2f%% %8.2f%% %7.2f %7.2f %7.1f%% %5d"
          % (name, p["cagr"] * 100, p["max_dd"] * 100, p["calmar"],
             p["sharpe"], wr, p["trades"]))
    return p


print("  %-30s %9s %9s %8s %8s %8s %5s" % ("", "年化", "回撤", "Calmar", "夏普", "胜率", "交易"))
show("现状 stop=-15% 无保护", stop_loss=0.15)
for sl in [0.06, 0.08, 0.10, 0.12]:
    show("纯止损 stop=-%.0f%%" % (sl * 100), stop_loss=sl)
print("  ---- 参考：带移动止盈/保本 ----")
show("trail8 + be3（当前线上）", stop_loss=0.15, trail=0.08, be_stop=0.03)
show("stop=-8% + be3", stop_loss=0.08, be_stop=0.03)
show("stop=-8% + be3 + 计息", stop_loss=0.08, be_stop=0.03, cash_yield=0.025)
