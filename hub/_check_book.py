# -*- coding: utf-8 -*-
"""验证策略账本：排序、净值曲线、龟龟六问、点击展开"""
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
U = "file:///" + os.path.join(os.path.dirname(HERE), "live", "index.html").replace("\\", "/")

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 1000}, device_scale_factor=2)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    pg.goto(U, wait_until="domcontentloaded")
    pg.wait_for_timeout(2500)

    r = {}
    r["has"] = pg.locator(".bk").count()
    r["rows"] = pg.eval_on_selector_all(".bkr .m",
        "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())")
    # 点第一条
    pg.eval_on_selector(".bkr", "e=>e.click()")
    pg.wait_for_timeout(500)
    r["open"] = pg.eval_on_selector_all(".bkdet.on", "e=>e.length")
    r["nav_svg"] = pg.eval_on_selector_all(".bkdet .nav polyline", "e=>e.length")
    r["g3"] = pg.eval_on_selector_all(".bkdet .g3 .v", "e=>e.map(x=>x.textContent.trim())")
    r["pos"] = pg.eval_on_selector(".bkdet .pos", "e=>e.innerText.replace(/\\s+/g,' ').trim()")
    r["trades"] = pg.eval_on_selector_all(".bkdet .tr div",
        "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())")
    r["six"] = pg.eval_on_selector_all(".bkdet .six .qi",
        "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())")
    body = pg.eval_on_selector("body", "e=>e.innerText")
    r["undef"] = body.count("undefined")
    pg.locator(".bk").screenshot(path=os.path.join(HERE, "_bk.png"))
    b.close()

print("账本区块:", r["has"], "｜展开详情:", r["open"], "｜净值曲线:", r["nav_svg"])
print("\n四行:")
for x in r["rows"]:
    print("  ", x)
print("\n三格收益:", r["g3"])
print("持仓    :", r["pos"])
print("最近交易:")
for x in r["trades"]:
    print("  ", x)
print("\n龟龟六问:")
for x in r["six"]:
    print("  ", x[:150])
print("\nundefined:", r["undef"], "｜ JS 错误:", errs or "无")
