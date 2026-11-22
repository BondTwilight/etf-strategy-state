# -*- coding: utf-8 -*-
"""_hub_shot_v7.py —— 决策链 / 环境判据 / 口径 渲染验证"""
import os

from playwright.sync_api import sync_playwright

HUB = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HUB, "index.html").replace("\\", "/")
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1560, "height": 1100}, device_scale_factor=1.4)
    pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
    pg.on("console", lambda m: errs.append("CONSOLE:" + m.text) if m.type == "error" else None)
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(900)

    print("== 决策链 ==")
    for s in pg.eval_on_selector_all(".step", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' '))"):
        print("  ", s)
    print("nav links:", pg.eval_on_selector_all(".nav a", "e=>e.length"))

    print("\n== 环境判据 ==")
    print("tag:", pg.eval_on_selector("#rg-tag", "e=>e.textContent"))
    for s in pg.eval_on_selector_all(".rg>div", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' '))"):
        print("  ", s)

    print("\n== 口径表 ==")
    print("tag:", pg.eval_on_selector("#cal-tag", "e=>e.textContent"))
    for s in pg.eval_on_selector_all("#caliber tbody tr",
                                     "e=>e.map(x=>x.innerText.replace(/\\s+/g,' '))"):
        print("  ", s)
    print("forbid:", pg.eval_on_selector("#forbid", "e=>e.innerText.replace(/\\s+/g,' ').slice(0,120)"))

    print("\n== 排行榜 ==")
    for s in pg.eval_on_selector_all("#leaderboard tbody tr",
                                     "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').slice(0,120))"):
        print("  ", s)

    body = pg.eval_on_selector("body", "e=>e.innerText")
    print("\nbody undefined:", body.count("undefined"), "｜ NaN:", body.count("NaN"))

    pg.screenshot(path=os.path.join(HUB, "_v7_top.png"))
    pg.locator("#sec-caliber").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.locator("#sec-caliber").screenshot(path=os.path.join(HUB, "_v7_caliber.png"))
    pg.locator("#sec-chain").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.locator("#sec-chain").screenshot(path=os.path.join(HUB, "_v7_chain.png"))

    # 锚点跳转有效性
    miss = pg.evaluate("""()=>{
      const ids=[...document.querySelectorAll('.nav a')].map(a=>a.getAttribute('href'))
        .filter(h=>h&&h.startsWith('#')&&h.length>1).map(h=>h.slice(1));
      return ids.filter(id=>!document.getElementById(id));
    }""")
    print("失效锚点:", miss)
    b.close()
print("\nERR:", errs if errs else "无")
