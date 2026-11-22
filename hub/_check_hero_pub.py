# -*- coding: utf-8 -*-
"""公网首屏：英雄卡 + 结构"""
from playwright.sync_api import sync_playwright

U = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844})
    p = c.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)[:120]))
    p.goto(U, wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(6000)
    print("hero:", p.eval_on_selector("#hero", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:170])
    print("order:", p.eval_on_selector_all(".wrap > div", "e=>e.map(x=>x.id||x.className)"))
    print("sw:", p.evaluate("() => document.documentElement.scrollWidth"))
    print("errs:", errs)
    b.close()
