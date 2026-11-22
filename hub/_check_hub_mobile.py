# -*- coding: utf-8 -*-
"""手机视口实测 hub.html，找出「看不了」的具体原因

逐段检查：横向溢出、字号、区块宽度、折叠状态、需要横向滚动的表。
"""
import json
import os

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(os.path.dirname(HERE), "live", "hub.html")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 844},
                    device_scale_factor=2,
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                               "AppleWebKit/605.1.15 Mobile/15E148")
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.goto("file:///" + PAGE.replace("\\", "/"), wait_until="domcontentloaded", timeout=40000)
    pg.wait_for_timeout(3000)

    r = pg.evaluate("""() => {
      const vw = document.documentElement.clientWidth;
      const sw = document.documentElement.scrollWidth;
      const bad = [];
      document.querySelectorAll('body *').forEach(el => {
        const b = el.getBoundingClientRect();
        if (b.width > 0 && b.right > vw + 2) {
          const t = (el.className && typeof el.className === 'string') ? el.className.split(' ')[0] : el.tagName;
          if (bad.length < 14) bad.push({tag: el.tagName, cls: t,
            w: Math.round(b.width), right: Math.round(b.right),
            txt: (el.innerText||'').replace(/\\s+/g,' ').slice(0,40)});
        }
      });
      // 需要横向滚动的容器
      const scrollers = [];
      document.querySelectorAll('body *').forEach(el => {
        if (el.scrollWidth > el.clientWidth + 4 && el.clientWidth > 0) {
          const t = (el.className && typeof el.className === 'string') ? el.className.split(' ')[0] : el.tagName;
          if (scrollers.length < 10) scrollers.push({cls: t,
            cw: el.clientWidth, sw: el.scrollWidth,
            txt: (el.innerText||'').replace(/\\s+/g,' ').slice(0,36)});
        }
      });
      const fs = getComputedStyle(document.body).fontSize;
      return {vw, sw, overflow: sw - vw, bad, scrollers, bodyFont: fs,
              h1: (document.querySelector('h1') ? document.querySelector('h1').innerText : ''),
              navLinks: document.querySelectorAll('.nav a').length};
    }""")
    print(json.dumps(r, ensure_ascii=False, indent=1))
    print("JS 错误：", errs if errs else "无")

    pg.screenshot(path=os.path.join(HERE, "_hub_m_top.png"))
    for sel, nm in (("#sec-chain", "_hub_m_chain.png"), ("#sec-mx", "_hub_m_mx.png"),
                    ("#sec-strat", "_hub_m_strat.png")):
        if pg.locator(sel).count():
            pg.locator(sel).scroll_into_view_if_needed()
            pg.wait_for_timeout(250)
            pg.locator(sel).screenshot(path=os.path.join(HERE, nm))
    b.close()
