# -*- coding: utf-8 -*-
"""_check_cf.py —— 验证浏览器直连次方 API（这是整件事的关键）

测两种 origin：
  file://            → Origin: null
  http://127.0.0.1   → Origin: http://127.0.0.1:8899（serve.py 在跑）
看两种情况下 my-running / spot 能不能真的取到数据。
"""
import os
import sys
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FILE_URL = "file:///" + os.path.abspath(os.path.join(ROOT, "live", "index.html")).replace("\\", "/")
HTTP_URL = "http://127.0.0.1:8899/../live/index.html"   # 仅当 serve 能映射，通常不通


def run(url, tag):
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 1000})
        pg.on("pageerror", lambda e: errs.append("PAGEERROR:" + str(e)))
        pg.on("console", lambda m: (errs.append("CONSOLE:" + m.text)
                                    if m.type == "error" and "ERR_EMPTY" not in m.text else None))
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        for _ in range(25):
            pg.wait_for_timeout(1000)
            st = pg.evaluate("() => (typeof OFF !== 'undefined' ? OFF.state : 'missing')")
            if st in ("ok", "fail", "nokey"):
                break

        print("=====", tag)
        print("  OFF.state   ", pg.evaluate("() => (typeof OFF !== 'undefined' ? OFF.state : 'missing')"))
        print("  OFF.err     ", pg.evaluate("() => (typeof OFF !== 'undefined' ? OFF.err : '')"))
        print("  OFF.at      ", pg.evaluate("() => (typeof OFF !== 'undefined' ? OFF.at : '')"))
        print("  官方持仓条数 ", pg.evaluate("() => (typeof OFF !== 'undefined' ? OFF.n : -1)"))
        print("  溢价覆盖只数 ", pg.evaluate("() => (typeof OFF !== 'undefined' ? OFF.prem : -1)"))
        print("  CF.stats    ", pg.evaluate("() => (typeof CF !== 'undefined' ? CF.stats() : null)"))
        print("  premMap 样本 ", pg.evaluate("""() => {
            const pm = (typeof D !== 'undefined' && D.premMap) || {};
            return Object.entries(pm).slice(0, 6);
        }"""))
        print("  持仓(cost)  ", pg.evaluate("""() => {
            return ((typeof D !== 'undefined' && D.items) || []).map(x => x.code + '@' + x.cost);
        }"""))
        print("  云服务条    ", pg.eval_on_selector("#cloud", "e=>e.innerText.replace(/\\s+/g,' ').slice(0,140)")
              if pg.locator("#cloud .cloudbar").count() else "(无)")
        print("  JS错误      ", errs[:3] or "无")
        b.close()


if __name__ == "__main__":
    run(FILE_URL, "file:// （Origin: null）")
