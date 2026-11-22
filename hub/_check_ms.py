# -*- coding: utf-8 -*-
"""检查：四维说明 / 恒方详情弹层 / 刷新按钮"""
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = "file:///" + os.path.join(ROOT, "hub", "index.html").replace("\\", "/")
LIVE = "file:///" + os.path.join(ROOT, "live", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 1440, "height": 1000})
    p = c.new_page()
    p.goto(HUB, wait_until="load", timeout=60000)
    p.wait_for_timeout(2000)
    print("ms dims:", p.eval_on_selector_all("#marketstate .ms-d > div", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim().slice(0,110))"))
    c.close()

    c2 = b.new_context(viewport={"width": 390, "height": 844})
    p2 = c2.new_page()
    errs = []
    p2.on("pageerror", lambda e: errs.append(str(e)[:160]))
    p2.goto(LIVE, wait_until="load", timeout=60000)
    p2.wait_for_timeout(2500)
    print("reload btn:", p2.eval_on_selector("#reload", "e=>e.innerText"))
    p2.locator("#intel tbody tr").first.click()
    p2.wait_for_timeout(400)
    print("sheet:", p2.eval_on_selector("#hfsheet", "e=>e.className"),
          "|", p2.eval_on_selector("#hfbox", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:180])
    print("sw:", p2.evaluate("() => document.documentElement.scrollWidth"), "errs:", errs)
    p2.screenshot(path="_hf_sheet.png")
    c2.close()
    b.close()
