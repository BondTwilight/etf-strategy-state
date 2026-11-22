# -*- coding: utf-8 -*-
"""_hub_shot_v2.py —— 执行台渲染验证：全页截图 + 关键区块 + 弹窗 + JS 错误"""
import os
import sys

from playwright.sync_api import sync_playwright

HUB = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HUB, "index.html").replace("\\", "/")
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1500, "height": 1100}, device_scale_factor=1.4)
    pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
    pg.on("console", lambda m: errs.append("CONSOLE:" + m.text) if m.type == "error" else None)
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(800)

    print("== 结构检查 ==")
    print("title:", pg.title())
    print("action level:", pg.eval_on_selector(".act", "e=>e.className"))
    print("action head:", pg.eval_on_selector(".act-h", "e=>e.textContent"))
    print("cards:", pg.eval_on_selector_all("#strategies .card .nm", "e=>e.map(x=>x.textContent)"))
    print("health lights:", pg.eval_on_selector_all("#health .hl", "e=>e.length"))
    print("calendar cols:", pg.eval_on_selector_all("#calendar .cl", "e=>e.length"))
    print("holdings:", pg.eval_on_selector_all("#holdings .hold", "e=>e.length"))
    print("cands rows:", pg.eval_on_selector_all("#cands tbody tr", "e=>e.length"))
    print("archived:", pg.eval_on_selector_all("#archived .ac", "e=>e.length"))
    print("bigchart svg paths:", pg.eval_on_selector_all("#bigchart svg path", "e=>e.length"))

    # 首屏（今日执行台 + 日历）
    pg.screenshot(path=os.path.join(HUB, "_v2_top.png"))
    # 持仓 + 数据健康
    pg.locator("text=持仓监控").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(HUB, "_v2_mid.png"))
    # 策略台账
    pg.locator("text=策略台账").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(HUB, "_v2_cards.png"))
    # 净值对照
    pg.locator("text=净值对照").scroll_into_view_if_needed()
    pg.wait_for_timeout(400)
    pg.screenshot(path=os.path.join(HUB, "_v2_chart.png"))
    # 弹窗：线C
    pg.locator("#strategies .card").first.click()
    pg.wait_for_timeout(700)
    pg.screenshot(path=os.path.join(HUB, "_v2_modal_lineC.png"))
    print("modal title:", pg.eval_on_selector(".mh h3", "e=>e.textContent"))
    print("modal dd rows:", pg.eval_on_selector_all(".ddt tr", "e=>e.length"))
    print("modal score items:", pg.eval_on_selector_all(".sci", "e=>e.length"))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(250)

    # 弹窗：恒方（含 legs 表）
    pg.locator("#strategies .card").last.click()
    pg.wait_for_timeout(700)
    pg.screenshot(path=os.path.join(HUB, "_v2_modal_intel.png"))
    print("intel legs rows:", pg.eval_on_selector_all(".mbox .tbl tbody tr", "e=>e.length"))
    b.close()

print("\nERR:", errs if errs else "无")
