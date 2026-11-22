# -*- coding: utf-8 -*-
"""聚宽 vs 本地：逐笔对账（聚宽交易从 position.csv 还原）

聚宽 MAX_HOLD=1，任一时刻最多 1 个持仓，因此：
  持仓区间 = 该标的连续出现「数量>0」的交易日
  退出日   = 区间结束后第一个交易日
  退出金额 = cash(退出日) - cash(末日) + (若退出日同时买入新标的) 新标的成本
  退出价   = 退出金额 / 数量
"""
import csv
import io

import numpy as np
import pandas as pd

POS = r"C:\Users\Twilight\Desktop\巨款回测\position.csv"
LOCAL = "回测输出/trades_main_final.csv"

txt = open(POS, "rb").read().decode("gbk", errors="replace")
rd = list(csv.reader(io.StringIO(txt)))
hdr = [h.strip().lstrip("\ufeff") for h in rd[0]] + ["_x"]

recs = []
for r in rd[1:]:
    if len(r) == 16:
        r = r + [""]
    if len(r) < 17:
        continue
    recs.append(r[:17])
df = pd.DataFrame(recs, columns=hdr)
df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
df = df.dropna(subset=["日期"]).sort_values("日期")


def num(s):
    return pd.to_numeric(
        s.astype(str).str.replace("股", "").str.replace(",", "").str.replace("%", ""),
        errors="coerce")


df["qty"] = num(df["数量"])
df["px"] = num(df["收盘价/结算价"])
df["val"] = num(df["市值/价值"])
df["cost"] = num(df["开仓均价"])

dates = sorted(df["日期"].unique())
cash = df[df["标的"].astype(str).str.strip() == "Cash"].set_index("日期")["val"]
cash = cash.reindex(dates).ffill()
hold = df[df["标的"].astype(str).str.contains(r"\.XSHG|\.XSHE", na=False)].copy()
hold["six"] = hold["标的"].str.extract(r"\((\d{6})\.")

# --- 持仓 episode ---
eps = []
for six, g in hold.groupby("six"):
    g = g.sort_values("日期").reset_index(drop=True)
    blocks, cur = [], [0]
    for i in range(1, len(g)):
        if g.loc[i, "日期"] == g.loc[i - 1, "日期"]:
            continue
        gap = dates.index(g.loc[i, "日期"]) - dates.index(g.loc[i - 1, "日期"])
        if gap <= 3:          # 中间只有非交易日间隔
            cur.append(i)
        else:
            blocks.append(cur)
            cur = [i]
    blocks.append(cur)
    for b in blocks:
        sub = g.loc[b]
        eps.append({
            "code": six, "name": sub["标的"].iloc[0],
            "entry": sub["日期"].iloc[0], "last": sub["日期"].iloc[-1],
            "days": len(sub), "qty": sub["qty"].iloc[0],
            "cost": sub["cost"].dropna().iloc[0] if sub["cost"].notna().any() else np.nan,
        })

eps = pd.DataFrame(eps).sort_values("entry").reset_index(drop=True)

# --- 退出价 ---
rows = []
for _, e in eps.iterrows():
    i_last = dates.index(e["last"])
    if i_last + 1 >= len(dates):
        exit_d, exit_px, ret = pd.NaT, np.nan, np.nan
    else:
        exit_d = dates[i_last + 1]
        proceeds = cash.loc[exit_d] - cash.loc[e["last"]]
        # 若退出日同时买入新标的，补回新标的成本
        newp = hold[(hold["日期"] == exit_d) & (hold["six"] != e["code"])]
        if len(newp):
            proceeds += float(newp["qty"].iloc[0]) * float(newp["cost"].dropna().iloc[0])
        exit_px = proceeds / e["qty"] if e["qty"] else np.nan
        ret = exit_px / e["cost"] - 1 if e["cost"] else np.nan
    rows.append(dict(e, exit=exit_d, exit_px=exit_px, ret=ret))
jq = pd.DataFrame(rows)

print("=== 聚宽还原出 %d 笔交易 ===" % len(jq))
print("%-8s %-11s %-11s %4s %10s %10s %8s  %s"
      % ("代码", "建仓", "平仓", "天", "成本", "平仓价", "收益", "名称"))
for r in jq.itertuples():
    print("%-8s %-11s %-11s %4d %10.4f %10.4f %+7.2f%%  %s"
          % (r.code, str(r.entry)[:10], str(r.exit)[:10], r.days, r.cost, r.exit_px,
             r.ret * 100, r.name))

# --- 本地：按顺序配对 buy→sell ---
lt = pd.read_csv(LOCAL)
lt["date"] = pd.to_datetime(lt["date"])
lt["code"] = lt["code"].astype(str).str.zfill(6)
open_pos, recs_l = {}, []
for r in lt.itertuples():
    if r.action == "buy":
        open_pos[r.code] = r
    elif r.action == "sell" and r.code in open_pos:
        b = open_pos.pop(r.code)
        recs_l.append({"code": r.code, "entry": b.date, "bpx": b.price,
                       "exit": r.date, "ret": r.ret, "reason": r.reason,
                       "days": np.nan})
loc = pd.DataFrame(recs_l)
for i, r in loc.iterrows():
    td = np.busday_count(r["entry"].date(), r["exit"].date())
    loc.at[i, "days"] = td

print("\n=== 本地 %d 笔 ===" % len(loc))
for r in loc.itertuples():
    print("%-8s %-11s %-11s %+7.2f%%  %s"
          % (r.code, str(r.entry)[:10], str(r.exit)[:10], r.ret * 100, r.reason))

# --- 对齐：同代码、建仓日相差 ≤5 个交易日 ---
print("\n=== 对齐结果 ===")
used = set()
pairs = []
for i, r in jq.iterrows():
    cand = loc[(loc["code"] == r["code"])].copy()
    if len(cand):
        cand["dd"] = (cand["entry"] - r["entry"]).dt.days.abs()
        cand = cand.sort_values("dd")
        for k, c in cand.iterrows():
            if k in used:
                continue
            if c["dd"] <= 10:
                used.add(k)
                pairs.append((r["code"], r["entry"], r["ret"], c["entry"], c["ret"],
                              r["days"], r["exit"], c["exit"]))
            break

print("%-8s %-11s %9s | %-11s %9s | %8s  %s"
      % ("代码", "聚宽建仓", "聚宽收益", "本地建仓", "本地收益", "收益差", "天数/平仓"))
for p in pairs:
    print("%-8s %-11s %+8.2f%% | %-11s %+8.2f%% | %+7.2fpp  %s→%s / %s→%s"
          % (p[0], str(p[1])[:10], p[2] * 100, str(p[3])[:10], p[4] * 100,
             (p[2] - p[4]) * 100, "", str(p[6])[:10], "", str(p[7])[:10]))

print("\n聚宽交易数 %d ｜ 本地 %d ｜ 能对上 %d ｜ 聚宽独有 %d ｜ 本地独有 %d"
      % (len(jq), len(loc), len(pairs), len(jq) - len(pairs), len(loc) - len(used)))

if pairs:
    d = np.array([p[2] - p[4] for p in pairs])
    print("同一笔的收益差：均值 %+.2fpp ｜ 中位 %+.2fpp ｜ 最大 %+.2fpp ｜ 同向 %d/%d"
          % (d.mean() * 100, np.median(d) * 100, np.abs(d).max() * 100,
             int((np.sign(d) == np.sign(d.mean())).sum()) if len(d) else 0, len(d)))
