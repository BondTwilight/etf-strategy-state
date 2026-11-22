# -*- coding: utf-8 -*-
"""聚宽实盘口径（2022-01 ~ 2026-11）交易明细深度解析。

输出：
  1. 逐笔配对（买入→卖出），收益/持有交易日/标的
  2. 分年统计：笔数、胜率、平均盈亏、当年净值变化
  3. 收益集中度：前 N 笔贡献占比、剔除最好/最差 N 笔后的结果
  4. 按标的类别（A股/跨境/红利/商品）统计
  5. 空仓期识别：连续无持仓的区间
  6. 与沪深300 的年度对比
"""
import os
import sys
import numpy as np
import pandas as pd

BASE = r'E:\workbuddy1.0\量化agent\etf_dip_signal'
sys.path.insert(0, BASE)

TX = r'C:\Users\Twilight\Desktop\无敌2\transaction.csv'
LOG = r'C:\Users\Twilight\Desktop\无敌2\log.txt'
PARQ = os.path.join(BASE, 'data', 'etf_qfq_cifang.parquet')
POOL = os.path.join(BASE, 'data', 'fixed_pool.json')


def load_trades():
    df = pd.read_csv(TX, encoding='gbk')
    df['日期'] = pd.to_datetime(df['日期'])
    # 从"标的"列抽出 6 位代码
    df['code'] = df['标的'].str.extract(r'\((\d{6})\.')[0]
    df['name'] = df['标的'].str.replace(r'\(\d{6}\.\w+\)', '', regex=True).str.strip()
    df['side'] = df['交易类型'].map({'买': 'buy', '卖': 'sell'})
    df['qty'] = df['成交数量'].str.replace('股', '', regex=False).astype(float).abs()
    df['px'] = df['成交价'].astype(float)
    df['pnl'] = df['平仓盈亏'].astype(float)
    df['fee'] = df['手续费'].astype(float)
    return df.sort_values(['日期', '委托时间']).reset_index(drop=True)


def pair(b):
    """按时间顺序把 买→卖 配对（同一标的先进先出）。"""
    open_lots = {}
    out = []
    for _, r in b.iterrows():
        if r['side'] == 'buy':
            open_lots.setdefault(r['code'], []).append(r)
        else:
            lots = open_lots.get(r['code'], [])
            if not lots:
                continue
            bb = lots.pop(0)
            out.append({
                'code': r['code'], 'name': r['name'],
                'entry': bb['日期'], 'exit': r['日期'],
                'buy_px': bb['px'], 'sell_px': r['px'],
                'qty': bb['qty'],
                'ret': r['pnl'] / (bb['px'] * bb['qty']),
                'pnl': r['pnl'],
                'fee': bb['fee'] + r['fee'],
                'days': (r['日期'] - bb['日期']).days,
            })
    return pd.DataFrame(out)


