# -*- coding: utf-8 -*-
"""检查 http 模式下的实时条"""
import os

from playwright.sync_api import sync_playwright

HUB = os.path.dirname(os.path.abspath(__file__))
URL = "http://127.0.0.1:8899/"
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1560, "height": 1000}, device_scale_factor=1.4)
    pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
    pg.on("console", lambda m: errs.append("CONSOLE:" + m.text) if m.type == "error" else None)
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(2500)

    def txt(sel):
        return pg.eval_on_selector(sel, "e=>e.innerText.split(/\\s+/).join(' ')")

    print("livebar:", txt(".livebar"))
    print("dot on :", pg.eval_on_selector_all(".livebar .dot.on", "e=>e.length"))
    print("items  :", pg.eval_on_selector_all(".livebar .it",
                                              "e=>e.map(x=>x.innerText.split(/\\s+/).join(' '))"))
    print("btns   :", pg.eval_on_selector_all(".livebar button", "e=>e.map(x=>x.textContent)"))
    print("undefined:", pg.eval_on_selector("body", "e=>e.innerText").count("undefined"))

    pg.locator("#sec-rp").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.locator("#sec-rp").screenshot(path=os.path.join(HUB, "_v8_live.png"))
    print("saved _v8_live.png")
    b.close()
print("ERR:", errs if errs else "无")
