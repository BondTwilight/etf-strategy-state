# -*- coding: utf-8 -*-
import os
import json
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HERE, "..", "live", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 900})
    p = c.new_page()
    p.goto(URL, wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(3000)
    out = p.evaluate("""() => {
      const it = (D.items||[]).find(x=>x.code==='515880');
      const live = (typeof LIVE!=='undefined' && LIVE['515880']) ? LIVE['515880'].price : null;
      const j = LC.judge(it, live);
      const el = document.querySelector('[data-dist="515880"]');
      return {item: it, live: live, judge: j,
              domText: el ? el.textContent.trim() : null,
              domColor: el ? getComputedStyle(el).color : null};
    }""")
    print(json.dumps(out, ensure_ascii=False, indent=1)[:1600])
    c.close()
    b.close()
