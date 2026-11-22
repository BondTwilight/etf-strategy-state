# -*- coding: utf-8 -*-
"""移动端：不可排名标记 + 弹窗闸门说明"""
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = "file:///" + os.path.join(ROOT, "live", "index.html").replace("\\", "/")
HUB = "file:///" + os.path.join(ROOT, "hub", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844})
    p = c.new_page()
    p.goto(LIVE, wait_until="load", timeout=60000)
    p.wait_for_timeout(2000)
    for i in range(p.locator(".card .tog").count()):
        p.locator(".card .tog").nth(i).click()
        p.wait_for_timeout(150)
        t = p.eval_on_selector_all(".card .more", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())")
        hit = [x for x in t if "九维评分" in x]
        for x in hit:
            k = x[x.find("九维评分"):][:70]
            print("card", i, k)
        break
    c.close()

    c2 = b.new_context(viewport={"width": 1440, "height": 1000})
    p2 = c2.new_page()
    p2.goto(HUB, wait_until="load", timeout=60000)
    p2.wait_for_timeout(1500)
    rows = p2.locator("#leaderboard tbody tr")
    rows.nth(2).click()   # 96864
    p2.wait_for_timeout(500)
    print("modal =", p2.eval_on_selector("#mbox", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:260])
    c2.close()
    b.close()
