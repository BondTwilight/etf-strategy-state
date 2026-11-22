# -*- coding: utf-8 -*-
"""_check_switch.py —— 验证「云端快照更新时，页面自动切换」
前置：云端 built_at 已被改成 2026-11-22 13:05，515450 的 held 被改成 5
"""
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
U = "file:///" + os.path.abspath(os.path.join(ROOT, "live", "index.html")).replace("\\", "/")

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 1000})
    pg.goto(U, wait_until="domcontentloaded")
    pg.wait_for_timeout(14000)

    print("cloudbar :", pg.eval_on_selector("#cloud", "e=>e.innerText.replace(/\\s+/g,' ')")
          if pg.locator("#cloud .cloudbar").count() else "(无)")
    print("云端 dot :", pg.eval_on_selector_all("#cloud .cloudbar .dot.on", "e=>e.length"))
    print("D.built_at:", pg.evaluate("() => D.built_at"))
    print("515450.held:", pg.evaluate("() => {const c=(D.items||[]).find(x=>x.code==='515450');return c?c.held:null;}"))
    card = pg.evaluate("""() => {const c=[...document.querySelectorAll('.card')].find(x=>x.dataset.code==='515450');
        return c?c.innerText.replace(/\\s+/g,' '):'';}""")
    print("515450 卡片:", card[:150])
    b.close()
