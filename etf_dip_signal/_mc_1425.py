# -*- coding: utf-8 -*-
"""14:25 vs 14:45 出信号的策略结果分布（蒙特卡洛）。

标定结论（630 观测，22 只 × 120 日）：
  14:25  ε ~ N(-0.042%, σ=0.460%)
  14:35  ε ~ N(-0.027%, σ=0.389%)
  14:45  ε ~ N(-0.019%, σ=0.237%)
  14:55  ε ~ N(-0.015%, σ=0.117%)
其中 ε = (该时点价 / 收盘价 - 1)

做法：把「信号用的价格」替换为 收盘价×(1+ε)，重跑策略 N 次，看年化/回撤分布。
      这与真实情形近似等价：真实只有当天一个价格，这里扰动 N 次，对乖离率
      的额外影响约 2%（因 bias 是 20/50 日均值，单日扰动被摊薄）。
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
N_SIM = 20
SEED = 20261104

PROFILES = [
    ('14:25', -0.00042, 0.00460),
    ('14:35', -0.00027, 0.00389),
    ('14:45', -0.00019, 0.00237),
    ('14:55', -0.00015, 0.00117),
]


def main():
    d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
    bmap = {str(k): int(v) for k, v in d['bmap'].items()}

    raw = pd.read_parquet('data/etf_qfq_cifang.parquet',
                          columns=['code', 'date', 'open', 'close', 'low'])
    raw['date'] = raw['date'].astype(str).str[:10]
    hist = {}
    for code, g in raw.groupby('code', sort=False):
        f, _ = data_quality.repair_prices(g[['date', 'open', 'close', 'low']])
        hist[code] = f.reset_index(drop=True)
    del raw
    m = bt1.build_matrices(hist, start=START, end=END)
    C0 = m['close'].copy()
    print('矩阵 %d x %d' % C0.shape)

    r0 = bt.run(m, dict(bmap), **STD)
    p0 = bt1.perf(r0['equity'], r0['trades'], 100000.0, r0['exposure'])
    print('基准（按收盘价成交、无扰动）: %.2f%% / %.2f%% / Calmar %.2f'
          % (p0['cagr'] * 100, p0['max_dd'] * 100, p0['calmar']))
    print()
    print('=' * 104)
    print('【1】各时点的策略结果分布（N=%d 次蒙特卡洛）' % N_SIM)
    print('=' * 104)
    print('%-8s %10s %10s %10s %10s %10s %10s'
          % ('时点', '年化均值', '年化σ', '年化P10', '年化P90', '回撤均值', '回撤σ'))
    print('-' * 104)

    rng = np.random.default_rng(SEED)
    out = []
    for tag, mu, sd in PROFILES:
        cagrs, dds = [], []
        for k in range(N_SIM):
            eps = rng.normal(mu, sd, size=C0.shape)
            m2 = dict(m)
            m2['close'] = C0 * (1.0 + eps)
            # 重新算 bias（因为 bias 依赖 close）
            C = pd.DataFrame(m2['close'])
            ma20 = C.rolling(20, min_periods=20).mean()
            ma50 = C.rolling(50, min_periods=50).mean()
            b20 = ((C / ma20 - 1.0) * 100.0).to_numpy().copy()
            b50 = ((C / ma50 - 1.0) * 100.0).to_numpy().copy()
            bmin5 = pd.DataFrame(b20).rolling(5, min_periods=1).min().to_numpy()
            b20[~np.isfinite(b20)] = np.nan
            b50[~np.isfinite(b50)] = np.nan
            m2['bias20'] = b20
            m2['bias50'] = b50
            m2['bmin5'] = bmin5
            r = bt.run(m2, dict(bmap), **STD)
            p = bt1.perf(r['equity'], r['trades'], 100000.0, r['exposure'])
            cagrs.append(p['cagr'] * 100)
            dds.append(p['max_dd'] * 100)
        cagrs = np.array(cagrs); dds = np.array(dds)
        print('%-8s %9.2f%% %9.2f%% %9.2f%% %9.2f%% %9.2f%% %9.2f%%'
              % (tag, cagrs.mean(), cagrs.std(ddof=1),
                 np.percentile(cagrs, 10), np.percentile(cagrs, 90),
                 dds.mean(), dds.std(ddof=1)), flush=True)
        out.append((tag, cagrs, dds))

    print()
    print('=' * 104)
    print('【2】14:25 相对 14:45 的差异是否显著')
    print('=' * 104)
    a = dict((t, (c, dd)) for t, c, dd in out)
    c25, d25 = a['14:25']
    c45, d45 = a['14:45']
    # 两独立样本均值差的标准误
    se = np.sqrt(c25.var(ddof=1) / len(c25) + c45.var(ddof=1) / len(c45))
    diff = c25.mean() - c45.mean()
    print('  年化均值差: %+.2fpp  合并标准误 %.2fpp  t = %.2f'
          % (diff, se, diff / se if se > 0 else 0))
    print('  年化分布: 14:25 [%.2f, %.2f] ｜ 14:45 [%.2f, %.2f]'
          % (np.percentile(c25, 5), np.percentile(c25, 95),
             np.percentile(c45, 5), np.percentile(c45, 95)))
    print('  回撤均值差: %+.2fpp'
          % (d25.mean() - d45.mean()))
    print()
    print('  判读：若 |t| < 2 且均值差 < 1pp ⇒ 提前到 14:25 不改变期望，只放大方差。')
    print()
    print('=' * 104)
    print('【3】结论口径')
    print('=' * 104)
    for tag, c, dd in out:
        print('  %-6s 年化 %.2f%% ±%.2f（90%%区间 %.2f~%.2f）｜ 回撤 %.2f%% ±%.2f'
              % (tag, c.mean(), c.std(ddof=1),
                 np.percentile(c, 5), np.percentile(c, 95),
                 dd.mean(), dd.std(ddof=1)))

    os.makedirs('回测输出', exist_ok=True)
    pd.DataFrame([{'time': t, 'cagr_mean': c.mean(), 'cagr_sd': c.std(ddof=1),
                   'cagr_p10': np.percentile(c, 10), 'cagr_p90': np.percentile(c, 90),
                   'dd_mean': dd.mean(), 'dd_sd': dd.std(ddof=1)}
                  for t, c, dd in out]).to_csv('回测输出/timing_1425.csv',
                                               index=False, encoding='utf-8-sig')
    print('\n已写出 回测输出/timing_1425.csv')


if __name__ == '__main__':
    main()
