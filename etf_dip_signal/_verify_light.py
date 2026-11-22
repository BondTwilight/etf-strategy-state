# -*- coding: utf-8 -*-
"""轻量验证：确认 etf_dip_signal 目录下模块、路径、池子、指标、决策树均可用（不做 381 只全量取数）。"""
import os, sys, time
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

t0 = time.time()
import config as cfg
print("1) config OK  ALERT_EMAIL=%s  AGENT_EMAIL=%s" % (cfg.ALERT_EMAIL, cfg.AGENT_EMAIL))
print("   ENABLE_EXTERNAL_STRATEGY=%s  EXTERNAL_API_KEY=%r" % (
    cfg.ENABLE_EXTERNAL_STRATEGY, cfg.EXTERNAL_API_KEY))
print("   USE_FIXED_POOL=%s  MAX_HOLD=%s  STOP_LOSS=%.0f%%  COOLDOWN=%s日" % (
    cfg.USE_FIXED_POOL, cfg.MAX_HOLD, cfg.STOP_LOSS_PCT * 100, cfg.STOP_COOLDOWN_DAYS))

import signal_alert as sa
codes, cmap, bmap, frozen = sa.get_pool()
print("2) 固定池 OK  数量=%d  冻结日=%s" % (len(codes), frozen))

import position_store
print("3) positions.json =", position_store.load_snapshots() and "有快照" or "空", "/",
      sa.load_positions() or "空仓")

import tdx_api, indicators as ind, engine
sample = codes[:3]
rt = tdx_api.get_realtime(list(sample) + [cfg.EXTERNAL_TARGET_CODE])
print("4) 实时行情 %d 行 ->" % len(rt), list(zip(rt["code"], rt["price"]))[:4])

b = ind.calculate_bias(sample, rt)
print("5) 乖离率 ->")
for _, r in b.iterrows():
    print("     %s  50日%.2f%%  20日%.2f%%  阈值%d" % (
        r["代码"], r["50日乖离率(%)"], r["20日乖离率(%)"], bmap.get(r["代码"], 0)))

g = engine.G()
print("6) 止损冷却状态 last_stop_date=%r" % g.last_stop_date)
cd, gap, last = engine.in_stop_cooldown("2026-10-20", g)
print("   今日是否冷却=%s" % cd)

print("7) 交易日判断 is_trade_day=%s" % sa.is_trade_day())
print("8) 输出目录 ->", os.path.join(BASE, "信号输出"), os.path.isdir(os.path.join(BASE, "信号输出")))
print("全部通过，耗时 %.1fs" % (time.time() - t0))
