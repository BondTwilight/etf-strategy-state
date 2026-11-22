# -*- coding: utf-8 -*-
"""策略详情弹层 + 看台合并观感"""
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = "file:///" + os.path.join(ROOT, "live", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    p = c.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)[:160]))
    p.goto(LIVE, wait_until="load", timeout=60000)
    p.wait_for_timeout(2500)
    print("det links:", p.locator(".det-link").count())
    p.locator(".det-link").first.click()
    p.wait_for_timeout(500)
    print("sheet:", p.eval_on_selector("#stsheet", "e=>e.className"))
    print("box head:", p.eval_on_selector("#stbox", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:420])
    print("cal cells:", p.locator("#stcal .d").count())
    p.locator("#stprev").click()
    p.wait_for_timeout(200)
    print("prev ok:", p.eval_on_selector("#stcal", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:60])
    p.screenshot(path="_st_sheet.png")
    print("errs:", errs)
    c.close()
    b.close()
