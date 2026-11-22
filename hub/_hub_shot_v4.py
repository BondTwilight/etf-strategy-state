# -*- coding: utf-8 -*-
"""_hub_shot_v4.py —— 浅色版渲染验证（含恒方信号墙 / 评分标准 / undefined 检查）"""
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
    print("hero stats:", pg.eval_on_selector_all(".hs .v", "e=>e.map(x=>x.textContent)"))
    print("leaderboard rows:", pg.eval_on_selector_all("#leaderboard tbody tr", "e=>e.length"))
    print("scores:", pg.eval_on_selector_all("#leaderboard .tot", "e=>e.map(x=>x.textContent)"))
    print("matrix cells:", pg.eval_on_selector_all("#matrix tbody td", "e=>e.length"))
    print("hfwall rows:", pg.eval_on_selector_all("#hfwall tbody tr", "e=>e.length"))
    print("hf signals:", pg.eval_on_selector_all("#hfwall .sig", "e=>e.map(x=>x.textContent.slice(0,26))"))
    print("cards:", pg.eval_on_selector_all("#strategies .card .sc-big b", "e=>e.map(x=>x.textContent)"))

    # ★ undefined 检查：整页文本里不能出现 undefined
    body = pg.eval_on_selector("body", "e=>e.innerText")
    print("body 含 undefined:", body.count("undefined"))
    print("body 含 NaN:", body.count("NaN"))

    pg.screenshot(path=os.path.join(HUB, "_v4_top.png"))
    pg.locator("text=环境适配矩阵").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(HUB, "_v4_matrix.png"))
    pg.locator("text=线C 持仓：线上 vs 模拟").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(HUB, "_v4_hold.png"))
    pg.locator("text=恒方量化 · 11 个产品信号墙").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(HUB, "_v4_hfwall.png"))

    # 弹窗：策略（检查 undefined 行）
    pg.locator("#leaderboard tbody tr").first.click()
    pg.wait_for_timeout(800)
    mb = pg.eval_on_selector("#mbox", "e=>e.innerText")
    print("modal 含 undefined:", mb.count("undefined"))
    print("modal dd rows:", pg.eval_on_selector_all(".ddt tr", "e=>e.length"))
    print("modal dd first:", pg.eval_on_selector_all(".ddt tr", "e=>e.map(x=>x.innerText.slice(0,50))")[:3])
    pg.screenshot(path=os.path.join(HUB, "_v4_modal.png"))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)

    # 评分标准
    pg.locator("#rule-btn").click()
    pg.wait_for_timeout(600)
    print("rule rows:", pg.eval_on_selector_all(".rule tbody tr", "e=>e.length"))
    pg.screenshot(path=os.path.join(HUB, "_v4_rule.png"))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)

    # 恒方产品
    pg.locator("#hfwall tbody tr").first.click()
    pg.wait_for_timeout(600)
    print("hf modal:", pg.eval_on_selector(".mh h3", "e=>e.textContent"))
    pg.screenshot(path=os.path.join(HUB, "_v4_hfmodal.png"))

    b.close()
print("\nERR:", errs if errs else "无")
