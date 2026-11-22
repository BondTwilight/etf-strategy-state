# -*- coding: utf-8 -*-
"""_check_pub_pred.py —— 公网验证：预测能否真的在 https 下跑起来"""
import os
from playwright.sync_api import sync_playwright

URL = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"
HERE = os.path.dirname(os.path.abspath(__file__))

errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 1600}, device_scale_factor=2)
    pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
    pg.on("console", lambda m: errs.append("CONSOLE:" + m.text) if m.type == "error" else None)
    pg.goto(URL, wait_until="domcontentloaded", timeout=60000)

    for _ in range(30):
        pg.wait_for_timeout(1000)
        st = pg.evaluate("() => (typeof PRED !== 'undefined' ? PRED.state : 'missing')")
        if st in ("ok", "fail"):
            break

    print("PRED.state  ", pg.evaluate("() => (typeof PRED !== 'undefined' ? PRED.state : 'missing')"))
    print("PRED.at     ", pg.evaluate("() => (typeof PRED !== 'undefined' ? PRED.at : '')"))
    print("PRED.err    ", pg.evaluate("() => (typeof PRED !== 'undefined' ? PRED.err : '')"))

    acts = pg.evaluate("""() => {
        if (typeof PRED === 'undefined' || !PRED.data) return null;
        return (PRED.data.strategies||[]).map(s => s.id + ':' + s.action);
    }""")
    print("四条动作    ", acts)
    print("次方状态    ", pg.evaluate("() => (typeof OFF !== 'undefined' ? [OFF.state, OFF.n, OFF.prem, OFF.err] : null)"))
    print("CF.stats    ", pg.evaluate("() => (typeof CF !== 'undefined' ? CF.stats() : null)"))
    print("恒方行数    ", pg.eval_on_selector_all(".intel tbody tr", "e=>e.length"))
    print("云端条      ", pg.eval_on_selector("#cloud", "e=>e.innerText.replace(/\\s+/g,' ').slice(0,80)")
          if pg.locator("#cloud .cloudbar").count() else "(无)")
    body = pg.eval_on_selector("body", "e=>e.innerText")
    print("undefined   ", body.count("undefined"))
    print("NaN         ", body.count("NaN"))
    print("JS 错误     ", errs[:3] or "无")

    pg.locator("#predict").screenshot(path=os.path.join(HERE, "_vf_pub_pred.png"))
    b.close()
