# -*- coding: utf-8 -*-
"""解析聚宽导出的 position.csv，算净值曲线 / 回撤 / 分年收益，并与本地回测对账"""
import io

import numpy as np
import pandas as pd

P = r'C:\Users\Twilight\Desktop\巨款回测\position.csv'
raw = open(P, 'rb').read().decode('gbk', errors='replace')
lines = [l for l in raw.splitlines() if l.strip()]
hdr = lines[0].split(',')
print('列数', len(hdr), '行数', len(lines) - 1)

rows = []
for l in lines[1:]:
    parts = l.split(',')
    if len(parts) < 8:
        continue
    rows.append(parts[:len(hdr)])

df = pd.DataFrame(rows, columns=hdr[:max(len(r) for r in rows)])
print('解析后', df.shape)

# 每天的总资产 = 该日所有行（Cash + 各持仓）的「市值/价值」之和
df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
df['市值'] = pd.to_numeric(df['市值/价值'], errors='coerce')
daily = df.dropna(subset=['日期']).groupby('日期')['市值'].sum()
daily = daily[daily > 0].sort_index()
print('每日总资产序列 %d 天 ｜ 首 %.0f ｜ 末 %.0f'
      % (len(daily), daily.iloc[0], daily.iloc[-1]))

cash = pd.DataFrame({'日期': daily.index, '净值': daily.values})

if len(cash) < 10:
    print('样本太少，退出'); raise SystemExit

eq = cash.set_index('日期')['净值']
ret = eq.pct_change().fillna(0.0)
yrs = (eq.index[-1] - eq.index[0]).days / 365.25
cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
dd = (eq / eq.cummax() - 1).min()

print('\n' + '=' * 62)
print('聚宽回测结果（净值来自 position.csv）')
print('=' * 62)
print('  区间      %s ~ %s（%.2f 年）' % (eq.index[0].date(), eq.index[-1].date(), yrs))
print('  期末净值  %.4f  （初始 %.0f → %.0f）' % (eq.iloc[-1] / eq.iloc[0],
                                                 eq.iloc[0], eq.iloc[-1]))
print('  总收益    %+.2f%%' % ((eq.iloc[-1] / eq.iloc[0] - 1) * 100))
print('  年化      %+.2f%%' % (cagr * 100))
print('  最大回撤  %.2f%%' % (dd * 100))
print('  Calmar    %.2f' % (cagr / abs(dd) if dd < 0 else np.nan))
vol = ret.std() * np.sqrt(252)
print('  年化波动  %.2f%%' % (vol * 100))
print('  夏普(无风险0) %.2f' % (ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else np.nan))

print('\n【分年收益】')
by = eq.groupby(eq.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
local = {2021: -0.2288, 2022: 1.0823, 2023: 0.0326,
         2024: 0.6843, 2025: 0.4585, 2026: 0.3530}
print('  年份    聚宽      本地      差')
for y, v in by.items():
    lv = local.get(y)
    if lv is None:
        print('  %-6d %8.2f%%      -' % (y, v * 100))
    else:
        print('  %-6d %8.2f%% %8.2f%%  %+7.2fpp' % (y, v * 100, lv * 100,
                                                    (v - lv) * 100))

print('\n【回撤区间】')
peak = eq.cummax()
ddser = eq / peak - 1
tr = ddser.idxmin()
pk = eq[:tr].idxmax()
print('  峰值 %s（%.0f）→ 谷底 %s（%.0f）｜%.2f%%'
      % (pk.date(), eq[pk], tr.date(), eq[tr], ddser.min() * 100))
