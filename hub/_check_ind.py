# -*- coding: utf-8 -*-
"""本地检查：行业强弱区块 + 恒方新鲜度 + 两页不溢出"""
import json
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = "file:///" + os.path.join(ROOT, "hub", "index.html").replace("\\", "/")
LIVE = "file:///" + os.path.join(ROOT, "live", "index.html").replace("\\", "/")
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 Mobile/15E148")

with sync_playwright() as pw:
    b = pw.chromium.launch()

    # ---------- 桌面看台 ----------
    ctx = b.new_context(viewport={"width": 1440, "height": 1000})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    pg.goto(HUB, wait_until="load", timeout=60000)
    pg.wait_for_timeout(2500)
    desk = {
        "ind_rows": pg.locator("#indtable tbody tr").count(),
        "ind_tag": pg.eval_on_selector("#ind-tag", "e=>e.textContent.trim()"),
        "ind_sum": pg.eval_on_selector("#indsum", "e=>e.innerText.trim()")[:160],
        "ind_ctx": pg.eval_on_selector("#indctx", "e=>e.innerText.trim()")[:180],
        "hf_tag": pg.eval_on_selector("#hf-tag", "e=>e.textContent.trim()"),
        "undefined": pg.eval_on_selector("body", "e=>e.innerText").count("undefined"),
        "NaN": pg.eval_on_selector("body", "e=>e.innerText").count("NaN"),
        "errs": errs[:3],
    }
    pg.locator("#sec-ind").scroll_into_view_if_needed()
    pg.wait_for_timeout(400)
    pg.locator("#sec-ind").screenshot(path="_ind_desk.png")
    pg.locator("#indtable tbody tr").first.click()
    pg.wait_for_timeout(500)
    desk["modal"] = pg.eval_on_selector("#mbox", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:220]
    desk["modal_rows"] = pg.locator("#mbox table.trd tbody tr").count()
    pg.screenshot(path="_ind_modal.png")
    ctx.close()

    # ---------- 手机页 ----------
    ctx2 = b.new_context(viewport={"width": 390, "height": 844}, user_agent=UA, device_scale_factor=2)
    pg2 = ctx2.new_page()
    errs2 = []
    pg2.on("pageerror", lambda e: errs2.append(str(e)[:200]))
    pg2.goto(LIVE, wait_until="load", timeout=60000)
    pg2.wait_for_timeout(7000)
    mob = {
        "sw": pg2.evaluate("() => document.documentElement.scrollWidth"),
        "ind_rows": pg2.locator("#ind table tbody tr[data-k]").count(),
        "ind_h": pg2.eval_on_selector("#ind", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:260],
        "intel_rows": pg2.locator("#intel table tbody tr").count(),
        "intel_h": pg2.eval_on_selector("#intel", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:300],
        "chk": pg2.eval_on_selector("#chk", "e=>e.innerText.trim()"),
        "undefined": pg2.eval_on_selector("body", "e=>e.innerText").count("undefined"),
        "NaN": pg2.eval_on_selector("body", "e=>e.innerText").count("NaN"),
        "errs": errs2[:3],
    }
    pg2.locator("#ind").scroll_into_view_if_needed()
    pg2.wait_for_timeout(300)
    pg2.locator("#ind").screenshot(path="_ind_mob.png")
    pg2.locator("#ind tbody tr[data-k]").first.click()
    pg2.wait_for_timeout(300)
    mob["det"] = pg2.eval_on_selector("#inddet", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:200]
    pg2.locator("#ind").screenshot(path="_ind_mob_det.png")
    pg2.locator("#intel").scroll_into_view_if_needed()
    pg2.locator("#intel").screenshot(path="_hf_mob.png")
    if pg2.locator(".card .tog").count():
        pg2.locator(".card .tog").first.click()
        pg2.wait_for_timeout(300)
        mob["card_more"] = pg2.eval_on_selector(".card .more", "e=>e.innerText.replace(/\\s+/g,' ').trim()")[:260]
    ctx2.close()
    b.close()

print("=== 桌面看台 ===")
for k, v in desk.items():
    print("  %-10s %s" % (k, v))
print("\n=== 手机页 ===")
for k, v in mob.items():
    print("  %-10s %s" % (k, v))

ok = (desk["ind_rows"] >= 15 and desk["modal_rows"] >= 3 and mob["ind_rows"] >= 8
      and mob["sw"] == 390 and mob["intel_rows"] == 11
      and desk["undefined"] == 0 and mob["undefined"] == 0
      and desk["NaN"] == 0 and mob["NaN"] == 0
      and not desk["errs"] and not mob["errs"])
print("\n" + ("本地检查通过 ✅" if ok else "存在问题 ❌"))
