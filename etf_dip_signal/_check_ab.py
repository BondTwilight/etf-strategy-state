# -*- coding: utf-8 -*-
"""证明 A/B 两文件除 EXEC_TIME 外完全一致"""
import difflib
import re

A = "../deliverables/jq_etf_dip_v44_A_1450.py"
B = "../deliverables/jq_etf_dip_v44_B_1457.py"

a = open(A, encoding="utf-8").read().splitlines()
b = open(B, encoding="utf-8").read().splitlines()

print("A 行数 %d ｜ B 行数 %d" % (len(a), len(b)))
for name, s in (("A", a), ("B", b)):
    for l in s:
        if l.startswith("EXEC_TIME"):
            print("  %s: %s" % (name, l.strip()))
            break

diff = [d for d in difflib.unified_diff(a, b, lineterm="", n=0)
        if d.startswith(("+", "-")) and not d.startswith(("+++", "---"))]
print("\n差异行数：%d" % len(diff))
for d in diff:
    print("  " + d)

# 除 EXEC_TIME 与其注释外，其余必须完全一致
core_a = [l for l in a if not l.strip().startswith(("EXEC_TIME", "# ★ 本文件为", "# 与另一臂", "# （本地回测用收盘价"))]
core_b = [l for l in b if not l.strip().startswith(("EXEC_TIME", "# ★ 本文件为", "# 与另一臂", "# （本地回测用收盘价"))]
print("\n剔除注释后的核心代码是否完全一致：", core_a == core_b)

for k in ["run_daily(trade, time=EXEC_TIME)", "def signals_at", "_selfcheck",
          "EXIT_ON_TIMEOUT_NO_CAND", "TRAIL_STOP_PCT = 0.08", "ENABLE_TRAIL = True"]:
    print("  %-32s A=%s B=%s" % (k, k in "\n".join(a), k in "\n".join(b)))
