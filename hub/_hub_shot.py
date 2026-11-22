# -*- coding: utf-8 -*-
"""_hub_shot.py —— 渲染检查：打开看板、抓 console 错误、截图三个状态"""
import os
import sys

from playwright.sync_api import sync_playwright

HUB = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HUB, "index.html").replace("\\", "/")

errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1500, "height": 1000})
    pg.on("console", lambda m: errs.append(("console." + m.type, m.text)) if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errs.append(("pageerror", str(e))))
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(700)
    pg.screenshot(path=os.path.join(HUB, "_shot_top.png"))
    # 滚到策略区
    pg.eval_on_selector_all(".sec", "els => els.length")
    pg.mouse.wheel(0, 1100)
    pg.wait_for_timeout(400)
    pg.screenshot(path=os.path.join(HUB, "_shot_mid.png"))
    # 打开第一张卡
    try:
        pg.click(".card", timeout=3000)
        pg.wait_for_timeout(600)
        pg.screenshot(path=os.path.join(HUB, "_shot_modal.png"))
    except Exception as e:
        errs.append(("click", str(e)))
    # 统计渲染元素
    stats = pg.evaluate("""() => ({
        cards: document.querySelectorAll('.card').length,
        sparks: document.querySelectorAll('.spark').length,
        indices: document.querySelectorAll('.idx').length,
        svgs: document.querySelectorAll('svg').length,
        holds: document.querySelectorAll('.hold-card').length,
        secs: document.querySelectorAll('.sec').length,
        bigchart: (document.querySelector('#bigchart svg') ? 1 : 0)
    })""")
    print("DOM:", stats)
    b.close()

print("ERR:", len(errs))
for k, v in errs:
    print("  ", k, "|", v[:220])
