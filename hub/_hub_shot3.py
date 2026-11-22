# -*- coding: utf-8 -*-
"""_hub_shot3.py —— 验证新增卡片与恒方腿明细表"""
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
    pg.wait_for_timeout(500)
    print("cards:", pg.eval_on_selector_all(".card", "e=>e.map(x=>x.querySelector('.nm').textContent)"))
    # 恒方
    pg.click("text=恒方量化 · 11 策略情报", timeout=5000)
    pg.wait_for_timeout(600)
    pg.screenshot(path=os.path.join(HUB, "_v_hengfang.png"))
    print("legs rows:", pg.eval_on_selector_all("#mbox .tbl tbody tr", "e=>e.length"))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    # P0/P1
    pg.click("text=P0/P1 · 两个", timeout=5000)
    pg.wait_for_timeout(500)
    pg.screenshot(path=os.path.join(HUB, "_v_p0p1.png"))
    b.close()
print("ERR:", errs)
