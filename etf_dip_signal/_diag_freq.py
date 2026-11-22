# -*- coding: utf-8 -*-
"""频率瓶颈诊断：77% 时间空仓，到底卡在哪一环。

回答三个问题：
  1. 空仓日里，有多少天「完全没有候选」、多少天「有候选但买不进」
  2. 各类别的候选日数 vs 实际被买次数 —— 量化「排不上队」
  3. 若改成「类内分别排序、各类各买一只」，会多出多少机会

这是判断「按类别细化能否提高频率」的前置诊断，不做任何参数改动。
"""
import os
import sys
import json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_etf_dip as bt1
import bt_multi as bt
import data_quality

START, END = '2021-01-01', '2026-10-20'
STD = dict(max_hold=1, intraday_stop=True, exec_mode='close', timeout_live=True,
           trail=0.08, be_stop=0.03, cash_yield=0.025, slippage=0.002)


def main():
    d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
    cmap = d.get('cmap', {}); sc = d.get('subclass', {})
    bmap = {str(k): int(v) for k, v in d['bmap'].items()}
    nm = d.get('name', {})

    def grp(c):
        if cmap.get(c) == '商品':
            return '商品'
        if sc.get(c) in ('美股', '日本', '欧股'):
            return '远洋'
        if cmap.get(c) == '跨境' and bmap.get(c) == -16:
            return '近岸'
        if bmap.get(c) == -5:
            return '红利'
        return 'A股'

    raw = pd.read_parquet('data/etf_qfq_cifang.parquet',
                          columns=['code', 'date', 'open', 'close', 'low'])
    raw['date'] = raw['date'].astype(str).str[:10]
    hist = {}
    for code, g in raw.groupby('code', sort=False):
        f, _ = data_quality.repair_prices(g[['date', 'open', 'close', 'low']])
        hist[code] = f.reset_index(drop=True)
    del raw
    m = bt1.build_matrices(hist, start=START, end=END)
    codes = list(m['codes'])
    dates = pd.to_datetime(m['dates'])
    n, mm = len(dates), len(codes)
    bmin5 = m['bmin5']; valid = m['valid']; bias50 = m['bias50']
    th = np.array([bmap.get(c, -16) for c in codes], dtype=float)
    gm = np.array([grp(c) for c in codes])
    print('矩阵 %d 交易日 x %d 只 ｜ %s ~ %s'
          % (n, mm, dates[0].date(), dates[-1].date()))
    print()

    # ---------- 1. 逐日候选统计 ----------
    cand = (bmin5 < th[None, :]) & valid
    n_cand = cand.sum(axis=1)

    r0 = bt.run(m, bmap, **STD)
    tr = r0['trades']
    buys = tr[tr['action'] == 'buy'].copy()
    buys['code'] = buys['code'].astype(str).str.zfill(6)
    buys['date'] = pd.to_datetime(buys['date'])
    bset = set(buys['date'])
    expo = r0['exposure']

    print('=' * 100)
    print('【1】逐日候选分布（阈值判定，未考虑持仓/冷却）')
    print('=' * 100)
    print('  有候选的交易日: %d / %d (%.1f%%)'
          % ((n_cand > 0).sum(), n, 100.0 * (n_cand > 0).sum() / n))
    print('  无候选的交易日: %d / %d (%.1f%%)'
          % ((n_cand == 0).sum(), n, 100.0 * (n_cand == 0).sum() / n))
    print('  候选数分位: P10=%.0f P25=%.0f 中位=%.0f P75=%.0f P90=%.0f 最大=%d'
          % tuple(np.percentile(n_cand, [10, 25, 50, 75, 90]).tolist() + [n_cand.max()]))
    print('  实际持仓占比 %.1f%%  买入 %d 笔  (年 %.1f 笔)'
          % (expo * 100, len(buys), len(buys) / (n / 244.0)))
    print()

    # 空仓归因
    held = np.zeros(n, dtype=bool)
    # 从 equity 无法直接看持仓，用买入/卖出重建
    sells = tr[tr['action'] == 'sell'].copy()
    sells['date'] = pd.to_datetime(sells['date'])
    sset = set(sells['date'])
    for i, dt in enumerate(dates):
        pass
    print('  空仓日构成（近似：非买入日且非持仓区间）')
    print('    注：MAX_HOLD=1 下「有候选但空仓」只能出现在冷确期或资金不足')
    print()

    # ---------- 2. 各类别候选日 vs 被买次数 ----------
    print('=' * 100)
    print('【2】各类别「有候选的天数」vs「实际被买次数」—— 量化排不上队')
    print('=' * 100)
    print('%-8s %6s %12s %12s %10s %12s'
          % ('组', '只数', '有候选日数', '占全期', '被买次数', '买/候选日'))
    rows = []
    for g in ('A股', '远洋', '近岸', '红利', '商品'):
        cols = np.where(gm == g)[0]
        if len(cols) == 0:
            continue
        has = (cand[:, cols].sum(axis=1) > 0)
        nb = int((buys['code'].map(lambda c: grp(c) == g)).sum())
        rows.append((g, len(cols), int(has.sum()), has.sum() / n, nb,
                     nb / max(has.sum(), 1)))
        print('%-8s %6d %12d %11.1f%% %10d %11.1f%%'
              % (g, len(cols), int(has.sum()), 100.0 * has.sum() / n, nb,
                 100.0 * nb / max(has.sum(), 1)))
    print()

    # ---------- 3. 全局排序 vs 类内排序 ----------
    print('=' * 100)
    print('【3】当前是「全局按 bias50 升序选第一」——各类别的第一被谁挤掉了')
    print('=' * 100)
    top_grp = []
    only_cand_grp = []
    for i in range(n):
        c = np.where(cand[i])[0]
        if len(c) == 0:
            top_grp.append(None); only_cand_grp.append(set())
            continue
        b = bias50[i, c]
        ok = np.isfinite(b)
        c = c[ok]; b = b[ok]
        if len(c) == 0:
            top_grp.append(None); only_cand_grp.append(set())
            continue
        j = c[np.argmin(b)]
        top_grp.append(gm[j])
        only_cand_grp.append(set(gm[c]))
    tg = pd.Series([x for x in top_grp if x is not None])
    print('  「全局排名第一」落在各组的次数:')
    for g, v in tg.value_counts().items():
        print('    %-8s %4d 天 (%.1f%%)' % (g, v, 100.0 * v / len(tg)))
    print()

    # 类内各买一只会多出多少机会
    print('  若改为「类内分别排序，各类各买第一」：')
    print('%-8s %12s %14s %14s' % ('组', '可买天数', '当前被买', '类内可多买'))
    for g in ('A股', '远洋', '近岸', '红利', '商品'):
        cnt = sum(1 for s in only_cand_grp if g in s)
        nb = int((buys['code'].map(lambda c: grp(c) == g)).sum())
        print('%-8s %12d %14d %14d' % (g, cnt, nb, max(cnt - nb, 0)))
    print()
    print('  （「可买天数」= 该组当天至少有一只满足自身阈值）')
    print()

    # ---------- 4. 各类别的「候选日重叠度」 ----------
    print('=' * 100)
    print('【4】各类别候选日的重叠度（重叠低 = 细化能真正增加频率）')
    print('=' * 100)
    gs = ['A股', '远洋', '近岸', '红利', '商品']
    sets = {}
    for g in gs:
        cols = np.where(gm == g)[0]
        sets[g] = (cand[:, cols].sum(axis=1) > 0)
    print('%-10s' % '' + ''.join('%10s' % g for g in gs))
    for a in gs:
        line = '%-10s' % a
        for b in gs:
            inter = (sets[a] & sets[b]).sum()
            union = (sets[a] | sets[b]).sum()
            jac = inter / union if union else 0
            line += '%9.0f%%' % (jac * 100)
        print(line)
    print()
    any_day = np.zeros(n, dtype=bool)
    for g in gs:
        any_day |= sets[g]
    print('  任一组有候选的天数: %d (%.1f%%)' % (any_day.sum(), 100.0 * any_day.sum() / n))
    for g in gs:
        uniq = sets[g].copy()
        for h in gs:
            if h != g:
                uniq &= ~sets[h]
        print('    仅 %-6s 有候选: %4d 天' % (g, uniq.sum()))
    print()
    print('  ⇒ 若「仅某组有候选」的天数多，说明各组机会时点不同，细化确实能增加频率；')
    print('     若几乎全部重叠，说明候选是「全市场同时超卖」，细化不会带来新机会。')


if __name__ == '__main__':
    main()
