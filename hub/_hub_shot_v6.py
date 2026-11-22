# -*- coding: utf-8 -*-
"""_hub_shot_v6.py —— 元素级截图（市场状态 / 真实持仓）"""
import os

from playwright.sync_api import sync_playwright

HUB = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HUB, "index.html").replace("\\", "/")
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1560, "height": 1100}, device_scale_factor=1.5)
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(900)
    for sel, name in (("#marketstate", "_v6_ms.png"),
                      ("#realpos", "_v6_rp.png"),
                      ("#execmap", "_v6_exec.png"),
                      ("#strategies", "_v6_cards.png")):
        el = pg.locator(sel)
        el.scroll_into_view_if_needed()
        pg.wait_for_timeout(350)
        el.screenshot(path=os.path.join(HUB, name))
        print("saved", name)
    b.close()
