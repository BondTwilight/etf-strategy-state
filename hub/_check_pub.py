# -*- coding: utf-8 -*-
"""验证已发布的公网实时页"""
from playwright.sync_api import sync_playwright

URL = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
    pg.on("console", lambda m: errs.append("CONSOLE:" + m.text) if m.type == "error" else None)
    pg.goto(URL, wait_until="load", timeout=45000)
    pg.wait_for_timeout(5000)
    print("title :", pg.title())
    print("ts    :", pg.eval_on_selector("#ts", "e=>e.textContent"))
    print("dot   :", pg.eval_on_selector("#dot", "e=>e.className"))
    print("prices:", pg.eval_on_selector_all("[data-p]",
          "e=>e.map(x=>x.getAttribute('data-p')+'='+x.textContent)"))
    print("chg   :", pg.eval_on_selector_all("[data-c]",
          "e=>e.map(x=>x.getAttribute('data-c')+'='+x.textContent)"))
    print("cards :", pg.eval_on_selector_all(".card", "e=>e.length"))
    print("undefined:", pg.eval_on_selector("body", "e=>e.innerText").count("undefined"))
    pg.screenshot(path=r"E:/workbuddy1.0/量化agent/hub/_v9_pub.png", full_page=False)
    b.close()
print("ERR:", errs if errs else "无")
