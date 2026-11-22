# -*- coding: utf-8 -*-
"""daily_refresh.py —— 收盘后把「今天的数字」推到所有页面上

为什么需要它
------------
看板不是一张图，是一条链：
    官方持仓 → 统一账本 → 恒方信号 → 行业强弱 → hub.json → 公网看台 → 手机页 → 云快照
链断在哪一环，页面就停在昨天。以前这条链只能手动跑 refresh.bat，
所以它本质上是「一次性看板」——用户不开电脑、不点 bat，就永远看到旧数字。

本脚本只做一件事：每个交易日 15:05 之后把整条链跑一遍，并把
「跑没跑成 / 每步几秒 / 哪步失败」写进 _refresh_meta.json。
页面读这个文件，就能明确告诉你「上次成功刷新是什么时候」。

调度：HKCU\\...\\Run\\QuantDailyRefresh → pythonw daily_refresh.py --loop
（schtasks 与 COM 快捷方式在本机被安全策略拦，只能用 Run 键）
"""
import datetime
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
OUT_DIR = os.path.join(BASE, "信号输出")
META = os.path.join(ROOT, "hub", "_refresh_meta.json")
PY = sys.executable

RUN_AT = "15:05"          # 收盘后 5 分钟：等平台结算与行情落地
ALERT_AT = "14:50"        # 正式信号兜底：14:30 自动化没跑成时，这里补一次
TICK = 60
GUARD = os.path.join(BASE, "intraday_guard.py")
GUARD_LOCK = os.path.join(BASE, "data", "_guard.lock")
SELF_LOCK = os.path.join(BASE, "data", "_refresh.lock")
RUN_LOCK = os.path.join(BASE, "data", "_refresh_run.lock")
PYW = os.path.join(os.path.dirname(PY), "pythonw.exe")

# (名字, 工作目录, 脚本, 是否关键)
STEPS = [
    # 行情库必须第一个跑：它是 hub/行业/评分唯一的数据源。
    # 以前这一步靠手动，结果「每日刷新」看着成功、数据日却永远停在 11-20。
    ("行情库", os.path.join(ROOT, "etf_dip_signal"), "_build_px.py", False),
    # 策略模拟必须在 hub 之前：评分/净值/年度/月历/调仓全部来自这份账本。
    # 以前这一步不在链上，等于「每天刷新页面、但账本永远停在手动跑的那天」。
    ("策略模拟", os.path.join(ROOT, "etf_dip_signal"), "_sim.py", False),
    ("官方持仓", os.path.join(ROOT, "etf_dip_signal"), "_platform.py", False),
    ("统一账本", os.path.join(ROOT, "etf_dip_signal"), "_book.py", False),
    ("恒方信号", os.path.join(ROOT, "hub"), "_hf_fetch.py", False),
    ("行业强弱", os.path.join(ROOT, "hub"), "_industry.py", False),
    ("看台数据", os.path.join(ROOT, "hub"), "hub_build.py", True),
    ("公网看台", os.path.join(ROOT, "hub"), "publish_build.py", False),
    ("手机页", os.path.join(ROOT, "hub"), "_build_live.py", False),
    ("云快照", os.path.join(ROOT, "hub"), "sync_cloud.py", False),
]

# 数据段（先跑完、先写 meta）→ 构建段（页面会读 meta）
DATA_STEPS = STEPS[:6]
BUILD_STEPS = STEPS[6:]


def log(line):
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "refresh_%s.log" % datetime.date.today().strftime("%Y-%m-%d"))
    with open(p, "a", encoding="utf-8") as f:
        f.write("%s  %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"), line))


def _meta():
    try:
        return json.load(open(META, encoding="utf-8"))
    except Exception:
        return {}


def _done_today():
    m = _meta()
    return (m.get("ok") and str(m.get("last_ok") or "")[:10]
            == datetime.date.today().strftime("%Y-%m-%d"))


