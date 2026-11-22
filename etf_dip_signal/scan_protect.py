# -*- coding: utf-8 -*-
"""「赚了就卖 / 不亏即赢」的两种实现及其代价

用户直觉：胜率 92%，那就赚一点就跑、绝不认亏，不就稳赢了？
本脚本把它拆成两个可回测的机制分别检验：

  ① 赚了就卖 = 无条件止盈（不看候选排名）        —— 已测，见下
  ② 不亏即赢 = 保本止损（浮盈达 X% 后回落到成本价就卖）
  ③ 两者 + 移动止盈 的组合

同时验证「空仓期买债」的真实增益（cash_yield）。
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

CASES = [
    ('基准（原规则）', dict()),
    ('赚了就卖 +3%无条件', dict(uncond_tp=True)),
    ('保本止损(曾达+3%)', dict(be_stop=0.03)),
    ('保本止损(曾达+5%)', dict(be_stop=0.05)),
    ('保本止损(曾达+8%)', dict(be_stop=0.08)),
    ('移动止盈8%', dict(trail=0.08)),
    ('移动止盈8% + 保本+3%', dict(trail=0.08, be_stop=0.03)),
    ('移动止盈8% + 保本+5%', dict(trail=0.08, be_stop=0.05)),
    ('空仓计息 2.5%', dict(cash_yield=0.025)),
    ('移动止盈8% + 计息2.5%', dict(trail=0.08, cash_yield=0.025)),
]

for wname, start in [('主窗口 2021起', '2021-01-01'), ('长窗口 2016起', '2016-01-01')]:
    m = bt1.build_matrices(hist, start=start, end='2026-10-20')
    print('\n' + '=' * 112)
    print('%s ｜ 交易日 %d' % (wname, len(m['dates'])))
    print('=' * 112)
    print('  %-24s %9s %9s %9s %8s %8s %7s %9s' % (
        '方案', '年化', '最大回撤', 'Calmar', '夏普', '胜率', '交易', '净利因子'))
    for name, kw in CASES:
        r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode='close',
                   timeout_live=True, **kw)
        tr = r['trades']
        if not len(tr):
            print('  %-24s 无交易' % name)
            continue
        p = bt1.perf(r['equity'], tr, 100000.0, r['exposure'])
        s = tr[tr.action == 'sell']
        gp = s[s.ret > 0]['ret'].sum()
        gl = abs(s[s.ret <= 0]['ret'].sum())
        print('  %-24s %8.2f%% %8.2f%% %8.2f %8.2f %7.1f%% %7d %9.2f' % (
            name, p['cagr'] * 100, p['max_dd'] * 100, p['calmar'], p['sharpe'],
            p['win_rate'] * 100 if np.isfinite(p['win_rate']) else -1,
            p['trades'], gp / gl if gl else np.inf))

    # 卖出原因分布
    print('\n  【卖出原因分布】')
    for name, kw in CASES:
        r = bt.run(m, BMAP, max_hold=1, intraday_stop=True, exec_mode='close',
                   timeout_live=True, **kw)
        tr = r['trades']
        s = tr[tr.action == 'sell'] if len(tr) else pd.DataFrame()
        vc = s['reason'].value_counts().to_dict() if len(s) else {}
        print('    %-24s %s' % (name, vc))
