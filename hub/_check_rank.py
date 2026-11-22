# -*- coding: utf-8 -*-
"""验证 rankable 闸门在页面上的呈现"""
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = "file:///" + os.path.join(ROOT, "hub", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 1440, "height": 1000})
    p = c.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)[:200]))
    p.goto(HUB, wait_until="load", timeout=60000)
    p.wait_for_timeout(2000)
    print("hstats =", p.eval_on_selector_all(".hs", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())"))
    print("lb rows:")
    for r in p.eval_on_selector_all("#leaderboard tbody tr", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())"):
        print("   ", r[:96])
    print("errs =", errs)
    p.locator("#sec-lb").screenshot(path="_rk_lb.png")
    p.locator("#leaderboard tbody tr").first.click()
    p.wait_for_timeout(400)
    print("modal head =", p.eval_on_selector("#mbox h3", "e=>e.innerText")[:60])
    p.screenshot(path="_rk_modal.png")
    c.close()
    b.close()