def main():
    tr = load_trades()
    p = pair(tr)
    print('=' * 100)
    print('【1】总体（41 笔配对）')
    print('=' * 100)
    print('  笔数 %d ｜ 胜 %d ｜ 负 %d ｜ 胜率 %.1f%%'
          % (len(p), (p['ret'] > 0).sum(), (p['ret'] <= 0).sum(),
             100.0 * (p['ret'] > 0).mean()))
    print('  平均收益 %+.2f%% ｜ 中位 %+.2f%% ｜ 最好 %+.2f%% ｜ 最差 %+.2f%%'
          % (p['ret'].mean() * 100, p['ret'].median() * 100,
             p['ret'].max() * 100, p['ret'].min() * 100))
    win = p[p['ret'] > 0]['ret']; los = p[p['ret'] <= 0]['ret']
    print('  平均盈利 %+.2f%%（%d 笔）｜ 平均亏损 %+.2f%%（%d 笔）｜ 盈亏比 %.2f : 1'
          % (win.mean() * 100, len(win), los.mean() * 100, len(los),
             abs(win.mean() / los.mean()) if len(los) else float('nan')))
    print('  单笔期望 %+.2f%% ｜ 持有天数 中位 %.0f / 均值 %.1f / 最长 %d'
          % (p['ret'].mean() * 100, p['days'].median(), p['days'].mean(), p['days'].max()))
    print('  累计毛利 %.0f 元 ｜ 累计手续费 %.0f 元 ｜ 费用占毛利 %.1f%%'
          % (p['pnl'].sum(), p['fee'].sum(),
             100.0 * p['fee'].sum() / p['pnl'].sum() if p['pnl'].sum() else 0))
    print()

    # 逐笔
    print('=' * 100)
    print('【2】逐笔明细')
    print('=' * 100)
    print('%-4s %-11s %-11s %-20s %8s %8s %8s %6s %9s'
          % ('#', '买入', '卖出', '标的', '买价', '卖价', '收益', '天数', '盈亏(元)'))
    for i, r in p.sort_values('entry').reset_index(drop=True).iterrows():
        print('%-4d %-11s %-11s %-20s %8.4f %8.4f %+7.2f%% %6d %+9.0f'
              % (i + 1, r['entry'].date(), r['exit'].date(), str(r['name'])[:18],
                 r['buy_px'], r['sell_px'], r['ret'] * 100, r['days'], r['pnl']))
    print()

    # 分年
    print('=' * 100)
    print('【3】分年统计')
    print('=' * 100)
    p['year'] = p['entry'].dt.year
    print('%-6s %5s %5s %7s %9s %9s %9s %9s'
          % ('年份', '笔数', '胜', '胜率', '平均收益', '合计盈亏', '最好', '最差'))
    for y, g in p.groupby('year'):
        print('%-6d %5d %5d %6.0f%% %+8.2f%% %+9.0f %+8.2f%% %+8.2f%%'
              % (y, len(g), (g['ret'] > 0).sum(), 100.0 * (g['ret'] > 0).mean(),
                 g['ret'].mean() * 100, g['pnl'].sum(),
                 g['ret'].max() * 100, g['ret'].min() * 100))
    print()

    # 净值节点（从日志抓）
    print('=' * 100)
    print('【4】净值节点（从聚宽日志解析）')
    print('=' * 100)
    import re
    s = open(LOG, 'rb').read().decode('gbk', 'replace')
    recs = []
    for l in s.splitlines():
        m = re.search(r'^(\d{4}-\d{2}-\d{2}) .*\[进度\] 净值 ([\d.]+) 持仓 (\d+)', l)
        if m:
            recs.append((m.group(1), float(m.group(2)), int(m.group(3))))
    if recs:
        eq = pd.DataFrame(recs, columns=['date', 'nav', 'hold'])
        eq['date'] = pd.to_datetime(eq['date'])
        eq = eq.sort_values('date')
        print('  日志采样 %d 个点（每 20 个交易日）｜ 期末净值 %.4f'
              % (len(eq), eq['nav'].iloc[-1]))
        # 年末净值
        print()
        print('  %-8s %10s %10s %10s' % ('年末', '净值', '年收益', '当年笔数'))
        prev = 1.0
        for y in range(2022, 2027):
            sub = eq[eq['date'].dt.year == y]
            if len(sub) == 0:
                continue
            last = sub['nav'].iloc[-1]
            nb = len(p[p['year'] == y])
            print('  %-8d %10.4f %+9.2f%% %10d'
                  % (y, last, (last / prev - 1) * 100, nb))
            prev = last
        # 空仓期
        print()
        print('  空仓区间（持仓=0 连续 >= 60 个交易日 ≈ 3 个月）:')
        runs = []
        cur = None
        for _, r in eq.iterrows():
            if r['hold'] == 0:
                if cur is None:
                    cur = [r['date'], r['date']]
                else:
                    cur[1] = r['date']
            else:
                if cur:
                    runs.append(cur); cur = None
        if cur:
            runs.append(cur)
        for a, b2 in runs:
            d = (b2 - a).days
            if d >= 60:
                print('    %s ~ %s（%d 天 ≈ %.1f 个月）'
                      % (a.date(), b2.date(), d, d / 30.0))
    print()

    # 收益集中度
    print('=' * 100)
    print('【5】收益集中度（判断是否靠少数几笔）')
    print('=' * 100)
    q = p.sort_values('ret', ascending=False)
    tot = p['pnl'].sum()
    for n in (1, 3, 5, 10):
        top = q.head(n)['pnl'].sum()
        print('  最好 %2d 笔合计 %+8.0f 元，占全部毛利 %.0f%%' % (n, top, 100.0 * top / tot))
    print()
    for n in (1, 3, 5):
        rest = q.iloc[n:]
        print('  剔除最好 %d 笔后：剩余 %d 笔，合计 %+8.0f 元，平均 %+.2f%%'
              % (n, len(rest), rest['pnl'].sum(), rest['ret'].mean() * 100))
    print()
    # 复利口径：剔除最好 N 笔
    for n in (1, 3, 5):
        rest = q.iloc[n:]
        comp = float(np.prod(1 + rest['ret'].values) - 1)
        print('  剔除最好 %d 笔后按单笔复利累计：%+.1f%%（原 %+.1f%%）'
              % (n, comp * 100, (np.prod(1 + p['ret'].values) - 1) * 100))

    p.to_csv(os.path.join(BASE, '回测输出', 'jq_trades_2022_2026.csv'),
             index=False, encoding='utf-8-sig')
    print()
    print('已写出 回测输出/jq_trades_2022_2026.csv')


if __name__ == '__main__':
    main()
