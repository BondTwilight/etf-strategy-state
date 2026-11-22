# -*- coding: utf-8 -*-
"""生成聚宽 v4.6（原版口径：关闭移动止盈 + 保本止损）。

相对 v4.4/current 的唯一逻辑改动：
    ENABLE_TRAIL:      True → False
    ENABLE_BREAKEVEN:  True → False
其余（池子/阈值/四道闸门/冷却/取数/自校验）一字不动，用 AST 校验证明。
"""
import ast
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, '..', 'deliverables', 'jq_etf_dip_current_20261102.py')
DST = os.path.join(BASE, '..', 'deliverables', 'jq_etf_dip_v46_原版无保护位_20261104.py')

HEADER_OLD = '''聚宽回测版 v4.4 · ETF 乖离率抄底策略 · 当前线上口径（14:45）
================================================================
前几版在聚宽上「跑完但零交易」，根因是取数结构。本版按官方文档修正，并加入自校验。'''

HEADER_NEW = '''聚宽回测版 v4.6 · ETF 乖离率抄底策略 · 原版口径（保护位已关闭）
================================================================
【本版与 v4.4 的唯一差别：关掉「移动止盈 8%」与「保本止损 3%」】
    原因（2026-11-04 全量数据三方对账，381 只，2 tick，timeout_live=True）：
      原版（无保护位）      39.76% / -17.95% / Calmar 2.22 / 36 笔 / 胜率 94.4%
      原版 + 盘中止损       36.91% / -14.94% / Calmar 2.47 / 35 笔 / 胜率 91.4%
      现行（trail8+be3）    37.21% / -18.55% / Calmar 2.01 / 43 笔 / 胜率 83.3%
    ⇒ 保护位三维度全落后；3 tick 下更差（37.29% vs 28.11%）。
    ⇒ 移动止盈 5 笔触发【全部亏损】（均值 -8.24%，胜 0/5），实际是「成本下方 8% 止损」。
    ⇒ 原版唯一止损是 -15% 深套止损，全期只触发 1 次（2026-11-03，-18.01%）。

前几版在聚宽上「跑完但零交易」，根因是取数结构。本版保留 v4.4 的全部取数修正与自校验。'''

BENCH_OLD = '''【本地基准（2021-01-04 ~ 2026-10-20，滑点 0.2%，仅供参考，不要当预期）】
    保护位全开（默认）：年化 +38.73%  最大回撤 -18.87%  Calmar 2.05  胜率 84.6%
    保护位全关：        年化 +34.28%  最大回撤 -32.32%  Calmar 1.06  胜率 92.1%

【聚宽实测（本文档版本前身，2026-11-02 跑）】
    2021-01-04 ~ 2026-10-21：年化 31.68%、回撤 19.04%、夏普 1.470
    2022-01-01 ~ 2026-11-01：年化 33.09%、回撤 19.04%、夏普 1.424
    ⇒ 聚宽比本地低 5~7pp，主因是 14:45 成交 vs 收盘价成交
    ⇒ 真实可期年化 30%~35%，回撤按 19% 计'''

BENCH_NEW = '''【本地基准（2021-01-04 ~ 2026-11-04，2 tick，timeout_live=True，不要当预期）】
    ★ 本版（原版口径）：年化 +39.76%  最大回撤 -17.95%  Calmar 2.22  胜率 94.4%  36 笔
      2022 起：        年化 +37.69%  最大回撤 -17.95%  Calmar 2.10  胜率 96.8%  31 笔
    对照 v4.4（保护位开）：年化 +37.21%  最大回撤 -18.55%  Calmar 2.01  胜率 83.3%  43 笔

【聚宽实测（同一代码库的历史版本，供对账参考）】
    v4.4 2021-01-04 ~ 2026-10-21：年化 31.68%、回撤 19.04%、夏普 1.470
    v4.4 2022-01-01 ~ 2026-11-01：年化 33.09%、回撤 19.04%、夏普 1.424
    ⇒ 聚宽比本地低约 4~5pp，主因是 14:45 成交 vs 收盘价成交
    ⇒ 本版预期：年化 33%~36%，回撤 17%~19%（若跑出 30% 以下，先查取数诊断）'''

