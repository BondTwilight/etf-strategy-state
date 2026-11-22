# -*- coding: utf-8 -*-
"""intraday_guard.py —— 盘中止损巡检（真执行）

为什么要有它
------------
`config.ENABLE_INTRADAY_STOP = True` 写着「盘中触及 -15% 立即卖」，
`engine.intraday_stop_scan()` 也已经实现，但**从来没有任何进程调用它**。
结果是：规则写着盯盘、系统每天只看 14:49 一次。

2026-11-20 就是活证据：515880 当日最低 0.3620 已击穿止损 0.3650，
但 14:49 出信号时价还是 0.3670，尾盘 11 分钟跌穿 —— 信号发完就跌破，系统没卖。

它做什么
--------
1. 只在【交易日 + 交易时段】跑（09:30-11:30 / 13:00-15:00），其余时间静默退出
2. 读 positions.json → 拉实时价 → 逐个判「现价 ≤ 成本 × (1 - STOP_LOSS_PCT)」
3. 触发即：
     - 从持仓状态摘除
     - 写回 positions.json
     - 记录当日快照
     - 标记止损日（engine.mark_stop_date → 启动 3 日冷却）
     - 写执行日志 + 推邮件
4. 跌停/停牌跳过，等下一轮（无法成交）
5. 幂等：卖出后持仓已摘除，重复跑不会重复触发；--dry 模式用当日 memo 防刷屏

用法
----
  python intraday_guard.py            单次巡检（给 Windows 计划任务每 5 分钟调用）
  python intraday_guard.py --loop     内置循环，交易时段每 INTRADAY_GUARD_SECONDS 秒跑一次
  python intraday_guard.py --dry      只判不记账（演练）
  python intraday_guard.py --force    忽略交易时段与交易日（离线校验用）
"""
import datetime as _dt
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import config as cfg

OUT_DIR = os.path.join(BASE, "信号输出")
MEMO = os.path.join(BASE, "data", "_guard_memo.json")
POS_FILE = os.path.join(BASE, "data", "positions.json")


# ---------------------------------------------------------------- 时段
def in_session(now=None):
    """是否在交易时段内（不含节假日判断）"""
    now = now or _dt.datetime.now()
    hm = now.hour * 60 + now.minute
    return (9 * 60 + 30 <= hm <= 11 * 60 + 30) or (13 * 60 <= hm <= 15 * 60)


def log(line):
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "guard_%s.log" % _dt.date.today().strftime("%Y-%m-%d"))
    with open(p, "a", encoding="utf-8") as f:
        f.write("%s  %s\n" % (_dt.datetime.now().strftime("%H:%M:%S"), line))


def memo_load():
    try:
        return json.load(open(MEMO, encoding="utf-8"))
    except Exception:
        return {}


