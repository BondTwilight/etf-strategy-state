# -*- coding: utf-8 -*-
"""C 组交付前完整性自检"""
import ast
import hashlib

P = "../deliverables/jq_etf_dip_v44_C_1445.py"
s = open(P, encoding="utf-8").read()
lines = s.splitlines()

print("文件      :", P)
print("行数      :", len(lines))
print("字节      :", len(s.encode("utf-8")))
print("md5       :", hashlib.md5(s.encode("utf-8")).hexdigest())

# EXEC_TIME 定位
for i, l in enumerate(lines, 1):
    if l.startswith("EXEC_TIME"):
        print("EXEC_TIME : 第 %d 行 -> %s" % (i, l.strip()))

# 池子完整性
import re
m = re.search(r'_POOL_RAW = \(\n(.*?)\n\)', s, re.S)
pool = m.group(1) if m else ""
n = len([x for x in pool.replace('"\n"', "").replace('"', "").split(",") if ":" in x])
print("池子条目  :", n, "（应为 381）")

# 关键函数是否都在
for k in ["def initialize", "def signals_at", "def _fetch_close", "def _to_wide",
          "def _selfcheck", "def trade", "run_daily(trade, time=EXEC_TIME)",
          "def _sell", "EXIT_ON_TIMEOUT_NO_CAND = True", "ENABLE_TRAIL = True",
          "TRAIL_STOP_PCT = 0.08", "BREAKEVEN_STOP_PCT = 0.03"]:
    print("  %-38s %s" % (k, k in s))

# 语法
ast.parse(s)
print("\n语法解析  : OK")
