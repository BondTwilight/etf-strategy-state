# -*- coding: utf-8 -*-
"""止损反杀检验 v2 —— 修正配对 + 数据清洗。

v1 的三个错误：
  ① 配对用全局单变量，同日先卖后买会串号（159967 被配到 2025-04-09）
  ② 未清洗，159792/518600 出现 +80%/+469% 的复权跳变假值
  ③ 用「卖出价」做基准，混入了卖出当日与收盘的差异

v2 改为：按标的 FIFO 配对；用 data_quality 修跳变；以「卖出日收盘」为基准，
并检测卖出后 10 日内是否出现 >25% 单日跳变，有则标记不可信。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import cifang_api as cf
import data_quality

JQ_DIR = r'C:\Users\Twilight\Desktop\无敌2'
JUMP = 0.25          # 单日 >25% 视为复权跳变


def load_trades():
    df = pd.read_csv(os.path.join(JQ_DIR, 'transaction.csv'), encoding='gbk')
    df['日期'] = pd.to_datetime(df['日期'])
    df['side'] = df['交易类型'].map({'买': 'buy', '卖': 'sell'})
    df['code'] = df['标的'].str.extract(r'\((\d{6})\.')[0]
    df['price'] = pd.to_numeric(df['成交价'], errors='coerce')
    df['qty'] = pd.to_numeric(df['成交数量'].str.replace('股', '', regex=False),
                              errors='coerce').abs()
    return df.sort_values(['日期', '委托时间']).reset_index(drop=True)


def pair_fifo(df):
    """按标的各自维护 FIFO 队列，避免串号。"""
    book = {}       # code -> list of buy dict
    out = []
    for _, r in df.iterrows():
        c = r['code']
        if not isinstance(c, str):
            continue
        if r['side'] == 'buy':
            book.setdefault(c, []).append({
                'code': c, 'entry': r['日期'], 'entry_px': r['price'], 'qty': r['qty'],
            })
        else:
            q = book.get(c, [])
            if not q:
                continue
            b = q.pop(0)
            out.append({
                'code': c,
                'entry': b['entry'], 'entry_px': b['entry_px'],
                'exit': r['日期'], 'exit_px': r['price'],
                'qty': b['qty'] if pd.notna(b['qty']) else r['qty'],
                'ret': (r['price'] / b['entry_px'] - 1) * 100,
            })
    return pd.DataFrame(out)


def clean_hist(hist):
    """对每只做跳变修复，返回 {code: DataFrame(date, close)}。"""
    out = {}
    for c, g in hist.items():
        g = g.sort_values('date').reset_index(drop=True)
        if len(g) < 3:
            continue
        fixed, hits = data_quality.repair_prices(g[[ 'date', 'close']].copy(),
                                                 jump_th=JUMP)
        fixed['date'] = fixed['date'].astype(str)
        out[c] = fixed
        if hits:
            print('    [清洗] %s 修复 %d 处跳变' % (c, len(hits)))
    return out


def main():
    tr = load_trades()
    pos = pair_fifo(tr)
    print('FIFO 配对：%d 笔（买入 %d / 卖出 %d）'
          % (len(pos), (tr['side'] == 'buy').sum(), (tr['side'] == 'sell').sum()))
    print()

    start = (pos['exit'].min() - pd.Timedelta(days=5)).strftime('%Y-%m-%d')
    end = '2026-11-04'
    codes = sorted(set(pos['code']))
    hist = cf.fetch_pool_history(codes, start, end, force=True)
    print('拉到 %d/%d 只' % (len(hist), len(codes)))
    print()
    series = clean_hist(hist)

    losses = pos[pos['ret'] < 0].sort_values('exit')
    print('=' * 100)
    print('【一】全部亏损卖出（基准 = 卖出日收盘，避开卖出价与收盘的差异）')
    print('=' * 100)
    print('%-12s %-8s %8s %9s | %8s %8s %8s %8s  %s'
          % ('卖出日', '标的', '当日收盘', '这笔收益', 'T+1', 'T+3', 'T+5', 'T+10', '数据可信'))
    rows = []
    for _, r in losses.iterrows():
        c = r['code']
        if c not in series:
            continue
        g = series[c]
        dates = list(g['date'])
        closes = g['close'].to_numpy(float)
        ex = r['exit'].strftime('%Y-%m-%d')
        idx = None
        for k in range(len(dates) - 1, -1, -1):
            if dates[k] <= ex:
                idx = k
                break
        if idx is None:
            continue
        base = closes[idx]
        # 检测卖出后 10 日内是否有跳变
        seg = closes[idx: idx + 11]
        bad = False
        if len(seg) >= 2:
            rr = seg[1:] / seg[:-1]
            bad = bool(np.any(np.abs(rr - 1) > JUMP))
        vals = []
        for lag in (1, 3, 5, 10):
            j = idx + lag
            vals.append((closes[j] / base - 1) * 100 if j < len(closes) else np.nan)
        print('%-12s %-8s %8.4f %+8.2f%% | %+7.2f%% %+7.2f%% %+7.2f%% %+7.2f%%  %s'
              % (ex, c, base, r['ret'], vals[0], vals[1], vals[2], vals[3],
                 '✗ 有跳变' if bad else '✓'))
        if not bad:
            rows.append({'code': c, 'exit': ex, 'entry': r['entry'].strftime('%Y-%m-%d'),
                         'ret': r['ret'], 't1': vals[0], 't3': vals[1],
                         't5': vals[2], 't10': vals[3]})

    rb = pd.DataFrame(rows)
    print('-' * 100)
    print('可信样本 %d 笔（已剔除跳变）：' % len(rb))
    for col, nm in (('t1', 'T+1'), ('t3', 'T+3'), ('t5', 'T+5'), ('t10', 'T+10')):
        s = rb[col].dropna()
        if len(s):
            print('  %-4s 均值 %+6.2f%%  中位 %+6.2f%%  正收益 %d/%d  区间 [%+.2f%%, %+.2f%%]'
                  % (nm, s.mean(), s.median(), (s > 0).sum(), len(s), s.min(), s.max()))
    for th in (3, 5):
        s = rb['t5'].dropna()
        print('  ★ T+5 反弹 > +%d%% 的：%d/%d 笔（%.0f%%）'
              % (th, (s > th).sum(), len(s), (s > th).mean() * 100 if len(s) else 0))

    print()
    print('=' * 100)
    print('【二】11-03 → 11-04 到底发生了什么')
    print('=' * 100)
    for code, nm, sell_px in (('588170', '科创半导体ETF华夏', 0.583),
                              ('159967', '创业板成长ETF华夏', 0.524)):
        if code not in series:
            continue
        g = series[code]
        rel = g[g['date'] >= '2026-10-26']
        print()
        print('  %s %s（聚宽卖出价 %.4f）' % (code, nm, sell_px))
        for _, r2 in rel.iterrows():
            mark = ''
            if r2['date'] == '2026-11-03':
                mark = '  ← 聚宽卖出日'
            if r2['date'] == '2026-11-04':
                mark = '  ← 今天'
            print('    %s  %.4f%s' % (r2['date'], r2['close'], mark))
        last = g['close'].iloc[-1]
        print('    ⇒ 从卖出价 %.4f 到今天 %.4f：%+.2f%%'
              % (sell_px, last, (last / sell_px - 1) * 100))

    if len(rb):
        p = os.path.join(BASE, '回测输出', 'stop_loss_rebound.csv')
        os.makedirs(os.path.dirname(p), exist_ok=True)
        rb.to_csv(p, index=False, encoding='utf-8-sig')
        print()
        print('已写出 回测输出/stop_loss_rebound.csv')


if __name__ == '__main__':
    main()