def memo_save(d):
    os.makedirs(os.path.dirname(MEMO), exist_ok=True)
    with open(MEMO, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 主巡检
def scan(force=False, dry=False):
    import engine
    import position_store
    import signal_alert as sa
    import web_quote

    today = _dt.date.today().strftime("%Y-%m-%d")
    now = _dt.datetime.now()

    if not force:
        if not in_session(now):
            return None                      # 时段外：静默
        try:
            if not sa.is_trade_day():
                return None                  # 非交易日：静默
        except Exception as e:
            log("[交易日判断失败] %r，按交易日继续" % (e,))

    if not os.path.exists(POS_FILE):
        return None
    pos = sa.load_positions()
    if not pos:
        return None                          # 空仓：静默

    codes = list(pos.keys())
    rt = web_quote.fetch_realtime(codes)
    if rt is None or rt.empty:
        log("[行情失败] %s 只都没取到" % len(codes))
        return None

    pp, pi, ps = position_store.positions_to_state(pos)
    portfolio = engine.Portfolio()
    portfolio.positions = pp
    g = engine.G()
    g.position_info = pi
    g.position_source = ps

    # 巡检前先记录一行「当前状态」，方便事后复盘
    pmap = dict(zip(rt["code"], rt["price"]))
    parts = []
    for c, p in pos.items():
        cost = float(p.get("avg_cost") or 0)
        last = float(pmap.get(c) or 0)
        if cost > 0 and last > 0:
            stop = cost * (1 - cfg.STOP_LOSS_PCT)
            parts.append("%s %.4f/%s %.2f%%(%s)"
                         % (c, last, ("%.4f" % stop), (last / cost - 1) * 100,
                            "已破" if last <= stop else "安全"))
    log("巡检 %d 只：" % len(pos) + " ｜ ".join(parts))

    hit = engine.intraday_stop_scan(g, portfolio, rt, today, verbose=True)
    if not hit:
        return {"date": today, "hits": [], "n": len(pos)}

    memo = memo_load()
    day = memo.get(today) or []
    fresh = [h for h in hit if h["code"] not in day]

    if dry:
        for h in fresh:
            log("[DRY] 会卖出 %s @ %.4f（%+.2f%%）" % (h["code"], h["price"], h["loss_pct"]))
        memo[today] = sorted(set(day + [h["code"] for h in fresh]))
        memo_save(memo)
        return {"date": today, "hits": fresh, "dry": True, "n": len(pos)}

    # ---- 真记账
    newpos = position_store.state_to_positions(
        portfolio.positions, g.position_info, g.position_source)

    # 给剩余持仓补上当日估值字段（与既有快照结构一致）
    if newpos:
        for c, p in newpos.items():
            last = float(pmap.get(c) or 0)
            cost = float(p.get("avg_cost") or 0)
            if last > 0:
                p["last_price"] = round(last, 4)
                if cost > 0:
                    p["pnl_pct"] = round((last / cost - 1) * 100, 4)

    position_store.write_positions(newpos)
    position_store.record_snapshot(today, newpos)

    memo[today] = sorted(set(day + [h["code"] for h in fresh]))
    memo_save(memo)

    # ---- 执行卡 + 推送
    lines = ["【盘中止损·已触发】%s %s" % (today, now.strftime("%H:%M")), ""]
    for h in fresh:
        nm = ""
        try:
            r = rt[rt["code"] == h["code"]].iloc[0]
            nm = r.get("name") or ""
        except Exception:
            pass
        shares = int(float(pos.get(h["code"], {}).get("total_amount") or 0))
        avg = float(pos.get(h["code"], {}).get("avg_cost") or 0)
        lines += [
            "● %s %s" % (h["code"], nm),
            "   成本 %.4f ｜ 触发价 %.4f ｜ 亏损 %+.2f%%" % (avg, h["price"], h["loss_pct"]),
            "   卖出 %s 份，参考金额 %.0f 元" % (format(shares, ","), shares * h["price"]),
            "   执行：立即挂限价 ≥ %.4f（不低于现价 -1%%），未成交则跟价，不追低" % (h["price"] * 0.99),
            "   之后：%d 个交易日内不开新仓（含今日）" % cfg.STOP_COOLDOWN_DAYS,
            "",
        ]
    lines += ["持仓已写回 positions.json，止损日已标记 ⇒ 14:45 正式任务会按冷却期处理。",
              "本消息由 intraday_guard.py 自动发出（PAPER_ONLY，不自动下单）。"]
    text = "\n".join(lines)

    log("触发 %d 笔：%s" % (len(fresh),
                          "、".join("%s@%.4f" % (h["code"], h["price"]) for h in fresh)))
    try:
        sa.push_email(text, "【盘中止损】%s 卖出 %s" % (
            today, "、".join(h["code"] for h in fresh)))
        log("邮件已发送")
    except Exception as e:
        log("邮件发送失败：%r" % (e,))

    return {"date": today, "hits": fresh, "text": text, "n": len(pos)}


# ---------------------------------------------------------------- 循环
def loop():
    # 🔴 单实例闸：两个 guard 同时 scan 会在同一天重复卖出（2026-11-22 真踩到）。
    # 用系统字节锁而不是 PID 文件 —— 进程被强杀时锁自动释放，不会假死。
    from _single_instance import acquire
    lock, ok = acquire(os.path.join(BASE, "data", "_guard.lock"))
    if not ok:
        sys.stderr.write("[intraday_guard] 已有巡检进程在跑，本进程退出（防重复卖出）\n")
        log("已有巡检进程在跑，本进程退出（防重复卖出）")
        return

    step = int(getattr(cfg, "INTRADAY_GUARD_SECONDS", 300))
    sys.stderr.write("[intraday_guard] 循环模式，间隔 %d 秒；交易时段 09:30-11:30 / 13:00-15:00\n" % step)
    last_beat = ""
    while True:
        try:
            r = scan()
            # 心跳：交易时段内每天第一条。没有它的话，非交易日/非交易时段一行日志都没有，
            # 看日志根本分不清「没触发」和「进程早就不在了」。
            now = _dt.datetime.now()
            day = now.strftime("%Y-%m-%d")
            if in_session(now) and last_beat != day:
                last_beat = day
                log("巡检循环在岗 · 间隔 %d 秒 · 非交易时段静默" % step)
            if r and r.get("hits"):
                sys.stderr.write("[intraday_guard] %s 触发 %d 笔\n" % (r["date"], len(r["hits"])))
        except Exception as e:
            sys.stderr.write("[intraday_guard] 本轮异常：%r\n" % (e,))
        # 对齐到下一个整步，避免漂移
        nxt = (int(time.time()) // step + 1) * step
        time.sleep(max(5, nxt - int(time.time())))


if __name__ == "__main__":
    force = "--force" in sys.argv
    dry = "--dry" in sys.argv
    if "--loop" in sys.argv:
        loop()
    else:
        r = scan(force=force, dry=dry)
        if r is None:
            print("（非交易时段/非交易日/空仓，无动作）")
        elif not r.get("hits"):
            print("巡检 %d 只，无触发" % r["n"])
        else:
            print(r.get("text") or r)
