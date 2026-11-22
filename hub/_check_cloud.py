# -*- coding: utf-8 -*-
"""_check_cloud.py —— 云服务接入验证

两段：
  1. file://   预期「云端未连」——验证降级不崩、内嵌数据照常渲染
  2. 公网 URL  预期「云端快照已生效」或「云端已连」——验证真的读到了库
"""
import os
import sys
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FILE_URL = "file:///" + os.path.abspath(os.path.join(ROOT, "live", "index.html")).replace("\\", "/")
PUB_URL = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"


def probe(url, tag, wait=14000):
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 1000}, device_scale_factor=2)
        pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
        pg.on("console", lambda m: errs.append("CONSOLE:" + m.text) if m.type == "error" else None)
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(wait)

        out = {
            "cloudbar": pg.eval_on_selector("#cloud", "e=>e.innerText.replace(/\\s+/g,' ')") if pg.locator("#cloud .cloudbar").count() else "(无)",
            "dot_on": pg.eval_on_selector_all("#cloud .cloudbar .dot.on", "e=>e.length"),
            "cards": pg.eval_on_selector_all(".card", "e=>e.length"),
            "codes": pg.eval_on_selector_all(".card", "e=>e.map(x=>x.dataset.code)"),
            "cost_515020": pg.evaluate("""() => {const c=[...document.querySelectorAll('.card')].find(x=>x.dataset.code==='515020');
                const m=c&&c.querySelector('.lg'); return m?m.innerText.replace(/\\s+/g,' '):'';}"""),
        }
        body = pg.eval_on_selector("body", "e=>e.innerText")
        out["undefined"] = body.count("undefined")
        out["nan"] = body.count("NaN")
        out["err"] = errs[:4]
        b.close()

    print("=====", tag)
    for k, v in out.items():
        print("  %-12s %s" % (k, v))
    return out


if __name__ == "__main__":
    probe(FILE_URL, "file:// （预期降级）")
    if "--pub" in sys.argv:
        probe(PUB_URL, "公网（预期云端生效）", wait=16000)
