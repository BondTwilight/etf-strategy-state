# -*- coding: utf-8 -*-
"""_hub_diag.py —— 诊断 sparkline 缺失"""
import os

from playwright.sync_api import sync_playwright

HUB = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HUB, "index.html").replace("\\", "/")
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1500, "height": 1100})
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(500)
    info = pg.evaluate("""() => {
      const out = [];
      document.querySelectorAll('#strategies .card').forEach(c => {
        const nm = c.querySelector('.nm').textContent;
        const svg = c.querySelector('svg.spark');
        out.push({
          nm,
          hasSvg: !!svg,
          paths: svg ? svg.querySelectorAll('path').length : 0,
          h: svg ? svg.getBoundingClientRect().height : null,
          w: svg ? svg.getBoundingClientRect().width : null,
          cardH: c.getBoundingClientRect().height,
          d: svg ? (svg.querySelector('path') ? svg.querySelector('path').getAttribute('d').slice(0,60) : null) : null
        });
      });
      return out;
    }""")
    for x in info:
        print(x)
    b.close()
