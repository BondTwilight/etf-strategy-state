# -*- coding: utf-8 -*-
"""生成「当前线上口径」的聚宽回测文件

与 v4.4 的代码结构完全一致（AST 校验），只做两件事：
  1. EXEC_TIME 固定为 14:45（= 线上定时任务时点）
  2. 头部说明更新为 2026-10-22 蒙特卡洛之后的诚实口径
"""
import ast
import hashlib

SRC = "../deliverables/jq_etf_dip_v44.py"
OUT = "../deliverables/jq_etf_dip_current_20261102.py"

OLD_LINE = ("EXEC_TIME = '14:50'            # 决策/成交时点。改成 '14:57' 可近似「按收盘价成交」\n"
            "                               # （本地回测用的是收盘价，两者会有系统性差异）")

OLD_BASE = """【本地基准（2021-01-04 ~ 2026-10-20）】
    保护位全开（默认）：年化 +40.74%  最大回撤 -18.38%  Calmar 2.22  胜率 82.2%
    保护位全关：        年化 +34.28%  最大回撤 -32.32%  Calmar 1.06  胜率 92.1%"""

NEW_BASE = """【本地基准（2021-01-04 ~ 2026-10-20，仅供参考，不要当预期）】
    保护位全开（默认）：年化 +40.74%  最大回撤 -18.38%  Calmar 2.22  胜率 82.2%
    保护位全关：        年化 +34.28%  最大回撤 -32.32%  Calmar 1.06  胜率 92.1%

【★ 最重要的口径提醒（2026-10-22 蒙特卡洛实测）】
    把信号价扰动 0.26%（= 14:50 与收盘的真实差值），年化就会在 29%~42% 之间飘，
    回撤在 -13%~-35% 之间飘，交易笔数 43~53 笔。
    ⇒ **任何单次回测的年化误差棒是 ±4pp、回撤 ±7pp。**
    ⇒ 两次回测差 4pp 以内一律当噪声，不要据此改参数。
    ⇒ 真实可期年化：30%~38%，做资金规划取 32%。

【口径警告】聚宽显示的「盈亏比」= 总盈利/总亏损（本策略约 4~6）；
    常用口径「平均盈利/平均亏损」约 1.1。两者不是一回事，不可混比。"""

base = open(SRC, encoding="utf-8").read()
assert OLD_LINE in base, "未找到 EXEC_TIME 原始行"
assert OLD_BASE in base, "未找到基准说明段"

s = base.replace("ETF 乖离率抄底策略\n", "ETF 乖离率抄底策略 · 当前线上口径（14:45）\n", 1)
s = s.replace(OLD_BASE, NEW_BASE, 1)
s = s.replace(OLD_LINE,
              "EXEC_TIME = '14:45'            # ★ 与线上定时任务一致（14:45 决策，收盘附近成交）\n"
              "                               # 已实测：14:45/14:50/14:57 三者差异在噪声内，\n"
              "                               # 故本文件采用线上真实时点，不再做时点 A/B", 1)
open(OUT, "w", encoding="utf-8").write(s)

# --- 校验：除 docstring 与 EXEC_TIME 外，AST 必须与 v4.4 一致 ---
def norm(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    body = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "EXEC_TIME" for t in node.targets):
            node.value = ast.Constant(value="<EXEC>")
        body.append(node)
    tree.body = body
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


ok = norm(SRC) == norm(OUT)
print("输出 %s" % OUT)
print("  行数 %d ｜ 字节 %d ｜ md5 %s"
      % (s.count("\n") + 1, len(s.encode("utf-8")),
         hashlib.md5(s.encode("utf-8")).hexdigest()[:12]))
print("  与 v4.4 代码结构一致：", ok)
for l in s.splitlines():
    if l.startswith("EXEC_TIME"):
        print("  ", l.strip()[:56])
        break
print("  池子条目：", s.count(":-16") + s.count(":-11") + s.count(":-5"))
