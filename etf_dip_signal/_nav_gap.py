# -*- coding: utf-8 -*-
"""算清 11-03 止损 vs 持有到 11-04 的净值差。"""
import pandas as pd

NAV_1103 = 3.7776          # 聚宽报告 277.76% 对应
CASH0 = 100000.0

# 11-03 卖出 588170
QTY = 644600
SELL_PX = 0.583
GROSS = QTY * SELL_PX      # 375,801.8
FEE = 75.16
NET = GROSS - FEE
CLOSE_1103 = 0.579
CLOSE_1104 = 0.695

total_1103 = NAV_1103 * CASH0
residual_cash = total_1103 - NET     # 除这笔外的剩余现金

print('期末总资产（聚宽 277.76%%）：%.2f 元' % total_1103)
print('11-03 卖出 588170：%d 股 × %.4f = %.2f，扣费 %.2f，净入 %.2f'
      % (QTY, SELL_PX, GROSS, FEE, NET))
print('⇒ 除这笔外的剩余现金：%.2f 元' % residual_cash)
print()

if_hold_1103 = QTY * CLOSE_1103 + residual_cash
if_hold_1104 = QTY * CLOSE_1104 + residual_cash
print('若 11-03 未卖：')
print('  11-03 收盘市值 %d × %.4f = %.2f → 净值 %.4f（%+.2f%%）'
      % (QTY, CLOSE_1103, QTY * CLOSE_1103,
         if_hold_1103 / CASH0, (if_hold_1103 / CASH0 - 1) * 100))
print('  11-04 收盘市值 %d × %.4f = %.2f → 净值 %.4f（%+.2f%%）'
      % (QTY, CLOSE_1104, QTY * CLOSE_1104,
         if_hold_1104 / CASH0, (if_hold_1104 / CASH0 - 1) * 100))
print()
print('实际（11-03 已卖）：净值 %.4f（%+.2f%%）' % (NAV_1103, (NAV_1103 - 1) * 100))
print('差额：%.4f 净值 ｜ %.2f 个百分点 ｜ %.0f 元（10 万本金）'
      % (if_hold_1104 / CASH0 - NAV_1103,
         ((if_hold_1104 / CASH0) - NAV_1103) * 100,
         if_hold_1104 - total_1103))
print()
print('=' * 70)
print('若 11-04 14:45 回补（假设无冷却期），成本 %.4f' % 0.685)
back_px = 0.685
print('  回补价 %.4f vs 卖出价 %.4f → 高 %.2f%%，回补反而亏'
      % (back_px, SELL_PX, (back_px / SELL_PX - 1) * 100))
print('  且在 14:45 买入 515880（榜首）到收盘：+0.00%%（14:45 价 = 收盘价）')
