# -*- coding: utf-8 -*-
"""手机页首屏：英雄卡 + 新顺序"""
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = "file:///" + os.path.join(ROOT, "live", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    p = c.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)[:200]))
    p.goto(LIVE, wait_until="load", timeout=60000)
    p.wait_for_timeout(2500)
    print("hero:", p.eval_on_selector("#hero", "e=>e.innerText.replace(/\\s+/g,' ').trim()"))
    print("order:", p.eval_on_selector_all(".wrap > div", "e=>e.map(x=>x.id||x.className)"))
    print("sw:", p.evaluate("() => document.documentElement.scrollWidth"))
    print("errs:", errs)
    p.screenshot(path="_ui_top.png", clip={"x": 0, "y": 0, "width": 390, "height": 900})
    c.close()
    b.close()
