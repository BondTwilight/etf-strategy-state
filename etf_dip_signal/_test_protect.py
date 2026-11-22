# -*- coding: utf-8 -*-
"""单元测试：移动止盈 / 保本止损 的触发边界（不联网、纯构造）"""
import pandas as pd
import config as cfg
import engine


class P:
    def __init__(self, cost, amt=1000):
        self._p = {'total_amount': amt, 'avg_cost': cost}

    def position(self, code):
        return self._p


def rt(price, code='X'):
    return pd.DataFrame([{'code': code, 'price': price}])


def run(cost, price, peak=None, armed=False):
    pi = {'X': {'entry_price': cost, 'entry_date': '2026-10-01'}}
    if peak:
        pi['X']['peak_price'] = peak
    if armed:
        pi['X']['be_armed'] = True
    ok, why = engine.check_trailing_protect('X', P(cost), pi, rt(price))
    return ok, why, pi['X'].get('peak_price'), pi['X'].get('be_armed')


cfg.TRAIL_STOP_PCT = 0.08
cfg.BREAKEVEN_STOP_PCT = 0.03
cfg.STOP_LOSS_PCT = 0.15

cases = [
    ('成本1.00 现价0.99 无峰值（未激活）', 1.00, 0.99, None, False, False),
    ('成本1.00 峰值1.10 现价1.01（回撤8.2%）', 1.00, 1.01, 1.10, False, True),
    ('成本1.00 峰值1.10 现价1.03（回撤6.4%）', 1.00, 1.03, 1.10, False, False),
    ('成本1.00 峰值1.05 现价0.99（已激活，回落破成本）', 1.00, 0.99, 1.05, True, True),
    ('成本1.00 峰值1.05 现价1.01（已激活但仍在成本上）', 1.00, 1.01, 1.05, True, False),
    ('成本1.00 峰值1.20 现价0.90（曾+20%后跳空到-10%）', 1.00, 0.90, 1.20, True, True),
    ('成本1.00 现价0.96 峰值1.00（从未涨过，不该管）', 1.00, 0.96, 1.00, False, False),
]
print('%-46s %-6s %-8s %s' % ('场景', '触发', '原因', '峰值→保本激活'))
for name, cost, px, peak, armed, expect in cases:
    ok, why, pk, ar = run(cost, px, peak, armed)
    flag = 'OK' if ok == expect else '!! 不符预期'
    print('%-46s %-6s %-8s %s -> %s   %s' % (
        name, ok, why or '-', pk, ar, flag if flag == 'OK' else flag))
