# -*- coding: utf-8 -*-
"""公网两页真实可用性探测：状态码 / 标题 / 关键区块 / JS 错误 / 渲染耗时"""
import sys, time, json
from playwright.sync_api import sync_playwright

BASE = "https://etf-strategy-live.app.workbuddy.host"
SC = "?sharecode=XWQ352NNVN"

TARGETS = [
    (BASE + "/" + SC, "mobile"),
    (BASE + "/hub.html" + SC, "hub"),
]

out = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    for url, tag in TARGETS:
        ctx = b.new_context(viewport={"width": 390, "height": 844} if tag == "mobile" else {"width": 1560, "height": 1000},
                            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148")
        pg = ctx.new_page()
        errs, cons, reqs = [], [], []
        pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
        pg.on("console", lambda m: cons.append(m.type + ":" + m.text[:160]) if m.type == "error" else None)
        pg.on("requestfailed", lambda r: reqs.append(r.url[:110] + " | " + str(r.failure)[:80]))
        t0 = time.time()
        try:
            resp = pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            code = resp.status if resp else None
            pg.wait_for_timeout(6000)
            body = pg.eval_on_selector("body", "e=>e.innerText") if pg.locator("body").count() else ""
            d = {
                "status": code,
                "ms": round((time.time() - t0) * 1000),
                "bytes_body": len(body),
                "title": pg.title(),
                "undefined": body.count("undefined"),
                "NaN": body.count("NaN"),
                "has_D": pg.evaluate("() => typeof D !== 'undefined'"),
                "sections": pg.eval_on_selector_all("[id^=sec-]", "e=>e.map(x=>x.id)"),
                "cards": pg.eval_on_selector_all(".card", "e=>e.length"),
                "errs": errs[:5],
                "cons": cons[:5],
                "reqfail": reqs[:6],
                "head": body[:300].replace("\n", " | "),
            }
        except Exception as e:
            d = {"error": str(e)[:220], "ms": round((time.time() - t0) * 1000)}
        out[tag] = d
        ctx.close()
    b.close()

print(json.dumps(out, ensure_ascii=False, indent=1))
