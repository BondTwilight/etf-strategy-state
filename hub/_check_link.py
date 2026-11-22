# -*- coding: utf-8 -*-
"""公网：链路条 + 持仓卡里的行业联动"""
from playwright.sync_api import sync_playwright

U = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"
with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    p = c.new_page()
    p.goto(U, wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(6000)
    print("chk:", p.eval_on_selector("#chk", "e=>e.innerText.trim()"))
    print("chk class:", p.eval_on_selector("#chk", "e=>e.className"))
    p.screenshot(path="_pub_top.png", clip={"x": 0, "y": 0, "width": 390, "height": 300})
    p.locator(".card .tog").first.click()
    p.wait_for_timeout(400)
    txt = p.eval_on_selector(".card .more", "e=>e.innerText.replace(/\\s+/g,' ').trim()")
    print("card more tail:", txt[-220:])
    p.locator(".card").first.screenshot(path="_pub_card.png")
    b.close()
