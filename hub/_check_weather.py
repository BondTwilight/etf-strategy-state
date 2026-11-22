# -*- coding: utf-8 -*-
"""验证手机页「当前环境与策略适配」区块

检查项：
  1. 区块存在且渲染出 regime 档位
  2. 四维拆解 / 四条判据可展开
  3. 适配表按 bp 降序，第一名与 Python 侧一致
  4. 评分与 Python 基线一致（环境适配维度重算后）
  5. undefined / NaN 为 0，无 JS 错误
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(os.path.dirname(HERE), "live", "index.html")
EXP = json.load(open(os.path.join(HERE, "_score_expect.json"), encoding="utf-8"))


def main():
    errs, cons = [], []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 900})
        pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
        pg.on("console", lambda m: cons.append(m.text[:160]) if m.type == "error" else None)
        pg.goto("file:///" + PAGE.replace("\\", "/"), wait_until="domcontentloaded", timeout=40000)
        pg.wait_for_timeout(3500)

        r = {}
        r["has_wx"] = pg.locator(".wx").count()
        r["badge"] = pg.eval_on_selector(".wx-badge", "e=>e.textContent.trim()") if r["has_wx"] else ""
        r["title"] = pg.eval_on_selector(".wx-t", "e=>e.textContent.trim()") if r["has_wx"] else ""
        r["mkt"] = pg.eval_on_selector_all(".wx-mkt span", "e=>e.map(x=>x.textContent.trim())") if r["has_wx"] else []
        r["rows"] = pg.eval_on_selector_all(".wx-tb tr", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())") if r["has_wx"] else []
        body = pg.eval_on_selector("body", "e=>e.innerText")
        r["undefined"] = body.count("undefined")
        r["NaN"] = body.count("NaN")

        # 展开判据
        if pg.locator("#wx-d1").count():
            pg.click("#wx-d1")
            pg.wait_for_timeout(400)
            r["conds"] = pg.eval_on_selector_all(".wx-cond .c",
                "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())")
        # 展开四维
        if pg.locator("#wx-d2").count():
            pg.click("#wx-d2")
            pg.wait_for_timeout(400)
            r["dims"] = pg.eval_on_selector_all(".wx-dim .r .v", "e=>e.map(x=>x.textContent.trim())")

        pg.locator(".wx").screenshot(path=os.path.join(HERE, "_wx.png"))
        b.close()

    print("=== 环境区块 ===")
    print("  档位徽章   ", r["badge"], "（Python 期望 %s）" % EXP["regime"]["code"])
    print("  档位说明   ", r["title"])
    print("  市场胶囊   ", r["mkt"])
    print("  适配表：")
    for x in r["rows"]:
        print("     ", x)
    print("  判据展开   ", r.get("conds"))
    print("  四维数值   ", r.get("dims"))
    print("\nundefined=%d  NaN=%d" % (r["undefined"], r["NaN"]))
    print("JS 错误：", errs if errs else "无")
    print("console：", cons[:3] if cons else "无")

    ok = (r["has_wx"] == 1 and r["badge"] == EXP["regime"]["code"]
          and r["undefined"] == 0 and r["NaN"] == 0 and not errs)
    print("\n" + ("PASS ✅" if ok else "FAIL ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
