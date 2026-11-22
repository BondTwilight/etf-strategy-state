# -*- coding: utf-8 -*-
"""公网最终验证 v2：分享码传递 + 行业强弱 + 恒方新鲜度 + 两页不溢出"""
import os

from playwright.sync_api import sync_playwright

BASE = "https://etf-strategy-live.app.workbuddy.host"
SC = "?sharecode=XWQ352NNVN"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 Mobile/15E148")

out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch()

    # ---------- 1. 手机页 ----------
    ctx = b.new_context(viewport={"width": 390, "height": 844}, user_agent=UA,
                        device_scale_factor=2)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.goto(BASE + "/" + SC, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(7000)
    m = {
        "sw": pg.evaluate("() => document.documentElement.scrollWidth"),
        "hubnav": pg.eval_on_selector("#hubnav", "e=>e.getAttribute('href')"),
        "ind_rows": pg.locator("#ind table tbody tr[data-k]").count(),
        "ind_txt": pg.eval_on_selector("#ind", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:90],
        "intel_rows": pg.locator("#intel table tbody tr").count(),
        "intel_txt": pg.eval_on_selector("#intel", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:120],
        "cards": pg.locator(".card").count(),
        "undefined": pg.eval_on_selector("body", "e=>e.innerText").count("undefined"),
        "NaN": pg.eval_on_selector("body", "e=>e.innerText").count("NaN"),
        "errs": errs[:3],
    }
    pg.locator("#ind").screenshot(path="_pub_ind.png")
    pg.locator("#intel").screenshot(path="_pub_hf.png")
    # 点「完整看台」：必须当场打开浮层，而不是顶层跳转
    pg.locator("#hubnav").click()
    pg.wait_for_timeout(4500)
    m["hv"] = pg.eval_on_selector("#hubview", "e=>e.className")
    fr = None
    for f in pg.frames:
        if "hub.html" in (f.url or ""):
            fr = f
    m["hv_frame"] = (fr.title() if fr else "NO FRAME")[:40]
    m["hv_sections"] = fr.eval_on_selector_all("[id^=sec-]", "e=>e.length") if fr else 0
    pg.screenshot(path="_pub_hubview.png")
    ctx.close()

    # ---------- 2. 看台（手机视口） ----------
    ctx2 = b.new_context(viewport={"width": 390, "height": 844}, user_agent=UA,
                         device_scale_factor=2)
    pg2 = ctx2.new_page()
    errs2 = []
    pg2.on("pageerror", lambda e: errs2.append(str(e)[:160]))
    pg2.goto(BASE + "/hub.html" + SC, wait_until="domcontentloaded", timeout=60000)
    pg2.wait_for_timeout(6000)
    h = {
        "sw": pg2.evaluate("() => document.documentElement.scrollWidth"),
        "vw": pg2.evaluate("() => document.documentElement.clientWidth"),
        "sections": pg2.eval_on_selector_all("[id^=sec-]", "e=>e.length"),
        "ind_rows": pg2.locator("#indtable tbody tr").count(),
        "mobnav": pg2.eval_on_selector("#mobnav", "e=>e.getAttribute('href')"),
        "hf_tag": pg2.eval_on_selector("#hf-tag", "e=>e.textContent.trim()"),
        "undefined": pg2.eval_on_selector("body", "e=>e.innerText").count("undefined"),
        "NaN": pg2.eval_on_selector("body", "e=>e.innerText").count("NaN"),
        "errs": errs2[:3],
    }
    pg2.locator("#sec-ind").screenshot(path="_pub_ind_desk.png")
    ctx2.close()
    b.close()

print("=== 手机页 / ===")
for k, v in m.items():
    print("  %-10s %s" % (k, v))
print("\n=== 看台 /hub.html ===")
for k, v in h.items():
    print("  %-10s %s" % (k, v))

ok = (m["sw"] == 390 and m["intel_rows"] == 11 and m["ind_rows"] >= 8
      and "sharecode" in (m["hubnav"] or "")
      and m["hv"] == "hv on" and m["hv_sections"] >= 10
      and h["sw"] == h["vw"] and h["sections"] >= 12 and h["ind_rows"] >= 15
      and "sharecode" in (h["mobnav"] or "")
      and m["undefined"] == 0 and h["undefined"] == 0
      and m["NaN"] == 0 and h["NaN"] == 0
      and not m["errs"] and not h["errs"])
print("\n" + ("公网检查通过 ✅" if ok else "存在问题 ❌"))
