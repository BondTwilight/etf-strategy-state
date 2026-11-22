# -*- coding: utf-8 -*-
"""_hub_shot2.py —— 截净值图区域 + 第二个弹窗"""
import os

from playwright.sync_api import sync_playwright

HUB = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HUB, "index.html").replace("\\", "/")
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1500, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(500)
    el = pg.locator(".panel").last
    el.scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    el.screenshot(path=os.path.join(HUB, "_shot_chart.png"))
    # 打开消费轮动卡片
    pg.click("text=消费轮动 96863", timeout=4000)
    pg.wait_for_timeout(500)
    pg.screenshot(path=os.path.join(HUB, "_shot_modal2.png"))
    b.close()
print("ERR:", errs)
