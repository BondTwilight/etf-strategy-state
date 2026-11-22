# -*- coding: utf-8 -*-
"""检查：逐策略今日动作 / 行业卡移除 / 手机弹窗 / 预加载"""
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = "file:///" + os.path.join(ROOT, "live", "index.html").replace("\\", "/")
HUB = "file:///" + os.path.join(ROOT, "hub", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844})
    p = c.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)[:150]))
    p.goto(LIVE, wait_until="load", timeout=60000)
    p.wait_for_timeout(5000)
    print("hero:", p.eval_on_selector("#hero", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:300])
    print("ind block:", p.locator("#ind").count())
    print("iframe preloaded:", p.eval_on_selector("#hvframe", "e=>e.getAttribute('src')"))
    print("errs:", errs, "sw:", p.evaluate("() => document.documentElement.scrollWidth"))
    c.close()

    c2 = b.new_context(viewport={"width": 390, "height": 844})
    p2 = c2.new_page()
    p2.goto(HUB, wait_until="load", timeout=60000)
    p2.wait_for_timeout(2500)
    p2.locator("#leaderboard tbody tr").first.click()
    p2.wait_for_timeout(500)
    print("modal bg:", p2.eval_on_selector(".modal", "e=>getComputedStyle(e).backgroundColor"))
    print("mbox:", p2.eval_on_selector(".mbox", "e=>{const s=getComputedStyle(e);return [s.backgroundColor,s.borderRadius,s.padding].join(' | ')}"))
    print("mbox text:", p2.eval_on_selector("#mbox", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:100])
    c2.close()
    b.close()
