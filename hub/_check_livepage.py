# -*- coding: utf-8 -*-
"""验证手机端实时页：file:// 下能否直连东财行情"""
import os

from playwright.sync_api import sync_playwright

P = r"E:/workbuddy1.0/量化agent/live/index.html"
URL = "file:///" + P
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
    pg.on("console", lambda m: errs.append("CONSOLE:" + m.text) if m.type == "error" else None)
    pg.goto(URL, wait_until="load")
    pg.wait_for_timeout(3500)

    print("ts:", pg.eval_on_selector("#ts", "e=>e.textContent"))
    print("dot:", pg.eval_on_selector("#dot", "e=>e.className"))
    print("pills:", pg.eval_on_selector("#pills", "e=>e.innerText.split(/\\s+/).join(' ')"))
    print("prices:", pg.eval_on_selector_all("[data-p]",
          "e=>e.map(x=>x.getAttribute('data-p')+'='+x.textContent+' '+x.className)"))
    print("chg   :", pg.eval_on_selector_all("[data-c]",
          "e=>e.map(x=>x.getAttribute('data-c')+'='+x.textContent)"))
    print("pnl   :", pg.eval_on_selector_all("[data-pnl]",
          "e=>e.map(x=>x.getAttribute('data-pnl')+'='+x.textContent)"))
    print("dist  :", pg.eval_on_selector_all("[data-dist]",
          "e=>e.map(x=>x.getAttribute('data-dist')+'='+x.textContent)"))
    print("cards:", pg.eval_on_selector_all(".card", "e=>e.length"))
    print("undefined:", pg.eval_on_selector("body", "e=>e.innerText").count("undefined"))
    pg.screenshot(path=r"E:/workbuddy1.0/量化agent/hub/_v9_live_mobile.png", full_page=True)
    print("saved")
    b.close()
print("ERR:", errs if errs else "无")