SWITCH_OLD = '''TRAIL_STOP_PCT = 0.08
BREAKEVEN_STOP_PCT = 0.03
ENABLE_TRAIL = True
ENABLE_BREAKEVEN = True'''

SWITCH_NEW = '''# ★ 2026-11-04：两条保护位全部关闭，回到原版口径（依据见文件头）
#   历史 v4.4 是 True/True（trail 8% + breakeven 3%），已证为净负贡献。
#   若要复现 v4.4 做对照，把下面两行改回 True 即可，其余不用动。
TRAIL_STOP_PCT = 0.08         # 仅在 ENABLE_TRAIL=True 时生效
BREAKEVEN_STOP_PCT = 0.03     # 仅在 ENABLE_BREAKEVEN=True 时生效
ENABLE_TRAIL = False
ENABLE_BREAKEVEN = False'''


def norm_ast(path):
    """抹掉所有字面量（字符串/数字/布尔），只留结构骨架。"""
    s = open(path, encoding='utf-8').read()
    t = ast.parse(s)
    for nd in ast.walk(t):
        if isinstance(nd, ast.Constant):
            nd.value = '<C>'
    return ast.dump(t, annotate_fields=False)


def diff_lines(a_path, b_path):
    import difflib
    a = open(a_path, encoding='utf-8').read().splitlines()
    b = open(b_path, encoding='utf-8').read().splitlines()
    out = [l for l in difflib.unified_diff(a, b, lineterm='', n=0)
           if l.startswith(('+', '-')) and not l.startswith(('+++', '---'))]
    return out


def main():
    s = open(SRC, encoding='utf-8').read()
    orig_len = len(s)

    for old, new, label in ((HEADER_OLD, HEADER_NEW, '文件头标题'),
                            (BENCH_OLD, BENCH_NEW, '基准说明'),
                            (SWITCH_OLD, SWITCH_NEW, '保护位开关')):
        if old not in s:
            raise SystemExit('未找到待替换段落：%s' % label)
        s = s.replace(old, new, 1)
        print('  已替换：%s' % label)

    open(DST, 'w', encoding='utf-8').write(s)
    print('  已写出 %s' % os.path.basename(DST))

    # 校验
    n_th = len(re.findall(r'\d{6}:-?\d+', s))
    print()
    print('  行数 %d ｜ 字节 %d ｜ 池子条目 %d'
          % (s.count('\n') + 1, len(s.encode('utf-8')), n_th))
    for k in ('ENABLE_TRAIL = False', 'ENABLE_BREAKEVEN = False',
              'STOP_LOSS_PCT = 0.15', 'SELL_PROFIT_PCT = 0.03',
              'HOLD_MAX_DAYS = 30', 'MAX_HOLD = 1',
              'STOP_COOLDOWN_DAYS', 'EXEC_TIME'):
        print('  %-26s %s' % (k, k in s))

    # AST 对比（抹掉所有字面量后应完全一致）
    try:
        a = norm_ast(SRC)
        b = norm_ast(DST)
        print()
        print('  AST 归一化长度：源 %d ｜ 新 %d' % (len(a), len(b)))
        print('  AST 结构完全一致（只改了常量值，未动任何逻辑）：%s' % (a == b))
    except SyntaxError as e:
        print('  AST 解析失败：%s' % e)

    # 打印实际差异行（只列代码，跳过注释/docstring）
    print()
    print('  实际改动行：')
    for l in diff_lines(SRC, DST):
        t = l[1:].strip()
        if not t or t.startswith('#'):
            continue
        print('    %s%s' % (l[0], t[:96]))


if __name__ == '__main__':
    main()
