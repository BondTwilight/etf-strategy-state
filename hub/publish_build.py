# -*- coding: utf-8 -*-
"""publish_build.py —— 生成公网脱敏版看台 live/hub.html

为什么要单独一份
----------------
主看台里有份额与金额（231,700 份 / 83,875 元），那是**资金规模**，不该上公网。
所以发布版在渲染前把 amount / shares / mv / pnl_amt 全部置空，前端显示「—」；
其余全部保留：代码、名称、成本价、现价、浮亏%、止损价、距止损、
决策链、环境判据、九维评分、环境矩阵、九项尽调、盈亏日历、恒方信号墙。

判据是「策略信息 vs 资金信息」：前者是这套系统值钱的地方，后者只和你账户多大有关。

同一份 template.html、同一份 hub.json，只差一个 mask 步骤。
本地完整版 hub/index.html 不受影响。
"""
import copy
import json
import os
import re

import hub_build as HB

# 资金类字段：一律打码
MASK = ("amount", "shares", "mv", "pnl_amt", "buy_amt", "total_amount")

NOTE = (
    "<b>公网脱敏版</b>：份额 / 金额 / 盈亏额已打码（显示「—」）；"
    "代码 · 成本价 · 止损价 · 浮亏% · 评分 · 矩阵 · 尽调全部保留。<br>"
    "<b>口径</b>：本页是<b>数据日</b>的完整分析快照（决策链 / 环境矩阵 / 九项尽调按该日算）。"
    "想要「当下」的实时价、距止损与今日指令，点右上 <b>📱 实时监控</b>。"
)


def mask(o):
    """就地打码，返回打掉的字段数"""
    n = 0
    if isinstance(o, dict):
        for k in list(o.keys()):
            if k in MASK and o[k] is not None:
                o[k] = None
                n += 1
            else:
                n += mask(o[k])
    elif isinstance(o, list):
        for v in o:
            n += mask(v)
    return n


def main():
    src = os.path.join(HB.HUB, "hub.json")
    hub = copy.deepcopy(json.load(open(src, encoding="utf-8")))
    hit = mask(hub)

    out = os.path.join(HB.ROOT, "live", "hub.html")
    HB.render_to(hub, out, nav_mobile="index.html", mask_note=NOTE)

    # 自检：确认敏感字段真的没了（扫描内联 JSON 里这些键是否还有数字值）
    raw = open(out, encoding="utf-8").read()
    leaked = [k for k in MASK if re.search(r'"%s"\s*:\s*-?[0-9]' % k, raw)]

    print("写出 %s（%.1f KB）" % (out, os.path.getsize(out) / 1024))
    print("打码字段 %d 处（%s）" % (hit, " / ".join(MASK)))
    print("泄漏自检：%s" % ("通过，未发现具体金额/份额" if not leaked else "⚠ 发现 " + ", ".join(leaked)))
    return 1 if leaked else 0


if __name__ == "__main__":
    raise SystemExit(main())
