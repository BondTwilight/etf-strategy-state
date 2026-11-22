# -*- coding: utf-8 -*-
"""_check_pub2.py —— 验证公网手机页（联动版）"""
import os
from playwright.sync_api import sync_playwright

URL = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"
HERE = os.path.dirname(os.path.abspath(__file__))

errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 1000}, device_scale_factor=2)
    pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
    pg.on("console", lambda m: errs.append("CONSOLE:" + m.text) if m.type == "error" else None)
    pg.goto(URL, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(6000)

    print("卡片数      ", pg.eval_on_selector_all(".card", "e=>e.length"))
    print("实时状态    ", pg.eval_on_selector("#ts", "e=>e.textContent"))
    print("绿点        ", pg.eval_on_selector_all(".hd .dot.on", "e=>e.length"))
    print("判定徽章    ", pg.eval_on_selector_all(".card [data-g]", "e=>e.filter(x=>x.style.display!=='none').map(x=>x.textContent)"))
    print("距止损      ", pg.evaluate("""() => { const o={};
        document.querySelectorAll('.card').forEach(c=>{const d=c.querySelector('[data-dist]');
          if(d) o[c.dataset.code]=d.textContent.trim();}); return o; }"""))

    pg.evaluate("""() => {
        const c=[...document.querySelectorAll('.card')].find(x=>x.dataset.code==='515880');
        if(c && !c.classList.contains('open')) c.querySelector('.tog').click();
    }""")
    pg.wait_for_timeout(500)
    txt = pg.evaluate("""() => { const c=[...document.querySelectorAll('.card')].find(x=>x.dataset.code==='515880');
        const m=c&&c.querySelector('.more'); return m?m.innerText.replace(/\\s+/g,' ').slice(0,200):'(none)'; }""")
    print("515880 依据 ", txt)

    body = pg.eval_on_selector("body", "e=>e.innerText")
    print("undefined   ", body.count("undefined"))
    print("NaN         ", body.count("NaN"))
    print("JS 错误     ", errs or "无")

    pg.screenshot(path=os.path.join(HERE, "_vc_pub.png"))
    b.close()
