# -*- coding: utf-8 -*-
"""报价单位(tick)成本 / 盈亏比 / 多重检验折扣"""
import numpy as np
import pandas as pd

TR = "回测输出/trades_main_final.csv"
df = pd.read_csv(TR)
df["code"] = df["code"].astype(str).str.zfill(6)

buys = df[df["action"] == "buy"].copy()
sells = df[df["action"] == "sell"].copy()

print("=" * 78)
print("一、最小报价单位（tick）相对成本 —— ETF 为 0.001 元")
print("=" * 78)
buys["tick_pct"] = 0.001 / buys["price"] * 100
print("  建仓价分布：最低 %.3f 元 ｜ 中位 %.3f 元 ｜ 最高 %.3f 元"
      % (buys["price"].min(), buys["price"].median(), buys["price"].max()))
print("  一个 tick 的相对成本：中位 %.3f%% ｜ 最差 %.3f%%"
      % (buys["tick_pct"].median(), buys["tick_pct"].max()))
print("\n  按 tick 成本排序（越高越危险）：")
tmp = buys.groupby("code").agg(price=("price", "median"), n=("price", "size"))
tmp["tick_pct"] = 0.001 / tmp["price"] * 100
print(tmp.sort_values("tick_pct", ascending=False).head(12).to_string())
print("\n  → 现假设滑点 0.10%%/边。若实际成交要多付 1 个 tick，则：")
over = (buys["tick_pct"] > 0.10).mean() * 100
print("     有 %.0f%% 的建仓标的，单边 tick 成本已超过 0.10%%" % over)

print("\n" + "=" * 78)
print("二、最终配置下的盈亏比与期望")
print("=" * 78)
if "ret" in sells.columns and len(sells):
    r = sells["ret"].dropna()
    win = r[r > 0]
    los = r[r <= 0]
    print("  交易 %d 笔 ｜ 胜 %d ｜ 负 %d ｜ 胜率 %.1f%%"
          % (len(r), len(win), len(los), len(win) / len(r) * 100))
    aw = win.mean() if len(win) else np.nan
    al = los.mean() if len(los) else np.nan
    print("  平均盈利 %+.2f%% ｜ 平均亏损 %+.2f%% ｜ 盈亏比 %.2f:1"
          % (aw * 100, al * 100, abs(aw / al) if al else np.nan))
    p = len(win) / len(r)
    be = abs(al) / (aw + abs(al))
    print("  单笔期望 %+.2f%% ｜ 盈亏平衡胜率 %.1f%% ｜ 安全垫 %+.1fpp"
          % (r.mean() * 100, be * 100, (p - be) * 100))
    print("  最差 3 笔：", np.round(np.sort(r.values)[:3] * 100, 2))
    print("  最好 3 笔：", np.round(np.sort(r.values)[-3:] * 100, 2))
    print("\n  卖出原因分布：")
    print(sells["reason"].value_counts().to_string())
    print("\n  按原因的盈亏：")
    for k, g in sells.groupby("reason"):
        print("    %-10s %2d 笔  均值 %+6.2f%%  最差 %+6.2f%%"
              % (k, len(g), g["ret"].mean() * 100, g["ret"].min() * 100))

print("\n" + "=" * 78)
print("三、多重检验折扣（Deflated Sharpe 的简化版）")
print("=" * 78)
CAGR, DD, SR = 0.4074, -0.1838, 1.82     # 最终配置（本地口径）
T = 5.8                                  # 年
for N in (1, 5, 10, 30, 50):
    # Bailey & Lopez de Prado: 期望最大夏普 ≈ sqrt(2 ln N) * 标准差(夏普估计误差)
    # 简化：SR 估计误差 ≈ sqrt((1+SR^2/2)/T)
    se = np.sqrt((1 + SR ** 2 / 2) / T)
    e_max = np.sqrt(2 * np.log(max(N, 2))) * se
    print("  若共试 %2d 组参数 → 纯运气也可产出 SR≈%.2f ｜ 净 SR≈%.2f ｜ 折算年化≈%.1f%%"
          % (N, e_max, SR - e_max, (SR - e_max) * 0.08 * 100))
print("  注：0.08 为「夏普→年化」的粗略折算（用实测波动），仅作量级参考")
