# -*- coding: utf-8 -*-
"""_hub_shot_v3.py —— 执行台 v3 渲染验证（排行榜 / 矩阵 / 卡片 / 弹窗）"""
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

    print("== 结构 ==")
    print("title:", pg.title())
    print("regime banner:", pg.eval_on_selector(".rgb .code", "e=>e.textContent"))
    print("leaderboard rows:", pg.eval_on_selector_all("#leaderboard tbody tr", "e=>e.length"))
    print("scores:", pg.eval_on_selector_all("#leaderboard .tot", "e=>e.map(x=>x.textContent)"))
    print("matrix rows/cells:",
          pg.eval_on_selector_all("#matrix tbody tr", "e=>e.length"),
          pg.eval_on_selector_all("#matrix tbody td", "e=>e.length"))
    print("action level:", pg.eval_on_selector(".act", "e=>e.className"))
    print("cards:", pg.eval_on_selector_all("#strategies .card .nm", "e=>e.map(x=>x.textContent.split('\\n')[0])"))
    print("today rows:", pg.eval_on_selector_all("#leaderboard .act-chip", "e=>e.map(x=>x.textContent)"))
    print("holdings:", pg.eval_on_selector_all("#holdings .hold", "e=>e.length"))
    print("divergence:", pg.eval_on_selector_all("#holdings .div", "e=>e.length"))
    print("bigchart paths:", pg.eval_on_selector_all("#bigchart svg path", "e=>e.length"))

    pg.screenshot(path=os.path.join(HUB, "_v3_top.png"))
    pg.locator("text=环境适配矩阵").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(HUB, "_v3_matrix.png"))
    pg.locator("text=线C 持仓：线上 vs 模拟").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(HUB, "_v3_hold.png"))
    pg.locator("text=策略台账").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(HUB, "_v3_cards.png"))
    pg.locator("text=净值对照").scroll_into_view_if_needed()
    pg.wait_for_timeout(400)
    pg.screenshot(path=os.path.join(HUB, "_v3_chart.png"))

    pg.locator("#leaderboard tbody tr").first.click()
    pg.wait_for_timeout(800)
    pg.screenshot(path=os.path.join(HUB, "_v3_modal.png"))
    print("modal title:", pg.eval_on_selector(".mh h3", "e=>e.textContent"))
    print("modal score items:", pg.eval_on_selector_all(".sci", "e=>e.length"))
    print("modal trades rows:", pg.eval_on_selector_all(".trd tbody tr", "e=>e.length"))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    pg.locator("#leaderboard tbody tr").last.click()
    pg.wait_for_timeout(700)
    pg.screenshot(path=os.path.join(HUB, "_v3_modal_hf.png"))
    print("hf legs:", pg.eval_on_selector_all(".mbox .tbl tbody tr", "e=>e.length"))
    b.close()

print("\nERR:", errs if errs else "无")
