# -*- coding: utf-8 -*-
"""_check_predict.py —— 验证调仓预测在纯静态页里跑通（file://，无本机）"""
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
U = "file:///" + os.path.abspath(os.path.join(ROOT, "live", "index.html")).replace("\\", "/")

errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 1400}, device_scale_factor=2)
    pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
    pg.on("console", lambda m: errs.append("CONSOLE:" + m.text) if m.type == "error" else None)
    pg.goto(U, wait_until="domcontentloaded")
    # 等预测算完（20 只 K 线）
    for _ in range(20):
        pg.wait_for_timeout(1000)
        st = pg.evaluate("() => (typeof PRED !== 'undefined' ? PRED.state : 'missing')")
        if st in ("ok", "fail"):
            break

    print("PRED.state  ", pg.evaluate("() => (typeof PRED !== 'undefined' ? PRED.state : 'none')"))
    print("PRED.at     ", pg.evaluate("() => (typeof PRED !== 'undefined' ? PRED.at : '')"))
    print("区块文本    ", pg.eval_on_selector("#predict", "e=>e.innerText.replace(/\\s+/g,' ').slice(0,300)")
          if pg.locator("#predict .pred").count() else "(无)")

    detail = pg.evaluate("""() => {
        const d = PRED.data; if (!d) return null;
        return (d.strategies||[]).map(s => ({
            id: s.id, action: s.action, reason: (s.reason||'').slice(0,60),
            top: s.top ? s.top.code : null, passN: s.passN, poolN: s.poolN,
            target: s.target, score: s.score,
            gates: s.gates ? s.gates.map(g=>g.k+':'+(g.hit?'HIT':'ok')) : null,
        }));
    }""")
    print("\n四条策略预测：")
    for x in (detail or []):
        print("  %-12s %-7s top=%-7s pass=%-6s score=%-7s %s"
              % (x["id"], x["action"], x["top"], "%s/%s" % (x["passN"], x["poolN"]),
                 x["score"], x["reason"]))

    body = pg.eval_on_selector("body", "e=>e.innerText")
    print("\nundefined   ", body.count("undefined"))
    print("NaN         ", body.count("NaN"))
    print("JS 错误     ", errs[:3] or "无")
    print("卡片数      ", pg.eval_on_selector_all(".card", "e=>e.length"))

    pg.screenshot(path=os.path.join(HERE, "_ve_predict.png"))
    b.close()
