# -*- coding: utf-8 -*-
"""公网：四维说明 / 刷新按钮 / 恒方弹层"""
from playwright.sync_api import sync_playwright

U = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"
H = "https://etf-strategy-live.app.workbuddy.host/hub.html?sharecode=XWQ352NNVN"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844})
    p = c.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)[:120]))
    p.goto(U, wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(5500)
    print("reload:", p.eval_on_selector("#reload", "e=>e.innerText"))
    p.locator("#intel tbody tr").first.click()
    p.wait_for_timeout(400)
    print("sheet:", p.eval_on_selector("#hfsheet", "e=>e.className"),
          "|", p.eval_on_selector("#hfbox", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:110])
    print("sw:", p.evaluate("() => document.documentElement.scrollWidth"), "errs:", errs)
    c.close()

    c2 = b.new_context(viewport={"width": 1440, "height": 1000})
    p2 = c2.new_page()
    p2.goto(H, wait_until="domcontentloaded", timeout=60000)
    p2.wait_for_timeout(3500)
    print("dims:", p2.eval_on_selector_all("#marketstate .ms-d > div", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim().slice(0,90))")[2:])
    print("ind tag:", p2.eval_on_selector("#ind-tag", "e=>e.innerText"))
    c2.close()
    b.close()
