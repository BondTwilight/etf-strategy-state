# -*- coding: utf-8 -*-
"""_hub_shot_v5.py —— 真实持仓 + 市场状态检测器 渲染验证"""
import os

from playwright.sync_api import sync_playwright

HUB = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HUB, "index.html").replace("\\", "/")
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1520, "height": 1150}, device_scale_factor=1.4)
    pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
    pg.on("console", lambda m: errs.append("CONSOLE:" + m.text) if m.type == "error" else None)
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(900)

    print("== 真实持仓总表 ==")
    print("rows:", pg.eval_on_selector_all("#realpos tbody tr", "e=>e.length"))
    print("tag:", pg.eval_on_selector("#rp-tag", "e=>e.textContent"))
    for t in pg.eval_on_selector_all("#realpos tbody tr",
                                     "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').slice(0,120))"):
        print("  ", t)

    print("\n== 市场状态检测器 ==")
    print("tag:", pg.eval_on_selector("#ms-tag", "e=>e.textContent"))
    print("score:", pg.eval_on_selector(".ms-g .big", "e=>e.textContent"))
    print("state:", pg.eval_on_selector(".ms-g .st", "e=>e.textContent"))
    print("dims:", pg.eval_on_selector_all(".ms-d .v", "e=>e.map(x=>x.textContent)"))
    print("labels:", pg.eval_on_selector_all(".ms-d .l", "e=>e.map(x=>x.textContent).slice(0,4)"))
    print("kline svg:", pg.eval_on_selector_all(".kline", "e=>e.length"),
          "candles:", pg.eval_on_selector_all(".kline rect", "e=>e.length"))
    print("ind rows:", pg.eval_on_selector_all(".ms-i tr", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').slice(0,80))")[:6])

    print("\n== 执行时点表 ==")
    print(pg.eval_on_selector("#execmap", "e=>e.innerText.replace(/\\s+/g,' ').slice(0,320)"))

    print("\n== 排行榜：真实持仓列 ==")
    for t in pg.eval_on_selector_all("#leaderboard tbody tr",
                                     "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').slice(0,110))"):
        print("  ", t)

    body = pg.eval_on_selector("body", "e=>e.innerText")
    print("\nbody undefined:", body.count("undefined"), "｜ NaN:", body.count("NaN"))

    pg.screenshot(path=os.path.join(HUB, "_v5_top.png"))
    pg.locator("text=真实持仓总表").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(HUB, "_v5_realpos.png"))
    pg.locator("text=市场状态检测器").scroll_into_view_if_needed()
    pg.wait_for_timeout(400)
    pg.screenshot(path=os.path.join(HUB, "_v5_ms.png"))
    pg.locator("#execmap").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(HUB, "_v5_exec.png"))

    # momo 弹窗（真实持仓块）
    pg.locator("#leaderboard tbody tr").nth(1).click()
    pg.wait_for_timeout(700)
    mb = pg.eval_on_selector("#mbox", "e=>e.innerText")
    print("\nmodal undefined:", mb.count("undefined"))
    print("modal 头:", pg.eval_on_selector(".mh h3", "e=>e.textContent"))
    print("modal 真实持仓段:", [x for x in mb.split("\n") if "真实持仓" in x or "官方绩效" in x][:4])
    pg.screenshot(path=os.path.join(HUB, "_v5_modal.png"), full_page=False)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)

    pg.locator("#ms-btn").click()
    pg.wait_for_timeout(600)
    print("ms rule rows:", pg.eval_on_selector_all(".rule tbody tr", "e=>e.length"))
    pg.screenshot(path=os.path.join(HUB, "_v5_msrule.png"))
    b.close()
print("\nERR:", errs if errs else "无")
