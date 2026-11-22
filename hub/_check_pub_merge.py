# -*- coding: utf-8 -*-
"""_check_pub_merge.py —— 公网验证：手机页 ↔ 完整看台 是否真的互通、脱敏是否生效"""
import os
import re
from playwright.sync_api import sync_playwright

BASE = "https://etf-strategy-live.app.workbuddy.host"
MOB = BASE + "/?sharecode=XWQ352NNVN"
HUB = BASE + "/hub.html?sharecode=XWQ352NNVN"
HERE = os.path.dirname(os.path.abspath(__file__))

with sync_playwright() as p:
    b = p.chromium.launch()

    # ---------- 手机页 ----------
    errs = []
    pg = b.new_page(viewport={"width": 390, "height": 900}, device_scale_factor=2)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(MOB, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(15000)
    print("===== 手机页 (/) =====")
    print("  卡片数     ", pg.eval_on_selector_all(".card", "e=>e.length"))
    print("  云服务条   ", pg.eval_on_selector("#cloud", "e=>e.innerText.replace(/\\s+/g,' ')")
          if pg.locator("#cloud .cloudbar").count() else "(无)")
    print("  完整看台   ", pg.eval_on_selector("#hubnav", "e=>e.getAttribute('href')"))
    print("  实时状态   ", pg.eval_on_selector("#ts", "e=>e.textContent"))
    body = pg.eval_on_selector("body", "e=>e.innerText")
    print("  undefined  ", body.count("undefined"))
    print("  JS错误     ", errs[:2] or "无")
    pg.screenshot(path=os.path.join(HERE, "_vd_mob.png"))
    pg.close()

    # ---------- 完整看台 ----------
    errs2 = []
    pg = b.new_page(viewport={"width": 1560, "height": 1000})
    pg.on("pageerror", lambda e: errs2.append(str(e)))
    pg.goto(HUB, wait_until="load", timeout=60000)
    pg.wait_for_timeout(6000)
    print("===== 完整看台 (/hub.html) =====")
    print("  标题       ", pg.eval_on_selector("h1", "e=>e.innerText.replace(/\\s+/g,' ')"))
    print("  脱敏提示   ", pg.eval_on_selector(".masknote", "e=>e.innerText.replace(/\\s+/g,' ').slice(0,90)"))
    print("  实时监控链 ", pg.eval_on_selector(".nav a.ext", "e=>e.getAttribute('href')"))
    print("  实时条     ", "有" if pg.locator(".livebar").count() else "无")
    # 真实持仓表里份额那一列是否已打码
    amt = pg.evaluate("() => {const r=(D.real_positions||[])[0]; return r?{code:r.code, amount:r.amount, pnl:r.pnl, stop:r.stop}:null;}")
    print("  持仓样本   ", amt)
    body2 = pg.eval_on_selector("body", "e=>e.innerText")
    print("  undefined  ", body2.count("undefined"))
    print("  NaN        ", body2.count("NaN"))
    print("  JS错误     ", errs2[:2] or "无")
    pg.screenshot(path=os.path.join(HERE, "_vd_hub.png"))
    pg.close()
    b.close()
