# -*- coding: utf-8 -*-
"""抓公网页面上到底哪个请求失败了（只看失败，不看成功）。"""
from playwright.sync_api import sync_playwright

URL = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844})
    p = c.new_page()
    bad = []
    p.on("requestfailed", lambda r: bad.append(("FAIL", r.url[:120], r.failure or "")))
    p.on("response", lambda r: bad.append(("HTTP", r.status, r.url[:120]))
         if r.status >= 400 else None)
    p.goto(URL, wait_until="domcontentloaded", timeout=90000)
    p.wait_for_timeout(6000)
    seen = set()
    for x in bad:
        k = str(x)
        if k in seen:
            continue
        seen.add(k)
        print(x)
    print("--- 页面状态 ---")
    print(p.evaluate("""() => ({
      ts: (document.getElementById('ts')||{}).textContent,
      dot: (document.getElementById('dot')||{}).className,
      chk: (document.getElementById('chk')||{}).textContent,
      tag: (document.getElementById('statetag')||{}).textContent
    })"""))
    c.close()
    b.close()
