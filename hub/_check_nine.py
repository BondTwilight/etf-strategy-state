# -*- coding: utf-8 -*-
"""验证「点开策略看九维评分依据」+ 四维判定过程 + 口径之外"""
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = "file:///" + os.path.join(os.path.dirname(HERE), "live", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 1000}, device_scale_factor=2)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:180]))
    pg.goto(PAGE, wait_until="domcontentloaded", timeout=40000)
    pg.wait_for_timeout(3000)

    # 1) 展开四维
    pg.click("#wx-d2")
    pg.wait_for_timeout(400)
    dims = pg.eval_on_selector_all(".wx-dim .r .v", "e=>e.map(x=>x.textContent.trim())")
    whys = pg.eval_on_selector_all(".wx-dim .why", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())")
    ex = pg.eval_on_selector(".wx-ex", "e=>e.innerText.replace(/\\s+/g,' ').trim()") if pg.locator(".wx-ex").count() else ""

    # 2) 展开判据
    pg.click("#wx-d1")
    pg.wait_for_timeout(400)
    conds = pg.eval_on_selector_all(".wx-cond .c",
        "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim().slice(0,90))")
    part = pg.eval_on_selector_all(".wx-cond .c.part", "e=>e.length")

    # 3) 点第一条策略 → 九维
    pg.eval_on_selector(".wx-tb tr.clickable", "e=>e.click()")
    pg.wait_for_timeout(500)
    nd = pg.eval_on_selector_all(".nd", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())")
    total = pg.eval_on_selector(".wx-tb tr.det td div b", "e=>e.textContent.trim()") if pg.locator(".wx-tb tr.det").count() else ""

    pg.locator(".wx").screenshot(path=os.path.join(HERE, "_wx2.png"))
    body = pg.eval_on_selector("body", "e=>e.innerText")
    b.close()

print("=== 四维判定过程（每个 0 分都解释清楚）===")
for v, w in zip(dims, whys):
    print("  [%s] %s" % (v, w[:150]))
print("\n=== 口径之外 ===")
print(" ", ex[:330])
print("\n=== 四条判据（%d 条半满足）===" % part)
for c in conds:
    print("  ", c)
print("\n=== 九维评分依据（点开第一条）===")
print("  总分:", total, "｜维度数:", len(nd))
for x in nd:
    print("   ", x[:110])
print("\nundefined=%d NaN=%d ｜ JS错误 %s"
      % (body.count("undefined"), body.count("NaN"), errs or "无"))
ok = len(nd) == 9 and len(dims) == 4 and part >= 1 and not errs and body.count("undefined") == 0
print("\n" + ("PASS ✅" if ok else "FAIL ❌"))
sys.exit(0 if ok else 1)
