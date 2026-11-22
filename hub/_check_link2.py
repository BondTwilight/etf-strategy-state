# -*- coding: utf-8 -*-
"""_check_link2.py —— 主看台 × 手机页 联动验证

验证五件事：
1. 两页在 file:// 下都能自取实时价（不需要任何后端）
2. 两页对同一持仓算出同一个「距止损」（证明判定同源）
3. 手机页卡片能展开依据（今日指令 / 九维 / 风控口径）
4. 主看台策略弹窗有「手机看 →」深链
5. 零 JS 错误、零 undefined、零 NaN
"""
import os
import re
import sys
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def url_of(p):
    return "file:///" + os.path.abspath(p).replace("\\", "/")


HUB = url_of(os.path.join(HERE, "index.html"))
MOB = url_of(os.path.join(ROOT, "live", "index.html"))


def check_hub(pg):
    out = {}
    out["dot_on"] = pg.eval_on_selector_all(".livebar .dot.on", "e=>e.length")
    out["src"] = pg.eval_on_selector(".livebar .ts:nth-of-type(2)", "e=>e.textContent") if pg.locator(".livebar .ts").count() > 1 else ""
    out["gates"] = pg.eval_on_selector_all(".livebar .gb", "e=>e.map(x=>x.textContent)")
    # 距止损数字（与手机页比对用）
    out["dist"] = pg.evaluate("""() => {
        const o={};
        document.querySelectorAll('.livebar .it').forEach(el=>{
          const c=el.querySelector('.c').textContent.trim();
          const d=el.querySelectorAll('.d')[1];
          if(d) o[c]=d.textContent.replace('距止损 ','').trim();
        });
        return o;
    }""")
    out["mobile_links"] = pg.eval_on_selector_all(".livebar .mobb", "e=>e.length")
    # 策略弹窗里的深链：直接检查 D.meta.mobile_url 是否注入
    out["has_mobile_url"] = pg.evaluate("() => !!(D.meta && D.meta.mobile_url)")
    # 今日动作卡的实时校验行
    out["planchk"] = pg.eval_on_selector_all(".planchk", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' '))")
    body = pg.eval_on_selector("body", "e=>e.innerText")
    out["undefined"] = body.count("undefined")
    out["nan"] = body.count("NaN")
    return out


def check_mobile(pg):
    out = {}
    out["cards"] = pg.eval_on_selector_all(".card", "e=>e.length")
    out["dot_on"] = pg.eval_on_selector_all(".hd .dot.on", "e=>e.length")
    out["ts"] = pg.eval_on_selector("#ts", "e=>e.textContent")
    out["gates"] = pg.eval_on_selector_all(".card [data-g]", "e=>e.filter(x=>x.style.display!=='none').map(x=>x.textContent)")
    out["dist"] = pg.evaluate("""() => {
        const o={};
        document.querySelectorAll('.card').forEach(el=>{
          const c=el.dataset.code;
          const d=el.querySelector('[data-dist]');
          if(d) o[c]=d.textContent.trim();
        });
        return o;
    }""")
    out["alerts"] = pg.eval_on_selector_all(".alb", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' '))")
    # 专门展开 515880（有今日动作「卖出」的那张）看「今日指令」是否齐全
    pg.evaluate("""() => {
        const c=[...document.querySelectorAll('.card')].find(x=>x.dataset.code==='515880');
        if(c && !c.classList.contains('open')) c.querySelector('.tog').click();
    }""")
    pg.wait_for_timeout(350)
    out["plan_515880"] = pg.evaluate("""() => {
        const c=[...document.querySelectorAll('.card')].find(x=>x.dataset.code==='515880');
        const m=c&&c.querySelector('.more');
        return m ? m.innerText.replace(/\\s+/g,' ').slice(0,260) : '(none)';
    }""")
    # 94744 是否合并在 513290 卡上
    out["also_badges"] = pg.eval_on_selector_all(".card .badge.fb", "e=>e.map(x=>x.textContent)")
    # 横幅能否真的出现（注入一条假告警）
    pg.evaluate("""() => { ALERTS=[{kind:'bad',code:'515020',txt:'【测试】515020 已跌破止损'}]; paintAlerts(); }""")
    pg.wait_for_timeout(200)
    out["alert_injected"] = pg.eval_on_selector_all(".alb.bad", "e=>e.map(x=>x.innerText.replace(/\\s+/g,' '))")
    # 再展开第一张卡（截图用）
    pg.locator(".card .tog").first.click()
    pg.wait_for_timeout(400)
    out["open"] = pg.eval_on_selector_all(".card.open", "e=>e.length")
    out["more_text"] = pg.eval_on_selector(".card.open .more", "e=>e.innerText.replace(/\\s+/g,' ').slice(0,240)") if pg.locator(".card.open .more").count() else "(none)"
    body = pg.eval_on_selector("body", "e=>e.innerText")
    out["undefined"] = body.count("undefined")
    out["nan"] = body.count("NaN")
    return out


def main():
    errs_h, errs_m = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()

        pg = b.new_page(viewport={"width": 1560, "height": 1000})
        pg.on("pageerror", lambda e: errs_h.append(str(e)))
        pg.on("console", lambda m: errs_h.append("CONSOLE:" + m.text) if m.type == "error" else None)
        pg.goto(HUB, wait_until="load")
        pg.wait_for_timeout(4500)
        H = check_hub(pg)
        pg.close()

        pg = b.new_page(viewport={"width": 390, "height": 900}, device_scale_factor=2)
        pg.on("pageerror", lambda e: errs_m.append(str(e)))
        pg.on("console", lambda m: errs_m.append("CONSOLE:" + m.text) if m.type == "error" else None)
        pg.goto(MOB, wait_until="load")
        pg.wait_for_timeout(4500)
        M = check_mobile(pg)
        pg.locator(".card").first.screenshot(path=os.path.join(HERE, "_va_mob_card.png"))
        pg.screenshot(path=os.path.join(HERE, "_va_mob_top.png"))
        pg.close()
        b.close()

    print("========== 主看台 hub/index.html ==========")
    for k, v in H.items():
        print("  %-14s %s" % (k, v))
    print("  js_err         %s" % (errs_h or "无"))

    print("========== 手机页 live/index.html ==========")
    for k, v in M.items():
        print("  %-14s %s" % (k, v))
    print("  js_err         %s" % (errs_m or "无"))

    print("========== 判定同源校验 ==========")
    ok = True
    for c in set(H["dist"]) & set(M["dist"]):
        a = H["dist"][c].replace("%", "").strip()
        bb = M["dist"][c].replace("%", "").strip()
        same = a == bb
        ok = ok and same
        print("  %-8s 主看台 %-9s 手机页 %-9s %s" % (c, a, bb, "一致" if same else "不一致 ✗"))
    print("  ⇒ %s" % ("两页判定同源" if ok else "存在不一致，需排查"))


if __name__ == "__main__":
    main()
