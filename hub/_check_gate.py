# -*- coding: utf-8 -*-
"""验证准入层 + 折叠默认态"""
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
U = "file:///" + os.path.join(os.path.dirname(HERE), "live", "index.html").replace("\\", "/")

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 900}, device_scale_factor=2)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.goto(U, wait_until="domcontentloaded")
    pg.wait_for_timeout(2500)

    print("rows:")
    for x in pg.eval_on_selector_all(".wx-tb tr.clickable",
                                     "e=>e.map(y=>y.innerText.replace(/\\s+/g,' ').trim())"):
        print("   ", x)
    print("\nverdict:", pg.eval_on_selector(".wx-v", "e=>e.innerText.replace(/\\s+/g,' ').trim()"))
    print("\nbdmore:", pg.eval_on_selector(".wx-bd .bdmore", "e=>getComputedStyle(e).display"))
    print("oth   :", (pg.eval_on_selector(".wx-oth", "e=>getComputedStyle(e).display")
                      if pg.locator(".wx-oth").count() else "none"))
    print("note  :", (pg.eval_on_selector(".wx-note", "e=>getComputedStyle(e).display")
                      if pg.locator(".wx-note").count() else "none"))
    body = pg.eval_on_selector("body", "e=>e.innerText")
    print("undef :", body.count("undefined"), "| err:", errs or "无")
    pg.screenshot(path=os.path.join(HERE, "_wx5.png"))
    b.close()
