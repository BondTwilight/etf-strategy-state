# -*- coding: utf-8 -*-
"""_hub_shot4.py —— 检查 96864 卡片与弹窗"""
import os

from playwright.sync_api import sync_playwright

HUB = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HUB, "index.html").replace("\\", "/")
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1500, "height": 1100})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append("console:" + m.text) if m.type == "error" else None)
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(600)
    # 滚到 D 组
    pg.eval_on_selector_all(".sec-h h2", "els => els.length")
    pg.locator("text=等股灾 96864").scroll_into_view_if_needed()
    pg.wait_for_timeout(400)
    pg.screenshot(path=os.path.join(HUB, "_v_intel.png"))
    pg.click("text=等股灾 96864", timeout=5000)
    pg.wait_for_timeout(700)
    pg.screenshot(path=os.path.join(HUB, "_v_96864.png"))
    b.close()
print("ERR:", errs)
