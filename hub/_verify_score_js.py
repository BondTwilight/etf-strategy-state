# -*- coding: utf-8 -*-
"""在真实浏览器里跑 score_core.js，与 Python 基准逐位对比

做法：生成一个临时测试页（内联 score_core.js + fixture），
不掺进正式产物，避免污染。任何一项偏差 > 1e-3 就报 FAIL。
"""
import io
import json
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = io.open(os.path.join(HERE, "score_core.js"), encoding="utf-8").read()
FIX = io.open(os.path.join(HERE, "_score_fixture.json"), encoding="utf-8").read()
EXP = json.load(io.open(os.path.join(HERE, "_score_expect.json"), encoding="utf-8"))

HTML = """<!doctype html><meta charset="utf-8"><title>score_core test</title>
<body><pre id="out">running</pre>
<script>
%s
</script>
<script>
const SD = %s;
const out = {};
try {
  // 1. 市场状态
  const ms = SC.marketState(SD);
  const m = ms['510300'];
  out.market = m ? { ind: m.ind, score: { total: m.score.total, state: m.score.state,
      conf: m.score.conf, dims: m.score.dims.map(function(d){return {k:d.k, v:d.v};}) } } : null;
  // 2. 环境判据
  const rg = SC.regime(SD);
  out.regime = rg.ok ? { code: rg.code, items: rg.items, raw: rg.raw } : { err: rg.err };
} catch (e) { out.error = String(e) + ' | ' + (e.stack||'').split('\\n')[1]; }
document.getElementById('out').textContent = JSON.stringify(out);
window.__RESULT__ = out;
</script></body>"""


def cmp_num(label, a, b, tol=1e-3):
    if a is None and b is None:
        print("  OK   %-22s 两边都是 None" % label)
        return True
    if a is None or b is None:
        print("  FAIL %-22s py=%r js=%r（一边缺值）" % (label, a, b))
        return False
    d = abs(float(a) - float(b))
    ok = d <= tol
    print("  %s %-22s py=%-12.6g js=%-12.6g Δ=%.2e"
          % ("OK  " if ok else "FAIL", label, float(a), float(b), d))
    return ok


def main():
    p = os.path.join(HERE, "_score_test.html")
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(HTML % (CORE, FIX))

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
        pg.goto("file:///" + p.replace("\\", "/"), wait_until="load", timeout=30000)
        pg.wait_for_timeout(500)
        res = pg.evaluate("() => window.__RESULT__ || null")
        b.close()

    if errs:
        print("JS 报错：", errs)
    if not res:
        print("FAIL 页面没有产出结果")
        return 1
    if res.get("error"):
        print("FAIL 计算抛错：", res["error"])
        return 1

    allok = True
    print("\n=== 1. 市场状态检测器（510300）===")
    e, g = EXP["market"], res.get("market") or {}
    if not g:
        print("  FAIL JS 没算出市场状态")
        allok = False
    else:
        for k in ("MA5", "MA10", "MA20", "MA60", "DIF", "DEA", "RSI",
                  "ATR", "BOLL_bw", "vol_ratio", "vol5", "vol20", "ret5", "ATR_chg"):
            allok &= cmp_num(k, e["ind"].get(k), (g.get("ind") or {}).get(k))
        allok &= cmp_num("score.total", e["score"]["total"], (g.get("score") or {}).get("total"))
        allok &= cmp_num("score.conf", e["score"]["conf"], (g.get("score") or {}).get("conf"))
        ss = (g.get("score") or {}).get("state")
        ok = ss == e["score"]["state"]
        print("  %s %-22s py=%s js=%s" % ("OK  " if ok else "FAIL", "score.state",
                                          e["score"]["state"], ss))
        allok &= ok
        ed = {x["k"]: x["v"] for x in e["score"]["dims"]}
        gd = {x["k"]: x["v"] for x in ((g.get("score") or {}).get("dims") or [])}
        for k in ed:
            allok &= cmp_num("dim." + k, ed[k], gd.get(k))

    print("\n=== 2. 环境判据 ===")
    er, gr = EXP["regime"], res.get("regime") or {}
    ok = gr.get("code") == er["code"]
    print("  %s %-22s py=%s js=%s" % ("OK  " if ok else "FAIL", "regime.code",
                                      er["code"], gr.get("code")))
    allok &= ok
    raw = gr.get("raw") or {}
    mp = {"dev": "dev", "vp": "vp", "gmd": "gmd", "dDev": "dDev"}
    for k, jk in mp.items():
        allok &= cmp_num(k, er[k], raw.get(jk))

    print("\n" + ("全部通过 ✅  JS 与 Python 逐位一致" if allok else "存在偏差 ❌ 必须修 JS"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
