# -*- coding: utf-8 -*-
"""
daily_alert.py —— 定时任务入口（每个交易日 14:40 由自动化调用）

职责（自包含，一步到位）：
  1. 判断交易日，非交易日直接退出（不输出）
  2. 生成交易信号（抄底候选池 + 天基营信号 + 当前持仓 + 操作建议）
  3. 保存到 信号输出/signal_YYYY-MM-DD.txt 和 latest.txt
  4. 若配置了推送通道（企业微信 webhook），自动推送

用法：
  python daily_alert.py            # 完整流程
  python daily_alert.py --force    # 忽略交易日判断（测试用）
"""

import os
import sys
import json
import datetime as _dt

import config as cfg

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)


def _already_ran(today):
    """今日是否已经出过信号：以 signal_YYYY-MM-DD.txt 存在且非空为准。
    这是幂等标记 —— 自动化和 14:50 兜底谁先跑都行，第二个直接跳过。"""
    p = os.path.join(BASE, '信号输出', 'signal_%s.txt' % today)
    try:
        return os.path.getsize(p) > 200
    except Exception:
        return False


def main():
    force = '--force' in sys.argv
    today = _dt.date.today().strftime('%Y-%m-%d')

    # 兜底模式：今天已经跑过就什么都不做（不重复发邮件、不重复写持仓）
    if ('--if-not-ran' in sys.argv) and not force and _already_ran(today):
        print(f"[{today}] 今日信号已存在，跳过（--if-not-ran）")
        return

    # 单实例锁：自动化与兜底同时触发时（14:49/14:50 擦边），只允许一个真正跑
    from _single_instance import acquire, release
    lock, got = acquire(os.path.join(BASE, 'data', '_alert.lock'))
    if not got:
        print("[跳过] 已有信号任务在跑，本次不重复执行")
        return
    try:
        _run(force, today)
    finally:
        release(lock)


def _run(force, today):
    import signal_alert as sa

    # 1. 交易日判断
    if not force:
        try:
            if not sa.is_trade_day():
                print(f"[{today}] 非交易日，退出。")
                return
        except Exception as e:
            print(f"[{today}] 交易日判断失败: {e}，继续尝试。")

    # 2. 生成信号
    try:
        res = sa.generate_signal(top=10, force=force)
    except Exception as e:
        print(f"[{today}] 信号生成失败: {e}")
        return

    # 非交易日（且非 force）直接退出，不覆盖输出
    if not res.get('is_trade_day'):
        print(f"[{today}] 非交易日，退出。")
        return

    # 3. 格式化 + 保存
    text = sa.format_text(res)
    path = sa.save_output(text, today)
    print(text)
    print(f"\n[已保存] {path}")

    # 4. 买卖决策已跑（generate_signal 内）→ 写回持仓 + 记录快照，形成跨日闭环
    import position_store
    final_pos = res.get('final_positions') or {}
    position_store.write_positions(final_pos)          # 决策后持仓写回 positions.json（纯字段）
    position_store.record_snapshot(today, final_pos)   # 记录今日快照（带浮盈）
    print(f"[持仓更新] {today}：{position_store.describe_positions(final_pos)}")

    # 5. 推送（若配置）
    webhook = getattr(cfg, 'WECOM_WEBHOOK', '')
    if webhook:
        sa.push_wecom(text)
    else:
        print("[推送] 未配置推送通道，仅保存到文件。")


if __name__ == '__main__':
    main()
