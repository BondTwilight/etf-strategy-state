# -*- coding: utf-8 -*-
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HERE, "..", "live", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 900}, device_scale_factor=2)
    p = c.new_page()
    p.goto(URL, wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(2500)
    p.screenshot(path="_one_top.png")
    # 滚到决策链，验证吸顶导航不遮内容
    p.evaluate("document.getElementById('flow').scrollIntoView({block:'start'})")
    p.wait_for_timeout(600)
    p.screenshot(path="_one_sticky.png")
    print("ok")
    c.close()
    b.close()
