# -*- coding: utf-8 -*-
"""兜底运行：14:52 检查今天是否已出正式信号，没出就跑。

设计原则：
  · 平时空转（10 秒内退出），不打扰用户、不发邮件
  · 只在「今天是交易日 且 latest.txt 不是今天写的」时才真正执行
  · 阈值 10 分钟：若 14:40 那次正在跑（文件刚写），不会重复触发

为什么要它：10-27~10-30 连续 4 个交易日漏跑，导致 159967 的止盈判断整段缺失，
最终以 -15.25% 深套止损离场，多亏约 5.5~7pp（10 万本金约 7,000 元）。
止盈/止损是路径依赖规则，漏跑一天等于没有。

⚠️ 2026-11-04 起：本脚本已不挂定时任务（用户明确删除 14:52 兜底），仅保留备用。
⚠️ 2026-11-04 起：策略回退原版，移动止盈/保本止损已归零，勿按旧文案解读。
"""
import os
import subprocess
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
LATEST = os.path.join(BASE, '信号输出', 'latest.txt')
PY = sys.executable
FRESH_SEC = 600          # 10 分钟内写过 = 视为已运行


def is_trade_day(today):
    try:
        sys.path.insert(0, BASE)
        import tdx_api
        ds = tdx_api.get_trade_dates(start_date=today, end_date=today)
        return len(ds) > 0
    except Exception as e:
        print('[兜底] 交易日判断失败（%s），按交易日处理以保安全' % str(e)[:60])
        return True


def main():
    today = datetime.now().strftime('%Y-%m-%d')
    now = datetime.now().strftime('%H:%M:%S')

    if not is_trade_day(today):
        print('[兜底 %s] %s 非交易日，退出。' % (now, today))
        return

    if not os.path.exists(LATEST):
        print('[兜底 %s] latest.txt 不存在，执行正式运行' % now)
        need_run = True
    else:
        age = time.time() - os.path.getmtime(LATEST)
        mtime_day = datetime.fromtimestamp(os.path.getmtime(LATEST)).strftime('%Y-%m-%d')
        if mtime_day == today and age < FRESH_SEC:
            print('[兜底 %s] 今日正式信号已于 %.0f 秒前生成，跳过。' % (now, age))
            return
        if mtime_day == today:
            print('[兜底 %s] 今日已有信号（%.0f 分钟前），跳过。' % (now, age / 60))
            return
        print('[兜底 %s] latest.txt 最后更新于 %s（非今日），判定 14:40 未成功，执行补跑'
              % (now, mtime_day))
        need_run = True

    if need_run:
        print('[兜底] 启动 daily_alert.py ...')
        r = subprocess.run([PY, 'daily_alert.py'], cwd=BASE,
                           capture_output=True, text=True, timeout=300)
        out = (r.stdout or '') + (r.stderr or '')
        print(out[-2000:])
        print('[兜底] 退出码 %d' % r.returncode)
        if r.returncode != 0:
            print('[兜底] ⚠️ 补跑失败，请人工检查')
            sys.exit(1)
        print('[兜底] 补跑完成。注意：这是延迟信号，14:40 的原始时点已错过，'
              '成交价会与回测口径有偏差。')


if __name__ == '__main__':
    main()
