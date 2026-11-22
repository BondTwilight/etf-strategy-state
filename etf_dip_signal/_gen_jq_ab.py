# -*- coding: utf-8 -*-
"""从 jq_etf_dip_v44.py 派生 A/B 两个可直接粘贴的聚宽策略

唯一差异：EXEC_TIME（A=14:50 原口径，B=14:57 近似收盘成交）
"""
import hashlib
import os

SRC = "../deliverables/jq_etf_dip_v44.py"
ARMS = [
    ("A", "14:50", "A 组 · 原口径（14:50 成交）",
     "本地回测的对照臂。已知结果：年化 30.55% / 回撤 -18.65%。"),
    ("B", "14:57", "B 组 · 近似收盘成交（14:57）",
     "用来验证「差异是否全部来自成交时点」。若年化升到 38~40%，说明是。"),
]

OLD_LINE = ("EXEC_TIME = '14:50'            # 决策/成交时点。改成 '14:57' 可近似「按收盘价成交」\n"
            "                               # （本地回测用的是收盘价，两者会有系统性差异）")

base = open(SRC, encoding="utf-8").read()
assert OLD_LINE in base, "未找到 EXEC_TIME 原始行，请检查 v4.4 是否被改动"

for tag, t, title, note in ARMS:
    s = base.replace("ETF 乖离率抄底策略\n", "ETF 乖离率抄底策略 · %s\n" % title, 1)
    s = s.replace(OLD_LINE,
                  "EXEC_TIME = '%s'            # ★ 本文件为 %s\n"
                  "                               # 与另一臂的唯一差异就是这一行\n"
                  "                               # （本地回测用收盘价，因此 B 更接近本地口径）"
                  % (t, title))
    s = s.replace("> 回测设置", "> 回测设置", 1)
    s = s.replace(
        "【用法】",
        "【本文件用途】%s\n\n【用法】" % note, 1)
    out = "../deliverables/jq_etf_dip_v44_%s_%s.py" % (tag, t.replace(":", ""))
    open(out, "w", encoding="utf-8").write(s)
    print("%s -> %s（%d 字节, md5=%s）"
          % (tag, os.path.basename(out), len(s.encode("utf-8")),
             hashlib.md5(s.encode("utf-8")).hexdigest()[:12]))
