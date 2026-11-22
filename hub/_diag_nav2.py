# -*- coding: utf-8 -*-
"""诊断2：不同内核 + 点击命中测试"""
from playwright.sync_api import sync_playwright

U = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"

with sync_playwright() as pw:
    for name in ("webkit", "firefox", "chromium"):
        try:
            b = getattr(pw, name).launch()
        except Exception as e:
            print(name, "launch fail", e); continue
        c = b.new_context(viewport={"width": 390, "height": 844})
        p = c.new_page()
        errs = []
        p.on("pageerror", lambda e: errs.append(str(e)[:180]))
        p.goto(U, wait_until="domcontentloaded", timeout=60000)
        p.wait_for_timeout(3500)
        info = p.evaluate("""() => {
            const a = document.getElementById('hubnav');
            if (!a) return {miss:true};
            const r = a.getBoundingClientRect();
            const el = document.elementFromPoint(r.x + r.width/2, r.y + Math.min(r.height/2, 10));
            return {href:a.getAttribute('href'), abs:a.href,
                    top: el ? (el.tagName + '#' + el.id + '.' + el.className) : null,
                    inside: el ? a.contains(el) : false,
                    rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]};
        }""")
        print(name, info, "errs", errs[:2])
        b.close()
