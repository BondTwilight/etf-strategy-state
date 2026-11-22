# -*- coding: utf-8 -*-
"""聚宽 position.csv 精确解析（表头缺一列「市值」）"""
import csv
import io

import numpy as np
import pandas as pd

POS = r"C:\Users\Twilight\Desktop\巨款回测\position.csv"
txt = open(POS, "rb").read().decode("gbk", errors="replace")
rd = list(csv.reader(io.StringIO(txt)))
hdr = [h.strip().lstrip("\ufeff") for h in rd[0]] + ["市值2"]
print("表头补齐后 %d 列: %s" % (len(hdr), hdr))

recs = []
for r in rd[1:]:
    if len(r) == 16:
        r = r + [""]
    if len(r) < 17:
        continue
    recs.append(r[:17])
df = pd.DataFrame(recs, columns=hdr)

for c in ["数量", "收盘价/结算价", "市值/价值", "盈亏/逐笔浮盈", "开仓均价"]:
    df[c] = pd.to_numeric(df[c].astype(str).str.replace("股", "").str.replace(",", ""),
                          errors="coerce")
df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
df = df.dropna(subset=["日期"]).sort_values("日期")

daily = df.groupby("日期")["市值/价值"].sum().sort_index()
eq = daily[daily > 0]
print("\n每日总资产 %d 天 ｜ %s %.0f → %s %.0f"
      % (len(eq), eq.index[0].date(), eq.iloc[0], eq.index[-1].date(), eq.iloc[-1]))

hold = df[df["标的"].astype(str).str.contains(r"\.XSHG|\.XSHE|\.SH|\.SZ", na=False)]
print("持仓行 %d" % len(hold))

print("\n=== 聚宽逐笔持仓（按建仓日）===")
print("%-24s %-11s %-11s %5s %9s %9s %9s"
      % ("标的", "首日", "末日", "天", "开仓均价", "末价", "末市值"))
rows = []
for code, g in hold.groupby("标的"):
    g = g.sort_values("日期")
    op = g["开仓均价"].dropna()
    rows.append((code, g["日期"].iloc[0].date(), g["日期"].iloc[-1].date(), len(g),
                 op.iloc[0] if len(op) else np.nan,
                 g["收盘价/结算价"].iloc[-1], g["市值/价值"].iloc[-1]))
for r in sorted(rows, key=lambda x: x[1]):
    print("%-24s %-11s %-11s %5d %9.4f %9.4f %9.0f" % r)

print("\n=== 512690 逐日 ===")
s = df[df["标的"].astype(str).str.contains("512690", na=False)]
print(s[["日期", "数量", "收盘价/结算价", "市值/价值", "盈亏/逐笔浮盈", "开仓均价"]].to_string())

print("\n=== 净值跌破 0.99 的日期 ===")
print(eq[eq < 99000].head(12).to_string())

# 保存供后续用
eq.rename("nav").to_csv("_jq_equity.csv", encoding="utf-8-sig")
print("\n已保存 _jq_equity.csv")
