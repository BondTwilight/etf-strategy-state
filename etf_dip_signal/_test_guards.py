# -*- coding: utf-8 -*-
"""新增两道护栏的单元测试：容量缩量 + 保护位时间护栏"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
import engine as eng

fails = []


def chk(name, got, want):
    ok = (abs(got - want) < 1e-6) if isinstance(want, float) else (got == want)
    print("  %-52s got=%-12s want=%-12s %s" % (name, got, want, "OK" if ok else "FAIL"))
    if not ok:
        fails.append(name)


print("=== 一、容量看守 cap_by_liquidity ===")
chk("成交额5亿 拟买10万 → 不缩", eng.cap_by_liquidity("X", 100000.0, {"amount": 5e8}), 100000.0)
chk("成交额5000万 拟买10万 → 上限50万，不缩", eng.cap_by_liquidity("X", 100000.0, {"amount": 5e7}), 100000.0)
chk("成交额500万 拟买10万 → 缩到5万", eng.cap_by_liquidity("X", 100000.0, {"amount": 5e6}), 50000.0)
chk("成交额800万 拟买10万 → 缩到8万", eng.cap_by_liquidity("X", 100000.0, {"amount": 8e6}), 80000.0)
chk("成交额缺失 → 原样返回", eng.cap_by_liquidity("X", 100000.0, {"amount": 0}), 100000.0)
chk("rt_row=None → 原样返回", eng.cap_by_liquidity("X", 100000.0, None), 100000.0)

print("\n=== 二、保护位时间护栏 ===")
class P:
    def position(self, code):
        return {"total_amount": 1000, "avg_cost": 1.0}

import pandas as pd
rt = pd.DataFrame([{"code": "512690", "price": 0.90, "last_close": 1.0}])

old = cfg.PROTECT_EARLIEST_TIME
cfg.PROTECT_EARLIEST_TIME = "23:59"          # 强制"现在早于门槛"
hit, why = eng.check_trailing_protect("512690", P(), {}, rt)
print("  %-52s got=%s want=%s %s" % ("当前时间 < 14:40 门槛 → 不判保护位", hit, False,
                                     "OK" if hit is False else "FAIL"))
if hit:
    fails.append("时间护栏")

cfg.PROTECT_EARLIEST_TIME = "00:00"          # 关闭门槛
hit2, why2 = eng.check_trailing_protect("512690", P(), {}, rt)
print("  %-52s got=%s(%s) %s" % ("门槛关闭 → 正常判定（-10% 应触发移动止盈）",
                                 hit2, why2, "OK" if hit2 else "FAIL"))
if not hit2:
    fails.append("门槛关闭后未触发")

cfg.PROTECT_EARLIEST_TIME = old

print("\n=== 结果 ===")
print("  通过 %d 项，失败 %d 项" % (5 + 2 - len(fails), len(fails)))
if fails:
    print("  失败：", fails)
    sys.exit(1)
