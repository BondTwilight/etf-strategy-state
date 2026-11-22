# -*- coding: utf-8 -*-
"""验证 held_days 修复（此前恒为 0）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine

info = {"159967": {"entry_date": "2026-10-21"}}
n = engine.held_days("159967", info, "2026-11-02")
print("held_days(2026-10-21 → 2026-11-02) =", n, "（修复前恒为 0）")
print("期望 8：10-21 起算，含 10-22/23/26/27/28/29/30 与 11-02")
print("判定：", "OK" if n == 8 else "需要复核")
