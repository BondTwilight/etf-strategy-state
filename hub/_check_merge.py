# -*- coding: utf-8 -*-
"""本地：合并区块 + 浮层结构"""
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = "file:///" + os.path.join(ROOT, "hub", "index.html").replace("\\", "/")
LIVE = "file:///" + os.path.join(ROOT, "live", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 1440, "height": 1000})
    p = c.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)[:200]))
    p.goto(HUB, wait_until="load", timeout=60000)
    p.wait_for_timeout(2000)
    print("sections =", p.eval_on_selector_all("[id^=sec-]", "e=>e.map(x=>x.id)"))
    print("subsec =", p.locator(".subsec").count())
    print("nav =", p.eval_on_selector_all(".nav a", "e=>e.map(x=>x.textContent.trim())"))
    print("ms in regime =", p.locator("#sec-regime .subsec #marketstate").count())
    print("cmp in strat =", p.locator("#sec-strat .subsec #bigchart").count())
    print("errs =", errs)
    c.close()

    c2 = b.new_context(viewport={"width": 390, "height": 844})
    p2 = c2.new_page()
    p2.goto(LIVE, wait_until="load", timeout=60000)
    p2.wait_for_timeout(1500)
    print("hv exists =", p2.locator("#hubview").count(), "class =", p2.eval_on_selector("#hubview", "e=>e.className"))
    print("hubnav href =", p2.eval_on_selector("#hubnav", "e=>e.getAttribute('href')"))
    p2.locator("#hubnav").click()
    p2.wait_for_timeout(800)
    print("after click class =", p2.eval_on_selector("#hubview", "e=>e.className"))
    print("iframe src =", p2.eval_on_selector("#hvframe", "e=>e.getAttribute('src')"))
    print("msg =", p2.eval_on_selector("#hvmsg", "e=>e.innerText")[:80])
    c2.close()
    b.close()
