# -*- coding: utf-8 -*-
"""_shot_link.py —— 联动效果截图（主看台实时条+动作卡 / 手机页卡片）"""
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
U = lambda p: "file:///" + os.path.abspath(p).replace("\\", "/")

with sync_playwright() as p:
    b = p.chromium.launch()

    # 主看台
    pg = b.new_page(viewport={"width": 1560, "height": 1100}, device_scale_factor=1.5)
    pg.goto(U(os.path.join(HERE, "index.html")), wait_until="load")
    pg.wait_for_timeout(4500)
    el = pg.locator("#live")
    el.scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    el.screenshot(path=os.path.join(HERE, "_vb_livebar.png"))
    print("saved _vb_livebar.png")
    a = pg.locator("#action")
    a.scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    a.screenshot(path=os.path.join(HERE, "_vb_action.png"))
    print("saved _vb_action.png")
    # 打开等股灾弹窗检查「手机看」
    pg.evaluate("() => openModal('bank96864')")
    pg.wait_for_timeout(600)
    pg.locator("#mbox").screenshot(path=os.path.join(HERE, "_vb_modal.png"))
    print("saved _vb_modal.png")
    pg.close()

    # 手机页
    pg = b.new_page(viewport={"width": 390, "height": 1000}, device_scale_factor=2)
    pg.goto(U(os.path.join(ROOT, "live", "index.html")), wait_until="load")
    pg.wait_for_timeout(4500)
    pg.evaluate("""() => {
        const c=[...document.querySelectorAll('.card')].find(x=>x.dataset.code==='515880');
        if(c) c.querySelector('.tog').click();
    }""")
    pg.wait_for_timeout(500)
    pg.screenshot(path=os.path.join(HERE, "_vb_mob.png"), full_page=False)
    print("saved _vb_mob.png")
    pg.close()
    b.close()
