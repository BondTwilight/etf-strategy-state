# -*- coding: utf-8 -*-
"""_hub_shot5.py —— 检查 momo 卡片与弹窗"""
import os

from playwright.sync_api import sync_playwright

HUB = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HUB, "index.html").replace("\\", "/")
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1500, "height": 1200})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append("console:" + m.text) if m.type == "error" else None)
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(700)
    print("cards:", pg.eval_on_selector_all(".card .nm", "e=>e.map(x=>x.textContent)"))
    pg.locator("text=线B · momo 原版").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(HUB, "_v_momo_card.png"))
    pg.click("text=线B · momo 原版", timeout=5000)
    pg.wait_for_timeout(800)
    pg.screenshot(path=os.path.join(HUB, "_v_momo.png"))
    b.close()
print("ERR:", errs)
