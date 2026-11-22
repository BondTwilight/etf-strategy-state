# -*- coding: utf-8 -*-
"""高胜率的代价与风险：胜率敏感性、收益集中度、bootstrap 置信区间。

回答三个问题：
  ① 胜率从 96.8% 掉到多少，策略就亏钱？
  ② 收益有多依赖少数几笔？
  ③ +5.03% 的单笔期望，在统计上是否显著（还是运气）？
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

CSV = os.path.join(BASE, '回测输出', 'trades_full_2022_2026.csv')
YEARS = 4.83          # 2022-01-04 ~ 2026-11-04
TURNS = 6.4           # 年换手（31 笔 / 4.83 年）


def cagr_from_expect(e, turns=TURNS):
    """把单笔期望换算成年化（复利，年换手 turns 次）。"""
    return (1 + e) ** turns - 1


def main():
    df = pd.read_csv(CSV)
    closed = df[df['reason'] != '(未平仓)'].copy()
    r = closed['ret'].to_numpy(float)
    w = r[r > 0]
    l = r[r <= 0]
    p0 = len(w) / len(r)
    avg_w = w.mean()
    avg_l = l.mean() if len(l) else np.nan

    print('=' * 96)
    print('【一】基本盘')
    print('=' * 96)
    print('  样本 %d 笔 ｜ 胜率 %.1f%% ｜ 平均盈利 %+.2f%% ｜ 平均亏损 %+.2f%%'
          % (len(r), p0 * 100, avg_w * 100, avg_l * 100))
    print('  盈亏比 %.2f : 1 ｜ 盈亏平衡胜率 %.1f%%'
          % (abs(avg_w / avg_l), abs(avg_l) / (avg_w + abs(avg_l)) * 100))
    e0 = p0 * avg_w + (1 - p0) * avg_l
    print('  单笔期望 %+.2f%% ｜ 换算年化 %+.1f%%（年换手 %.1f）'
          % (e0 * 100, cagr_from_expect(e0) * 100, TURNS))

    print()
    print('=' * 96)
    print('【二】胜率敏感性：只要掉到多少就不赚钱')
    print('=' * 96)
    print('  %-10s %12s %12s %10s' % ('胜率', '单笔期望', '年化', '相对现状'))
    for p in (0.968, 0.95, 0.90, 0.85, 0.80, 0.78, 0.76, 0.75, 0.72, 0.70):
        e = p * avg_w + (1 - p) * avg_l
        print('  %-10s %+11.2f%% %+11.1f%% %+9.1fpp'
              % ('%.1f%%' % (p * 100), e * 100, cagr_from_expect(e) * 100,
                 (cagr_from_expect(e) - cagr_from_expect(e0)) * 100))
    print()
    print('  ⇒ 盈亏平衡线 = %.1f%%（跌破即长期亏钱）' % (abs(avg_l) / (avg_w + abs(avg_l)) * 100))
    print('  ⇒ 若止损正常执行在 -15%% 而非 -18.01%%，平衡线降到 %.1f%%'
          % (0.15 / (avg_w + 0.15) * 100))

    print()
    print('=' * 96)
    print('【三】收益集中度')
    print('=' * 96)
    s = np.sort(r)[::-1]
    tot = s.sum()
    print('  31 笔合计收益 %+.1f%%（简单加总）' % (tot * 100))
    for k in (1, 2, 3, 5, 10):
        print('  最好 %2d 笔：合计 %+6.1f%%，占全部 %4.1f%%'
              % (k, s[:k].sum() * 100, s[:k].sum() / tot * 100))
    print()
    print('  剔除最好 N 笔后的单笔期望与年化：')
    for k in (0, 1, 2, 3, 5):
        rest = s[k:]
        if len(rest) < 2:
            continue
        e = rest.mean()
        print('    剔除 %d 笔：剩 %d 笔 ｜ 期望 %+.2f%% ｜ 年化 %+.1f%%'
              % (k, len(rest), e * 100, cagr_from_expect(e) * 100))

    print()
    print('=' * 96)
    print('【四】Bootstrap：+5.03% 的期望是真本事还是运气')
    print('=' * 96)
    rng = np.random.default_rng(20261104)
    B = 20000
    means = np.array([rng.choice(r, size=len(r), replace=True).mean()
                      for _ in range(B)])
    lo, hi = np.percentile(means, [2.5, 97.5])
    print('  Bootstrap %d 次（重抽样 %d 笔）' % (B, len(r)))
    print('  单笔期望 均值 %+.2f%% ｜ 95%% 置信区间 [%+.2f%%, %+.2f%%]'
          % (means.mean() * 100, lo * 100, hi * 100))
    print('  区间下界 > 0 ？ %s' % ('是（显著为正）' if lo > 0 else '否（可能是运气）'))
    print('  区间下界对应的年化：%+.1f%%' % (cagr_from_expect(lo) * 100))
    print()
    print('  ⚠️ 注意：这个置信区间只反映"把这 31 笔看成从同一分布抽样"的不确定性，')
    print('     不包含"未来市场环境变化"的风险，也掩盖了"只有 1 笔亏损"这一事实——')
    print('     亏损样本 n=1，平均亏损 -18.01%% 这个数字本身的误差极大。')

    print()
    print('=' * 96)
    print('【五】"只有 1 笔亏损"意味着什么')
    print('=' * 96)
    print('  亏损笔数 n=1 ⇒ 无法估计：')
    print('    · 止损是否真的有效（没有对照组）')
    print('    · 平均亏损的真实分布（-18.01% 只是这一个样本）')
    print('    · 连续亏损的概率（没出现过连续 2 笔亏损）')
    print()
    # 假设真实亏损率的不同情景
    print('  若真实亏损率是 X，31 笔里出现 ≤1 笔亏损的概率：')
    from math import comb
    for pr in (0.03, 0.05, 0.10, 0.20, 0.30):
        prob = comb(31, 0) * pr ** 0 + 0  # placeholder
        p0_ = (1 - pr) ** 31
        p1_ = 31 * pr * (1 - pr) ** 30
        print('    亏损率 %4.0f%% → P(0 笔亏损)=%.1f%% ｜ P(≤1 笔)=%.1f%%'
              % (pr * 100, p0_ * 100, (p0_ + p1_) * 100))
    print()
    print('  ⇒ 观测到"31 笔仅 1 笔亏损"，与"真实亏损率 5%%"并不矛盾（概率 %.0f%%）。' %
          (((1 - 0.05) ** 31 + 31 * 0.05 * (1 - 0.05) ** 30) * 100))
    print('     所以不能据此断言"真实胜率就是 96.8%%"，样本量根本不够。')

    print()
    print('=' * 96)
    print('【六】持有与换手')
    print('=' * 96)
    print('  平均持仓 %.1f 交易日（中位 %.0f）｜ 持仓占比 %.1f%%'
          % (closed['hold_td'].mean(), closed['hold_td'].median(),
             closed['hold_td'].sum() / 1200 * 100))
    print('  年换手 %.1f 次 ⇒ 每年约 %.1f%% 的时间在场内'
          % (len(closed) / YEARS, closed['hold_td'].sum() / YEARS / 244 * 100))
    print('  成本敏感：单边 2 tick（约 0.2%%）→ 往返 0.4%%，'
          '按 %.1f 次年换手 = 年化拖累约 %.1fpp'
          % (len(closed) / YEARS, len(closed) / YEARS * 0.4))


if __name__ == '__main__':
    main()
