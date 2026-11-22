# -*- coding: utf-8 -*-
"""消费轮动 96863：从 2026-05-28 锚点复现，定位 11 月持仓与切换"""
import os, sys
import numpy as np, pandas as pd
BASE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, BASE)
import data_quality

CODES = ['162411', '513100', '161128', '588000', '162415', '515450']
NAMES = {'162411': '油气', '513100': '纳指100', '161128': '标普信息',
         '588000': '科创50', '162415': '美国消费', '515450': '红利低波'}
START = '2026-05-28'
END = '2026-11-19'
CASH0 = 85860.0
INIT_CODE = '161128'
INIT_SHARES = 21400
COMM = 0.00025
SLIP = 0.001
MIN_HOLD = 5
MIN_RET, MAX_RET = 2.01, 9.99

df = pd.read_parquet(os.path.join(BASE, 'data', 'all_etf_1119.parquet'))
df['code'] = df['code'].astype(str)
px = {}
for c in CODES:
    s = df[df.code == c][['date', 'close']].copy()
    s['date'] = s['date'].astype(str).str[:10]
    s = s.drop_duplicates('date').reset_index(drop=True)
    s, _ = data_quality.repair_prices(s)
    s['date'] = pd.to_datetime(s['date'])
    px[c] = s.set_index('date')['close'].astype(float)
p = pd.DataFrame(px).sort_index()
p = p.loc[START:END].ffill()
r19 = (p / p.shift(19) - 1) * 100

cash = CASH0
code = INIT_CODE
shares = INIT_SHARES
buy_date = pd.Timestamp(START)
trades = []
eq = []

for i, d in enumerate(p.index):
    row = r19.loc[d]
    cand = {c: row[c] for c in CODES if pd.notna(row[c]) and MIN_RET <= row[c] <= MAX_RET}
    top = max(cand, key=cand.get) if cand else None
    held_days = len(p.loc[buy_date:d].index) - 1 if code else 0

    # 卖出：持仓已满 5 天，且（不在带内 或 有更强的候选）
    if code and held_days >= MIN_HOLD:
        if (code not in cand) or (top is not None and top != code and cand[top] > cand[code] + 0.5):
            px_sell = p.loc[d, code] * (1 - SLIP - COMM)
            cash += shares * px_sell
            trades.append((d, 'sell', code, shares, px_sell, cash))
            code, shares = None, 0

    # 买入：空仓且有候选
    if code is None and top is not None:
        px_buy = p.loc[d, top] * (1 + SLIP + COMM)
        shares = int(cash / px_buy // 100) * 100
        if shares > 0:
            cash -= shares * px_buy
            code, buy_date = top, d
            trades.append((d, 'buy', code, shares, px_buy, cash))

    mv = shares * p.loc[d, code] if code else 0
    eq.append((d, cash + mv, code, shares, cash))

print("=== 交易记录（2026-05-28 ~ 2026-11-19）===")
for t in trades:
    print("  %s %s %06d %d 份 @ %.3f，现金 %.2f" % (
        t[0].date(), "买入" if t[1] == 'buy' else "卖出", int(t[2]), t[3], t[4], t[5]))

print("\n=== 11 月逐日持仓 ===")
for d, total, c, sh, ca in eq:
    if d >= pd.Timestamp('2026-10-28'):
        print("  %s 持仓 %-6s %-8s 总资产 %.2f" % (
            d.date(), c or '现金', NAMES.get(c, ''), total))

e = pd.Series([x[1] for x in eq], index=[x[0] for x in eq])
print("\n区间收益: %+.2f%% | 最大回撤: %.2f%%" % (
    (e.iloc[-1] / e.iloc[0] - 1) * 100, ((e / e.cummax() - 1).min()) * 100))
nov = e[e.index >= '2026-11-01']
print("11月（至11-19）: %+.2f%%" % ((nov.iloc[-1] / nov.iloc[0] - 1) * 100))