def _write_meta(steps, ok, t0, last_ok, pending):
    m = _meta()
    m.update({
        "last_run": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "last_ok": last_ok or m.get("last_ok"),
        "ok": ok,
        "pending": pending,
        "cost": round(time.time() - t0, 1),
        "total": len(STEPS),
        "steps": steps,
    })
    json.dump(m, open(META, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return m


def run_once(force=False):
    """对外入口：先拿「刷新任务锁」，再跑。

    🔴 2026-11-22 踩到：手动跑一次（102 秒）时，后台循环看到 _done_today() 还是 False，
    又起了一次，两条链同时写 index.html / live/index.html。构建不是原子的，
    并发写会产出「一半旧一半新」的页面。所以任务锁必须在这里，而不是只在 loop 里。
    """
    from _single_instance import acquire, release
    lk, got = acquire(RUN_LOCK)
    if not got:
        log("已有刷新任务在跑，本次跳过")
        return _meta()
    try:
        return _run_once_inner(force)
    finally:
        release(lk)


def _run_once_inner(force=False):
    """按顺序跑完整条链。

    🔴 meta 要在「数据段跑完、构建段开始前」先写一次：
    页面是构建段生成的，如果等全部跑完才写 meta，页面里的「上次成功刷新」
    会永远显示昨天（第一次跑甚至显示空）。这是很典型的自指时序坑。
    """
    if not force and _done_today():
        log("今日已成功刷新，跳过")
        return _meta()

    t0 = time.time()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    log("=== 开始刷新 ===")
    steps = []

    def run_group(group, dead=False):
        for name, cwd, script, crit in group:
            if dead:
                steps.append({"name": name, "ok": False, "sec": 0, "err": "上游失败，跳过"})
                continue
            s = time.time()
            err, ok = "", False
            # 关键步骤失败重试一次：本机内存紧张时 pandas 会偶发 3MB 级别的
            # _ArrayMemoryError（2026-11-22 实际遇到），重跑一次就能过。
            for attempt in range(2 if crit else 1):
                try:
                    r = subprocess.run([PY, script], cwd=cwd, capture_output=True,
                                       text=True, encoding="utf-8", errors="replace",
                                       timeout=900)
                    ok = (r.returncode == 0)
                    tail = (r.stderr or r.stdout or "").strip().splitlines()
                    err = "" if ok else (" | ".join(tail[-3:])[:400] or ("exit %d" % r.returncode))
                except Exception as e:
                    ok, err = False, repr(e)[:400]
                if ok:
                    break
                if attempt == 0:
                    log("   %s 失败，3 秒后重试一次" % name)
                    time.sleep(3)
                    s = time.time()
            sec = round(time.time() - s, 1)
            steps.append({"name": name, "ok": ok, "sec": sec, "err": err})
            log("%s %s %.1fs%s" % ("✓" if ok else "✗", name, sec, ("  " + err) if err else ""))
            if not ok and crit:
                log("关键步骤失败，后续跳过")
                dead = True
        return dead

    # ① 数据段：持仓 / 账本 / 恒方 / 行业
    run_group(DATA_STEPS)
    # 先把「数据已就绪」写进去，随后构建的页面就能显示今天
    _write_meta(steps, True, t0, now, pending=True)

    # ② 构建段：hub.json → 公网看台 → 手机页 → 云快照
    run_group(BUILD_STEPS)

    ok = all(x["ok"] for x in steps)
    m = _write_meta(steps, ok, t0, now if ok else None, pending=False)
    log("=== %s · %.1fs ===" % ("成功" if ok else "有失败", time.time() - t0))
    return m


def ensure_guard():
    """巡检进程不在岗就拉起来。每次 tick 检查一次，等于一个自愈看门狗。
    判据是系统字节锁（进程死锁自动释放），不是 PID 文件。"""
    try:
        from _single_instance import is_running
        if is_running(GUARD_LOCK):
            return False
        exe = PYW if os.path.exists(PYW) else PY
        # DETACHED_PROCESS：让巡检进程脱离本进程的控制台/生命周期。
        # 否则父进程所在的 shell 一结束，子进程可能被一起收走（2026-11-22 实测）。
        subprocess.Popen([exe, GUARD, "--loop"], cwd=BASE,
                         creationflags=0x00000008 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        log("巡检进程不在岗 → 已拉起 intraday_guard --loop")
        return True
    except Exception as e:
        log("拉起巡检失败：%r" % (e,))
        return False


def ensure_alert(now=None):
    """14:30 正式信号兜底。

    为什么需要：正式信号目前只由 WorkBuddy 自动化触发，客户端没开就没有信号、
    没有邮件、positions.json 也不前进 —— 这是整条链最后一个单点。
    做法：交易日 14:50 检查今天的 signal_YYYY-MM-DD.txt 在不在；不在就跑
    `daily_alert.py --if-not-ran`（幂等：已有文件直接退出，锁：不会与自动化并发）。
    同一天只尝试一次，失败也记下来，不刷屏、不反复下单。
    """
    now = now or datetime.datetime.now()
    if now.weekday() >= 5 or now.strftime("%H:%M") < ALERT_AT:
        return False
    today = now.strftime("%Y-%m-%d")
    if _alert_done(today):
        return False
    m = _meta()
    if m.get("alert_try") == today:
        return False
    # 先记账再执行：即使进程中途崩了，也不会在同一分钟里反复拉起
    m["alert_try"] = today
    json.dump(m, open(META, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("14:30 正式信号未发现（今日无 signal 文件）→ %s 兜底执行 daily_alert.py --if-not-ran" % ALERT_AT)
    try:
        r = subprocess.run([PY, os.path.join(BASE, "daily_alert.py"), "--if-not-ran"],
                           cwd=BASE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        tail = (r.stdout or r.stderr or "").strip().splitlines()[-3:]
        log("兜底结束 rc=%d  %s" % (r.returncode, " | ".join(tail)[:300]))
        return r.returncode == 0
    except Exception as e:
        log("兜底失败：%r" % (e,))
        return False


def _alert_done(today):
    p = os.path.join(BASE, "信号输出", "signal_%s.txt" % today)
    try:
        return os.path.getsize(p) > 200
    except Exception:
        return False


def loop():
    from _single_instance import acquire
    lock, ok = acquire(SELF_LOCK)
    if not ok:
        sys.stderr.write("[daily_refresh] 已有刷新循环在跑，本进程退出\n")
        return
    log("刷新循环在岗 · 每交易日 %s 之后跑一次 · 60s 心跳" % RUN_AT)
    while True:
        try:
            # 2026-11-22 用户决定：舍弃「盘中止损常驻巡检」。
            # 理由：四条策略都是固定时点执行（14:30 / 14:45 / 14:50），
            # 每天盯 5 分钟一次的盘中价既不符合策略口径，也要多养一个常驻进程。
            # 跌破止损由 14:45 的正式信号判断，页面上的「距止损」也实时显示。
            now = datetime.datetime.now()
            ensure_alert(now)
            if now.weekday() < 5 and now.strftime("%H:%M") >= RUN_AT and not _done_today():
                run_once()
        except Exception as e:
            log("本轮异常：%r" % (e,))
        time.sleep(TICK)


if __name__ == "__main__":
    if "--loop" in sys.argv:
        loop()
    else:
        m = run_once(force=("--force" in sys.argv))
        print("ok=%s last_ok=%s cost=%ss" % (m.get("ok"), m.get("last_ok"), m.get("cost")))
        for x in (m.get("steps") or []):
            print("  %s %-6s %5.1fs %s" % ("✓" if x["ok"] else "✗", x["name"], x["sec"], x["err"][:120]))
