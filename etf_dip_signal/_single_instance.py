# -*- coding: utf-8 -*-
"""_single_instance.py —— 单实例锁（防止巡检/刷新重复起进程）

为什么不用 PID 文件
------------------
PID 文件在进程被强杀时会留下假记录，下一轮会误判「已经在跑」，
结果该起的没起。用操作系统的字节锁：进程一死，锁自动释放，永远不会假死。

2026-11-22 踩过的坑：重启巡检时旧的没杀干净，两个 intraday_guard 同时 scan，
触发时会重复卖出。这个锁就是那道闸。
"""
import os

try:
    import msvcrt
except ImportError:          # 非 Windows 平台：退化为进程内可用
    msvcrt = None


def acquire(path):
    """非阻塞独占锁。返回 (fh, True)；已被占用返回 (None, False)。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    fh = None
    try:
        fh = open(path, "a+b")
    except PermissionError:
        # 另一个进程正拿着这个文件（Windows 字节锁会让第二次 open 直接拒绝）
        # ⇒ 这本身就是「已在运行」的最强证据，不要当成错误往上抛。
        return None, False
    if msvcrt is None:
        return fh, True
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return fh, True
    except OSError:
        fh.close()
        return None, False


def release(fh):
    """释放锁（关闭文件句柄即可，OS 会自动解锁）。"""
    if not fh:
        return
    try:
        fh.seek(0)
        if msvcrt is not None:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except Exception:
        pass
    try:
        fh.close()
    except Exception:
        pass


def is_running(path):
    """探测某个锁是否被别的进程持有（自己短暂拿一下就放）。"""
    fh, ok = acquire(path)
    if ok:
        release(fh)
        return False
    return True
