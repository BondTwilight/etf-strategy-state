# -*- coding: utf-8 -*-
"""单页版自检：区块是否都在、有没有 JS 报错、手机上有没有横向溢出。"""
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HERE, "..", "live", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    for w, tag in ((390, "手机"), (1280, "桌面")):
        c = b.new_context(viewport={"width": w, "height": 900})
        p = c.new_page()
        errs = []
        p.on("pageerror", lambda e: errs.append(str(e)[:200]))
        p.on("console", lambda m: errs.append("console:" + m.text[:120]) if m.type == "error" else None)
        p.goto(URL, wait_until="domcontentloaded", timeout=60000)
        p.wait_for_timeout(2500)
        info = p.evaluate("""() => {
          const ids = ['hero','cards','weather','flow','matrix','predict','books','intel','health','rules','caliber'];
          const out = {};
          ids.forEach(id => {
            const e = document.getElementById(id);
            out[id] = e ? (e.innerText || '').replace(/\\s+/g,' ').trim().slice(0,90) : 'MISSING';
          });
          return {
            ids: out,
            sw: document.documentElement.scrollWidth,
            vw: document.documentElement.clientWidth,
            navlinks: document.querySelectorAll('#navx a').length,
            chnSteps: document.querySelectorAll('.chn-i').length,
            mxRows: document.querySelectorAll('.mx tbody tr').length,
            mxCells: document.querySelectorAll('.mx tbody td').length,
            hfRows: document.querySelectorAll('#intel tbody tr').length,
            undefined: (document.body.innerText.match(/undefined/g) || []).length,
            nan: (document.body.innerText.match(/NaN/g) || []).length,
            iframe: document.querySelectorAll('iframe').length,
            title: document.title
          };
        }""")
        print("=== %s %dpx ===" % (tag, w))
        print("  sw/vw=%s/%s iframe=%s nav=%s" % (info["sw"], info["vw"], info["iframe"], info["navlinks"]))
        print("  chain=%s  matrix rows=%s cells=%s  hf rows=%s"
              % (info["chnSteps"], info["mxRows"], info["mxCells"], info["hfRows"]))
        print("  undefined=%s NaN=%s errs=%s" % (info["undefined"], info["nan"], errs[:3]))
        for k, v in info["ids"].items():
            print("  %-8s %s" % (k, v[:86]))
        c.close()
    b.close()
