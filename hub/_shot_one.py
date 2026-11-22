# -*- coding: utf-8 -*-
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HERE, "..", "live", "index.html").replace("\\", "/")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    p = c.new_page()
    p.goto(URL, wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(2500)
    for sid, name in (("flow", "_one_flow.png"), ("matrix", "_one_mx.png"),
                      ("health", "_one_health.png")):
        el = p.locator("#" + sid)
        el.scroll_into_view_if_needed()
        el.screenshot(path=name)
        print(sid, "->", name)
    # 整页
    p.screenshot(path="_one_full.png", full_page=True)
    print("full ok")
    c.close()
    b.close()
