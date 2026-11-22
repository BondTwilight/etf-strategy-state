# -*- coding: utf-8 -*-
"""sync_cloud.py —— 生成同步到云数据库的 SQL（脱敏 + 精简）

为什么需要它
------------
手机页的数据原本写死在 HTML 里，只有重新发布才会变。
上云后页面优先读 `strategy_snapshot`：这份脚本把「会变的数字」抽出来 ——
持仓、成本、止损、浮盈、今日动作、持有天数 —— 静态文案（九维、尽调、下一步）
仍由页面内嵌提供，按 code 合并。

为什么不让页面自己写
--------------------
RLS 只建了 SELECT 策略，客户端（含 anon）没有任何写入权限。
这是故意的：一个谁都能改止损价的页面不该存在。
写入只走管理通道（exec_sql），由策略中枢这一侧执行。

脱敏
----
即使构建时开了 LIVE_SHOW_AMOUNT=1，本脚本也强制剔除 amount / shares / mv / pnl_amt。
上云的内容与已发布页面完全同级，不增加暴露面。

用法
----
    python sync_cloud.py                 # 打印 payload 与 SQL，写入 live/_cloud_sql.txt
    python sync_cloud.py --events        # 额外解析 guard 日志，给出可插入的巡检事件
"""
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIVE = os.path.join(ROOT, "live")
GUARD_DIR = os.path.join(ROOT, "etf_dip_signal", "信号输出")

# 强制不上云的字段（份额、金额、市值、盈亏额）
SECRET_KEYS = ("amount", "shares", "mv", "pnl_amt", "total_amount", "buy_amt")


def slim(r, act=None):
    """一条真实持仓 → 云端最小字段集（已脱敏）

    只保留「会变的数字」。策略名 / 徽章 / 九维 / 尽调文案仍由页面内嵌提供，
    按 code 合并 —— 那些内容不随行情变化，没必要每天推一遍。
    """
    return {
        "code": r.get("code"),
        "name": r.get("name"),
        "cost": r.get("buy_price") if r.get("buy_price") is not None else r.get("cost"),
        "stop": r.get("stop"),
        "act": act,
        "held": r.get("held_days") if r.get("held_days") is not None else r.get("held"),
        "dist": r.get("dist_stop") if r.get("dist_stop") is not None else r.get("dist"),
        "pnl": r.get("pnl"),
        "prem": r.get("prem"),
    }


def last_guard():
    """最近一次巡检的时间戳（HH:MM:SS）+ 是否有真触发。
    返回值固定 3 元组 —— 调用方是 day, ts, hit = last_guard()，
    早退分支只返回 2 个会在「今天还没有巡检日志」时直接抛 ValueError。"""
    if not os.path.isdir(GUARD_DIR):
        return None, None, False
    files = sorted([f for f in os.listdir(GUARD_DIR)
                    if re.match(r"guard_\d{4}-\d{2}-\d{2}\.log$", f)])
    if not files:
        return None, None, False
    last = files[-1]
    day = last.replace("guard_", "").replace(".log", "")
    ts, hit = None, False
    try:
        with open(os.path.join(GUARD_DIR, last), encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = re.match(r"^(\d{2}:\d{2}:\d{2})\s+(.*)$", line.strip())
                if not m:
                    continue
                ts = m.group(1)
                if m.group(2).startswith("触发") and "0 笔" not in m.group(2):
                    hit = True
    except Exception:
        pass
    return (day, ts, hit)


def build_payload(hub):
    S = {s["id"]: s for s in (hub.get("strategies") or [])}
    ev = hub.get("regime_evidence") or {}
    ms = (hub.get("market_state") or {}).get("items") or []
    prim = (hub.get("market_state") or {}).get("primary")
    m0 = next((x for x in ms if x.get("code") == prim), (ms[0] if ms else None))

    items, seen = [], set()
    for r in (hub.get("real_positions") or []):
        c = r.get("code")
        if c in (None, "—") or c in seen:
            continue
        seen.add(c)
        sid = r.get("sid")
        act = ((S.get(sid) or {}).get("live_action") or {}).get("action")
        items.append(slim(r, act))

    # 同标的被多条策略持有时只保留一条（合并展示由页面用内嵌数据完成）
    for r in (hub.get("extra_live") or []):
        c = r.get("code")
        if c in (None, "—") or c in seen:
            continue
        seen.add(c)
        items.append(slim(r))

    day, ts, hit = last_guard()
    p = {
        "data_date": (hub.get("meta") or {}).get("data_date"),
        "built_at": (hub.get("meta") or {}).get("built_at"),
        "session": (hub.get("meta") or {}).get("session"),
        "regime": {"code": ev.get("code"), "label": ev.get("label"),
                   "hits": sum(1 for x in (ev.get("items") or []) if x.get("hit")),
                   "n": len(ev.get("items") or [])},
        "market": None if not m0 else {"state": m0["score"]["state"],
                                       "score": m0["score"]["total"],
                                       "conf": m0["score"]["conf"]},
        "guard": {"date": day, "last_at": ts, "hit": bool(hit)},
        "items": items,
    }
    # 保险：任何残留的敏感字段一律剔除
    for it in p["items"]:
        for k in SECRET_KEYS:
            it.pop(k, None)
    return p


def main():
    hub = json.load(open(os.path.join(HERE, "hub.json"), encoding="utf-8"))
    p = build_payload(hub)
    txt = json.dumps(p, ensure_ascii=False, separators=(",", ":"))

    snap_sql = (
        "INSERT INTO strategy_snapshot (id, data_date, built_at, payload) "
        "VALUES ('live', $1, $2, $3::jsonb) "
        "ON CONFLICT (id) DO UPDATE SET data_date = EXCLUDED.data_date, "
        "built_at = EXCLUDED.built_at, payload = EXCLUDED.payload, synced_at = now()"
    )

    print("===== PAYLOAD（脱敏，%d 字符）=====" % len(txt))
    print(txt)
    print()
    print("===== snapshot SQL =====")
    print(snap_sql)
    print("参数：")
    print('  $1 = %r' % p["data_date"])
    print('  $2 = %r' % p["built_at"])
    print("  $3 = 上面的 payload 全文")

    if "--events" in sys.argv:
        print()
        print("===== 巡检事件（仅非 DRY 的真实触发）=====")
        print("今天日志里只有 dry-run，不产生 stop 事件；真实触发时按下面格式追加：")
        print("INSERT INTO guard_event (trade_date, ts, code, name, action, price, detail) "
              "VALUES ($1,$2,$3,$4,$5,$6,$7)")

    out = os.path.join(HERE, "_cloud_sql.txt")   # 放 hub/，不进发布目录
    with open(out, "w", encoding="utf-8") as f:
        f.write(txt + "\n\n" + snap_sql + "\n")
    print()
    print("已写出 %s（%d 字节）" % (out, os.path.getsize(out)))


if __name__ == "__main__":
    main()
