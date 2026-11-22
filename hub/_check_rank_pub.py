# -*- coding: utf-8 -*-
"""公网：rankable 列 + 浮层 + 移动端标记"""
from playwright.sync_api import sync_playwright

BASE = "https://etf-strategy-live.app.workbuddy.host"
SC = "?sharecode=XWQ352NNVN"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 1440, "height": 1000})
    p = c.new_page()
    p.goto(BASE + "/hub.html" + SC, wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(3000)
    print("hstat:", p.eval_on_selector_all(".hs", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())[2]"))
    for r in p.eval_on_selector_all("#leaderboard tbody tr", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())"):
        print("  ", r[:80])
    c.close()

    c2 = b.new_context(viewport={"width": 390, "height": 844})
    p2 = c2.new_page()
    p2.goto(BASE + "/" + SC, wait_until="domcontentloaded", timeout=60000)
    p2.wait_for_timeout(4000)
    p2.locator("#hubnav").click()
    p2.wait_for_timeout(3500)
    print("hv:", p2.eval_on_selector("#hubview", "e=>e.className"))
    fr = [f for f in p2.frames if "hub.html" in (f.url or "")]
    print("frame:", fr[0].title() if fr else "NONE")
    c2.close()
    b.close()
