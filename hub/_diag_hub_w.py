# -*- coding: utf-8 -*-
"""精确找出把页面撑宽的元素（从最外层往上追）"""
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
    pg.goto("file:///" + PAGE.replace("\\", "/"), wait_until="domcontentloaded", timeout=40000)
    pg.wait_for_timeout(2500)

    r = pg.evaluate("""() => {
      const vw = document.documentElement.clientWidth;
      const out = {vw, docSW: document.documentElement.scrollWidth,
                   bodySW: document.body.scrollWidth};
      // 只看「自己超宽、但父元素不超宽」的（即真正的元凶）
      const roots = [];
      const all = document.querySelectorAll('body *');
      all.forEach(el => {
        const b = el.getBoundingClientRect();
        if (b.width <= vw + 1) return;
        const p = el.parentElement;
        const pb = p ? p.getBoundingClientRect() : null;
        const parentWide = pb && pb.width > vw + 1;
        if (!parentWide && roots.length < 12) {
          const cls = (typeof el.className === 'string' && el.className)
            ? el.className.split(' ').slice(0, 2).join('.') : el.tagName;
          roots.push({tag: el.tagName, cls,
            w: Math.round(b.width), sw: el.scrollWidth, cw: el.clientWidth,
            pos: getComputedStyle(el).position,
            display: getComputedStyle(el).display,
            gtc: getComputedStyle(el).gridTemplateColumns.slice(0, 60),
            txt: (el.innerText || '').replace(/\\s+/g, ' ').slice(0, 50)});
        }
      });
      // 导航自身
      const nav = document.querySelector('.nav');
      const navInfo = nav ? {
        w: Math.round(nav.getBoundingClientRect().width),
        sw: nav.scrollWidth,
        wrap: getComputedStyle(nav).flexWrap,
        display: getComputedStyle(nav).display,
        nA: nav.querySelectorAll('a').length,
      } : null;
      return {out, roots, navInfo};
    }""")

    print("视口 %d ｜ document.scrollWidth %d ｜ body.scrollWidth %d"
          % (r["out"]["vw"], r["out"]["docSW"], r["out"]["bodySW"]))
    print("\n导航：", r["navInfo"])
    print("\n真正超宽的根元素（父元素不超宽）：")
    for x in r["roots"]:
        print("  %-8s .%-22s w=%d scrollW=%d clientW=%d  %s"
              % (x["tag"], x["cls"][:22], x["w"], x["sw"], x["cw"], x["txt"]))
        if x["gtc"] and x["gtc"] != "none":
            print("           grid-template-columns: %s" % x["gtc"])
    b.close()
