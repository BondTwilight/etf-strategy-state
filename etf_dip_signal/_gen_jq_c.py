# -*- coding: utf-8 -*-
"""派生 C 组（14:45）—— 量一下线上当前这个时点到底值多少"""
import hashlib
import os

SRC = "../deliverables/jq_etf_dip_v44.py"
OLD_LINE = ("EXEC_TIME = '14:50'            # 决策/成交时点。改成 '14:57' 可近似「按收盘价成交」\n"
            "                               # （本地回测用的是收盘价，两者会有系统性差异）")

base = open(SRC, encoding="utf-8").read()
assert OLD_LINE in base

s = base.replace("ETF 乖离率抄底策略\n", "ETF 乖离率抄底策略 · C 组 · 线上现用时点（14:45）\n", 1)
s = s.replace(OLD_LINE,
              "EXEC_TIME = '14:45'            # ★ 本文件为 C 组 · 线上定时任务当前时点\n"
              "                               # 用来量化「现在这个点到底值多少」\n"
              "                               # 与 A/B 的唯一差异就是这一行", 1)
s = s.replace("【用法】",
              "【本文件用途】线上定时任务就是 14:45。已知 A(14:50)=31.68%、B(14:57)=35.51%，\n"
              "本组用来测 14:45 比 14:50 再早 5 分钟会掉多少。\n\n【用法】", 1)
out = "../deliverables/jq_etf_dip_v44_C_1445.py"
open(out, "w", encoding="utf-8").write(s)
print("C -> %s（%d 字节, md5=%s）" % (os.path.basename(out),
                                     len(s.encode("utf-8")),
                                     hashlib.md5(s.encode("utf-8")).hexdigest()[:12]))
