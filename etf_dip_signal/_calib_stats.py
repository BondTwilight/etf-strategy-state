# -*- coding: utf-8 -*-
"""补齐标定统计（读已存的 CSV，不再请求）"""
import pandas as pd

d = pd.read_csv("data/minute_calib.csv")
print("样本 %d 只 × %d 日 = %d" % (d.code.nunique(), d.day.nunique(), len(d)))
print()
print("%-8s %9s %9s %9s" % ("时点", "均值", "标准差", "绝对偏差90%分位"))
for k, nm in (("r45", "14:45"), ("r50", "14:50"), ("r57", "14:57")):
    x = d[k]
    print("%-8s %+8.4f%% %8.4f%% %12.4f%%"
          % (nm, x.mean() * 100, x.std() * 100, x.abs().quantile(0.9) * 100))
print()
print("相邻时点之差的标准差：")
print("  14:45 − 14:50 : %.4f%%" % ((d.r45 - d.r50).std() * 100))
print("  14:50 − 14:57 : %.4f%%" % ((d.r50 - d.r57).std() * 100))
print()
print("14:50 偏差的分布特征：")
print("  负偏差占比（14:50 价 < 收盘）: %.1f%%" % ((d.r50 < 0).mean() * 100))
print("  |偏差| > 0.5%% 的占比          : %.1f%%" % ((d.r50.abs() > 0.005).mean() * 100))
print("  |偏差| > 1.0%% 的占比          : %.1f%%" % ((d.r50.abs() > 0.01).mean() * 100))
print()
print("按标的 14:50 偏差标准差（%%）：")
print((d.groupby("code")["r50"].std() * 100).round(4).sort_values(ascending=False).to_string())
