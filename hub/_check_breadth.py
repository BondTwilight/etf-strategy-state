# -*- coding: utf-8 -*-
"""验证多市场广度 + 风险偏好"""
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
U = "file:///" + os.path.join(os.path.dirname(HERE), "live", "index.html").replace("\\", "/")

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 1200}, device_scale_factor=2)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:180]))
    pg.goto(U, wait_until="domcontentloaded")
    pg.wait_for_timeout(2500)

    r = {}
    r["has"] = pg.locator(".wx-bd").count()
    r["head"] = pg.eval_on_selector(".wx-bd .bh", "e=>e.innerText.replace(/\\s+/g,' ').trim()") if r["has"] else ""
    r["dots"] = pg.eval_on_selector_all(".wx-bd .dt", "e=>e.map(x=>x.className)") if r["has"] else []
    r["list"] = pg.eval_on_selector_all(".wx-bd .li", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())") if r["has"] else []
    r["risk"] = pg.eval_on_selector(".wx-bd .risk", "e=>e.innerText.replace(/\\s+/g,' ').trim()") if pg.locator(".wx-bd .risk").count() else ""

    # 用 SC 直接复算，交叉核对
    r["api"] = pg.evaluate("""() => {
      try {
        const bd = SC.breadth(D.score.close);
        const ro = SC.riskOn(D.score.close);
        return {bd: bd ? {n: bd.n, up: bd.up, pct: bd.pct} : null, ro: ro};
      } catch(e) { return {err: String(e)}; }
    }""")

    body = pg.eval_on_selector("body", "e=>e.innerText")
    r["undef"] = body.count("undefined")
    pg.locator(".wx").screenshot(path=os.path.join(HERE, "_wx4.png"))
    b.close()

print("广度区块:", r["has"])
print("标题行  :", r["head"])
print("小方块  :", "".join("R" if "u" in (d or "") else "G" for d in r["dots"]))
print("明细    :")
for x in r["list"]:
    print("   ", x)
print("风险偏好:", r["risk"])
print("API 复算:", r["api"])
print("undefined:", r["undef"], "｜ JS 错误:", errs or "无")
