# -*- coding: utf-8 -*-
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
U = "file:///" + os.path.join(os.path.dirname(HERE), "live", "index.html").replace("\\", "/")

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 1200}, device_scale_factor=2)
    pg.goto(U, wait_until="domcontentloaded")
    pg.wait_for_timeout(2500)
    pg.click("#wx-d2")
    pg.wait_for_timeout(400)
    if pg.locator("#wx-d3").count():
        pg.click("#wx-d3")
        pg.wait_for_timeout(400)
    print("others:", pg.eval_on_selector_all(
        ".wx-oth .o", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())"))
    print("mig:", (pg.eval_on_selector(".wx-mig", "e=>e.innerText.replace(/\\s+/g,' ').trim().slice(0,150)")
                   if pg.locator(".wx-mig").count() else "none"))
    print("textarea:", (pg.eval_on_selector("#wx-mig-txt", "e=>String(e.value).slice(0,90)")
                        if pg.locator("#wx-mig-txt").count() else "none"))
    pg.locator(".wx").screenshot(path=os.path.join(HERE, "_wx3.png"))
    b.close()
