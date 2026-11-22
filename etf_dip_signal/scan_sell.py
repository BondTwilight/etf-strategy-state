# -*- coding: utf-8 -*-
"""卖出规则变体回测：验证「卖出规则是否过死/滞后」，并给出可回测的替代方案

变体：
  base        原规则（+3% 但候选第一是自己则不卖；30 日到期同样可被否决）
  uncond_tp   +3% 无条件止盈（不看候选排名）
  tp5 / tp8   止盈放宽到 +5% / +8%（仍受候选否决）
  trail8/10   移动止盈：自持仓最高收盘回撤 8% / 10% 即卖
  timeout     满 30 交易日无条件清仓（不看候选）
  hyb         +3% 无条件 + 30 日无条件（去掉全部候选否决权）
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cifang_api
import bt_multi as bt
import bt_etf_dip as bt1
import data_quality

d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
CODES, BMAP = d['codes'], {str(k): int(v) for k, v in d['bmap'].items()}
hist = cifang_api.fetch_pool_history(CODES, cache_path='data/etf_qfq_cifang.parquet')
hist, _ = data_quality.audit(hist, verbose=False)


def over30(tr):
    b = tr[tr.action == 'buy'].reset_index(drop=True)
    s = tr[tr.action == 'sell'].reset_index(drop=True)
    if not len(s):
        return 0, np.nan
    dd = (pd.to_datetime(s['date']) - pd.to_datetime(b['date'])).dt.days
    n = int((dd > 45).sum())        # 45 自然日 ≈ 30 交易日
    return n, float(dd.mean())


for wname, start in [('主窗口 2021起', '2021-01-01'), ('长窗口 2016起', '2016-01-01')]:
    m = bt1.build_matrices(hist, start=start, end='2026-10-20')
    print('\n' + '=' * 112)
    print('%s ｜ 交易日 %d' % (wname, len(m['dates'])))
    print('=' * 112)
    print('  %-22s %9s %9s %9s %8s %7s %9s %8s %10s' % (
        '变体', '总收益', '年化', '最大回撤', 'Calmar', '交易', '胜率', '平均持有', '超30日笔数'))

    cases = [
        ('base 原规则', dict()),
        ('uncond_tp +3%无条件', dict(uncond_tp=True)),
        ('tp5 +5%(受限)', dict(sell_profit=0.05)),
        ('tp8 +8%(受限)', dict(sell_profit=0.08)),
        ('trail8 移动止盈8%', dict(trail=0.08)),
        ('trail10 移动止盈10%', dict(trail=0.10)),
        ('timeout 30日无条件', dict(uncond_timeout=True)),
        ('live口径 到期即退', dict(timeout_live=True)),
        ('trail8+live', dict(trail=0.08, timeout_live=True)),
        ('hyb 全去否决权', dict(uncond_tp=True, uncond_timeout=True)),
    ]
    out = {}
    for name, kw in cases:
        r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode='close', **kw)
        p = bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])
        out[name] = (r, p)
        # 平均持有（自然日）
        tr = r['trades']
        hold = np.nan
        if len(tr):
            b = tr[tr.action == 'buy'].reset_index(drop=True)
            s = tr[tr.action == 'sell'].reset_index(drop=True)
            k = min(len(b), len(s))
            if k:
                hold = float((pd.to_datetime(s['date'][:k]) - pd.to_datetime(b['date'][:k])).dt.days.mean())
        n_over, _ = over30(tr)
        print('  %-22s %8.1f%% %8.2f%% %8.2f%% %8.2f %7d %8.1f%% %7.1f日 %8d' % (
            name, p['total_return'] * 100, p['cagr'] * 100, p['max_dd'] * 100,
            p['calmar'], p['trades'],
            p['win_rate'] * 100 if np.isfinite(p['win_rate']) else -1,
            hold if np.isfinite(hold) else -1, n_over))

    # 卖出原因分布对比
    print('\n  【卖出原因分布】')
    for name in ('base 原规则', 'uncond_tp +3%无条件', 'trail8 移动止盈8%', 'hyb 全去否决权'):
        tr = out[name][0]['trades']
        s = tr[tr.action == 'sell'] if len(tr) else pd.DataFrame()
        vc = s['reason'].value_counts().to_dict() if len(s) else {}
        print('    %-22s %s' % (name, vc))
