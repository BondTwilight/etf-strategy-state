# -*- coding: utf-8 -*-
"""
P2 前向采集：每天收盘后抓一次恒方 signals.json，记录每个策略腿的持仓/评级。
用途：3 个月后检验“平台共识 risk-on 比例”是否预测我们线C/线B 的收益。
不依赖历史回测，不做任何前视。
"""
import os, json, csv, base64, urllib.request, datetime as dt

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "platform_consensus.csv")
URL = "https://gitee.com/api/v5/repos/bolanggu1031/signal/contents/signals.json"

DEFENSIVE_HINTS = ("空仓", "现金", "515020", "511880", "银行", "货币")


def fetch_signals():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        js = json.loads(r.read().decode("utf-8"))
    return json.loads(base64.b64decode(js["content"]).decode("utf-8", "replace"))


def classify(holding, target, action):
    text = " ".join(str(x or "") for x in (holding, target, action))
    return "defensive" if any(h in text for h in DEFENSIVE_HINTS) else "risk_on"


def main():
    sig = fetch_signals()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for key, v in sig.items():
        p = v.get("payload", {})
        for c in p.get("calibers", []):
            holding = c.get("holding") or ""
            target = c.get("target_code") or ""
            action = c.get("action") or ""
            rows.append({
                "collected_at": now,
                "key": key,
                "trade_date": p.get("trade_date") or "",
                "generated_at": p.get("generated_at") or "",
                "caliber": c.get("short") or "",
                "label": c.get("label") or "",
                "target": target,
                "holding": holding,
                "action": action,
                "grade": c.get("grade") or "",
                "stability": (c.get("stability_full") or "").replace("\n", " "),
                "stance": classify(holding, target, action),
            })

    new = 0
    seen = set()
    exists = os.path.exists(OUT) and os.path.getsize(OUT) > 0
    if exists:
        with open(OUT, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                seen.add((r["key"], r["caliber"], r["trade_date"], r["generated_at"]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if not exists:
            w.writeheader()
        for r in rows:
            k = (r["key"], r["caliber"], r["trade_date"], r["generated_at"])
            if k in seen:
                continue
            w.writerow(r)
            new += 1

    risk = sum(1 for r in rows if r["stance"] == "risk_on")
    print("collected_at:", now)
    print("legs: %d | risk_on: %d | defensive: %d | risk-on ratio: %.0f%%"
          % (len(rows), risk, len(rows) - risk, risk / max(1, len(rows)) * 100))
    print("new rows appended:", new, "->", OUT)
    for r in rows:
        print("  %-28s %-18s %-8s %s" % (r["key"], r["caliber"], r["stance"], r["action"]))


if __name__ == "__main__":
    main()
