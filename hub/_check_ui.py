# -*- coding: utf-8 -*-
"""整页截图：手机三段式 + 桌面排行榜"""
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = "file:///" + os.path.join(ROOT, "live", "index.html").replace("\\", "/")
HUB = "file:///" + os.path.join(ROOT, "hub", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    p = c.new_page()
    p.goto(LIVE, wait_until="load", timeout=60000)
    p.wait_for_timeout(2500)
    print("order:", p.eval_on_selector_all(".wrap > div", "e=>e.map(x=>x.id||x.className)"))
    print("labels:", p.eval_on_selector_all(".grp", "e=>e.map(x=>x.innerText.trim())"))
    p.screenshot(path="_ui_full.png", full_page=True)
    c.close()

    c2 = b.new_context(viewport={"width": 1440, "height": 1000})
    p2 = c2.new_page()
    errs = []
    p2.on("pageerror", lambda e: errs.append(str(e)[:160]))
    p2.goto(HUB, wait_until="load", timeout=60000)
    p2.wait_for_timeout(2000)
    p2.locator("#sec-lb").screenshot(path="_ui_lb.png")
    print("errs:", errs)
    c2.close()
    b.close()
