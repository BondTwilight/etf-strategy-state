# -*- coding: utf-8 -*-
"""验证天基营外部信号接入（真实调用，注意每日 500 次上限，本脚本仅用 4~5 次）。"""
import os, sys, datetime as _dt
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import config as cfg
import engine

print("开关 ENABLE_EXTERNAL_STRATEGY =", cfg.ENABLE_EXTERNAL_STRATEGY)
print("Key  前6位 =", cfg.EXTERNAL_API_KEY[:6] + "..." + cfg.EXTERNAL_API_KEY[-4:],
      "长度", len(cfg.EXTERNAL_API_KEY))

print("\n[1] 字段级原始返回（今日）")
row = engine._fetch_signal_by_date("2026-10-20")
if row is None:
    print("    该日无数据（404）")
else:
    for k in ("date", "longCycle", "midStrength", "duokong1", "newDuokong1",
              "duokong2", "composite", "shortBottom", "updatedAt"):
        print("    %-14s = %r" % (k, row.get(k)))
    print("    → 策略取值 newDuokong1 = %r，判定 %s" % (
        row.get(cfg.EXTERNAL_SIGNAL_FIELD),
        "long(做多)" if str(row.get(cfg.EXTERNAL_SIGNAL_FIELD)).strip() == cfg.EXTERNAL_SIGNAL_LONG else "flat(空仓/非做多)"))

print("\n[2] 非交易日 404 处理（2026-10-18 周日）")
print("    ->", engine._fetch_signal_by_date("2026-10-18"))

print("\n[3] 带回溯的正式取信号（含信号日与滞后天数）")
for d in ("2026-10-20", "2026-10-18"):
    r = engine.fetch_external_signal(d, with_detail=True)
    print("    查询日 %s -> %s" % (d, r))
