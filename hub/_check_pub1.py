# -*- coding: utf-8 -*-
"""公网单页验证：11 个区块都在、没有 iframe、锚点能跳、无溢出、无报错。"""
from playwright.sync_api import sync_playwright

URL = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    for w in (390, 1280):
        c = b.new_context(viewport={"width": w, "height": 900})
        p = c.new_page()
        errs = []
        p.on("pageerror", lambda e: errs.append(str(e)[:160]))
        p.on("console", lambda m: errs.append("console:" + m.text[:120]) if m.type == "error" else None)
        p.goto(URL, wait_until="domcontentloaded", timeout=90000)
        p.wait_for_timeout(5000)
        info = p.evaluate("""() => {
          const ids=['hero','cards','weather','flow','matrix','predict','books','intel','health','rules','caliber'];
          const miss = ids.filter(i=>!document.getElementById(i) ||
                        !(document.getElementById(i).innerText||'').trim());
          return {miss, sw:document.documentElement.scrollWidth,
                  vw:document.documentElement.clientWidth,
                  h:document.documentElement.scrollHeight,
                  iframe:document.querySelectorAll('iframe').length,
                  chn:document.querySelectorAll('.chn-i').length,
                  mx:document.querySelectorAll('.mx tbody td').length,
                  und:(document.body.innerText.match(/undefined/g)||[]).length,
                  nan:(document.body.innerText.match(/NaN/g)||[]).length};
        }""")
        # 点「矩阵」锚点，验证能滚过去
        p.click("#navx a[href='#matrix']")
        p.wait_for_timeout(900)
        top = p.evaluate("() => document.getElementById('matrix').getBoundingClientRect().top")
        print("%dpx  缺失=%s 溢出=%s 高=%d iframe=%s 链=%s 矩阵格=%s und=%s nan=%s 跳转后 top=%.0f errs=%s"
              % (w, info["miss"], info["sw"] - info["vw"], info["h"], info["iframe"],
                 info["chn"], info["mx"], info["und"], info["nan"], top, errs[:2]))
        c.close()
    b.close()
