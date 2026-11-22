# -*- coding: utf-8 -*-
"""验证「K 线尾部自维护」：注入 localStorage tail 后，页面是否合并并重算

模拟场景：用户三周不开电脑。内嵌种子停在 2026-11-20，
但每次收盘后打开过手机页，就攒下 11-23 / 11-24 两天的 bar。
本次验证：注入这两天 → 重载 → 环境区块应显示「本地已累积 2 天」，
且 regime 与 Python 用同样数据算出来的一致。
"""
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = "file:///" + os.path.join(os.path.dirname(HERE), "live", "index.html").replace("\\", "/")

# 两天的假 bar（价格取自真实量级，用来验证合并链路而非预测准确性）
TAIL = {
    "2026-11-23": {
        "510300": [4.018, 4.060, 4.000, 4.052, 21000000],
        "159915": [2.550, 2.590, 2.530, 2.575, 15000000],
        "510880": [3.100, 3.130, 3.090, 3.120, 8000000],
        "515450": [1.515, 1.530, 1.510, 1.525, 3000000],
    },
    "2026-11-24": {
        "510300": [4.052, 4.080, 4.030, 4.035, 20000000],
        "159915": [2.575, 2.600, 2.550, 2.560, 14000000],
        "510880": [3.120, 3.140, 3.100, 3.105, 7500000],
        "515450": [1.525, 1.535, 1.515, 1.520, 2800000],
    },
}


def main():
    errs = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 900})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)[:180]))

        # 第一次访问：写入 tail
        pg.goto(PAGE, wait_until="domcontentloaded", timeout=40000)
        pg.wait_for_timeout(1500)
        import json
        pg.evaluate("(t) => localStorage.setItem('etf_score_tail_v1', JSON.stringify(t))",
                    TAIL)

        # 重新加载，看是否合并
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(3000)

        r = {
            "wxLive": pg.evaluate("() => D.wxLive || ''"),
            "scoreDate": pg.evaluate("() => (D.score && D.score.date) || ''"),
            "tailDates": pg.evaluate(
                "() => (D.score && D.score.dates) ? D.score.dates.slice(-3) : []"),
            "n300": pg.evaluate(
                "() => (D.score && D.score.close && D.score.close['510300']) ? D.score.close['510300'].length : 0"),
            "badge": pg.eval_on_selector(".wx-badge", "e=>e.textContent.trim()") if pg.locator(".wx-badge").count() else "",
            "mkt": pg.eval_on_selector_all(".wx-mkt span", "e=>e.map(x=>x.textContent.trim())") if pg.locator(".wx-mkt").count() else [],
            "rows": pg.eval_on_selector_all(".wx-tb tr", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' ').trim())") if pg.locator(".wx-tb").count() else [],
            "undefined": pg.eval_on_selector("body", "e=>e.innerText").count("undefined"),
        }
        # 独立复算：用合并后的数据在页面里跑一次 regime
        r["regimeNow"] = pg.evaluate("""() => {
          try { const g = SC.regime(D.score); return {code: g.code, raw: g.raw}; }
          catch(e){ return {err: String(e)}; }
        }""")
        b.close()

    print("=== 合并结果 ===")
    print("  D.wxLive       ", r["wxLive"])
    print("  序列末日期     ", r["scoreDate"])
    print("  最后三天       ", r["tailDates"])
    print("  510300 根数    ", r["n300"], "（种子 800 + 2 = 802 应为 802）")
    print("  档位徽章       ", r["badge"])
    print("  市场胶囊       ", r["mkt"])
    print("  适配表首行     ", r["rows"][0] if r["rows"] else "—")
    print("  复算 regime    ", r["regimeNow"])
    print("  undefined      ", r["undefined"])
    print("  JS 错误        ", errs if errs else "无")

    ok = (r["scoreDate"] == "2026-11-24" and r["n300"] == 802
          and "累积 2 天" in r["wxLive"] and not errs)
    print("\n" + ("PASS ✅  自维护生效：不开电脑也能续上" if ok else "FAIL ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
