# -*- coding: utf-8 -*-
"""公网：策略详情 + 合并观感"""
from playwright.sync_api import sync_playwright

U = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844})
    p = c.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)[:120]))
    p.goto(U, wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(6000)
    print("det links:", p.locator(".det-link").count())
    # 找 momo 卡片（第二张左右），按文案定位
    idx = 0
    for i in range(p.locator(".det-link").count()):
        card = p.locator(".card").nth(i)
        if "momo" in card.inner_text():
            idx = i
            break
    p.locator(".det-link").nth(idx).click()
    p.wait_for_timeout(500)
    print("sheet:", p.eval_on_selector("#stsheet", "e=>e.className"))
    print("box:", p.eval_on_selector("#stbox", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:520])
    p.screenshot(path="_st_pub.png")
    p.locator("#stx").click()
    p.wait_for_timeout(200)
    # 合并观感：iframe 里的 .hero 应被隐藏
    p.locator("#hubnav").click()
    p.wait_for_timeout(4500)
    fr = [f for f in p.frames if "hub.html" in (f.url or "")]
    if fr:
        f = fr[0]
        print("frame title:", f.title())
        print("hero visible:", f.evaluate("() => { const h=document.querySelector('.hero'); return h?getComputedStyle(h).display:'none'; }"))
        print("nav count:", f.evaluate("() => document.querySelectorAll('.nav a').length"))
    else:
        print("NO FRAME")
    print("sw:", p.evaluate("() => document.documentElement.scrollWidth"), "errs:", errs)
    b.close()
