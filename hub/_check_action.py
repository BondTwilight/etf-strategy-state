# -*- coding: utf-8 -*-
"""检查执行卡（其他策略行）+ 实时条 + 全页错误"""
import os

from playwright.sync_api import sync_playwright

HUB = os.path.dirname(os.path.abspath(__file__))
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1560, "height": 1050}, device_scale_factor=1.4)
    pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
    pg.on("console", lambda m: errs.append("CONSOLE:" + m.text) if m.type == "error" else None)
    pg.goto("http://127.0.0.1:8899/", wait_until="networkidle")
    pg.wait_for_timeout(2200)

    print("=== 执行卡 ===")
    print(pg.eval_on_selector("#action", "e=>e.innerText.split(/\\s+/).join(' ').slice(0,420)"))
    print()
    print("livebar:", pg.eval_on_selector(".livebar", "e=>e.innerText.split(/\\s+/).join(' ')"))
    print("undefined:", pg.eval_on_selector("body", "e=>e.innerText").count("undefined"))
    print("NaN:", pg.eval_on_selector("body", "e=>e.innerText").count("NaN"))

    pg.locator("#sec-act").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.locator("#sec-act").screenshot(path=os.path.join(HUB, "_v8_action.png"))
    print("saved _v8_action.png")
    b.close()
print("ERR:", errs if errs else "无")
