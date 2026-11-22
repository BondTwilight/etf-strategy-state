# -*- coding: utf-8 -*-
"""_verify_predict.py —— 验证 predict_core.js 与 Python 公式逐位一致

方法：同一份腾讯 qfq K 线，Python 用 wslope_v2 算一遍，
浏览器用 PC.wslope 算一遍，比 score。数据同源、同时刻，差异只能来自公式。
"""
import json
import math
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0"}
MOMO_POOL = ["518880", "159509", "588000", "501225", "513100", "513310",
             "159915", "162719", "159985", "513030", "513290", "513520"]
BAND_POOL = ["162411", "513100", "161128", "588000", "162415", "515450"]


def txid(c):
    return ("sh" if c[0] in "56" else "sz") + c


def kline(code, n=60):
    u = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,%d,qfq"
         % (txid(code), n))
    r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=15)
    j = json.loads(r.read())
    d = j.get("data", {}).get(txid(code)) or {}
    rows = d.get("qfqday") or d.get("day") or []
    return [{"d": x[0], "o": float(x[1]), "c": float(x[2]),
             "h": float(x[3]), "l": float(x[4]), "v": float(x[5])} for x in rows]


def wslope_v2(close, n):
    """照抄 _platform.py 38-56 行"""
    y = list(close[-n:])
    if len(y) < n or any((not math.isfinite(v)) or v <= 0 for v in y):
        return None
    x = list(range(n))
    w = [(1 + i / n) ** 2 for i in x]
    sw = sum(w)
    mx = sum(w[i] * x[i] for i in x) / sw
    my = sum(w[i] * y[i] for i in x) / sw
    sxx = sum(w[i] * (x[i] - mx) ** 2 for i in x)
    if sxx <= 0:
        return None
    slope = sum(w[i] * (x[i] - mx) * (y[i] - my) for i in x) / sxx
    ann = math.exp(slope * 250) - 1
    ssr = sum(w[i] * (y[i] - (my + slope * (x[i] - mx))) ** 2 for i in x)
    sst = sum(w[i] * (y[i] - my) ** 2 for i in x)
    r2 = 1 - ssr / sst if sst > 0 else 0
    return ann * max(r2, 0)


def ret_n(close, n):
    if len(close) <= n:
        return None
    return close[-1] / close[-1 - n] - 1


def main():
    # ---- Python 侧 ----
    data, py = {}, {}
    for c in MOMO_POOL + BAND_POOL + ["159552"]:
        k = kline(c, 60)
        data[c] = k
        cl = [x["c"] for x in k]
        py[c] = {
            "n": len(k),
            "last": cl[-1],
            "s20": wslope_v2(cl, 20),
            "s10": wslope_v2(cl, 10),
            "r20": ret_n(cl, 20),
            "r26": ret_n(cl, 26),
            "r19": ret_n(cl, 19),
            "ma10": sum(cl[-10:]) / 10 if len(cl) >= 10 else None,
        }

    momo_rows = []
    for c in MOMO_POOL:
        p = py[c]
        if p["s20"] is None:
            continue
        ok = (p["r20"] is not None and p["r20"] * 100 >= 1
              and p["r26"] is not None and p["r26"] * 100 >= 1
              and 0 <= p["s20"] <= 3.0)
        momo_rows.append({"code": c, "score": round(p["s20"], 6),
                          "r20": round(p["r20"] * 100, 2) if p["r20"] is not None else None,
                          "pass": ok})
    momo_rows.sort(key=lambda x: -x["score"])
    print("===== Python 侧 momo 排序（腾讯 qfq，11-20 收盘）=====")
    for r in momo_rows:
        print("  %-7s score=%-9.6f r20=%-7s %s"
              % (r["code"], r["score"], r["r20"], "PASS" if r["pass"] else ""))
    print("  通过双滤：%d 只" % sum(1 for r in momo_rows if r["pass"]))

    # ---- 生成测试页（内嵌同一份 K 线）----
    page = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<script src="live_core.js"></script>
<script src="predict_core.js"></script>
<script>
const DATA = __DATA__;
window.RESULT = null;
(function(){
  const out = {};
  for (const c in DATA) {
    const cl = DATA[c].map(x => x.c);
    const s20 = PC.wslope(cl, 20), s10 = PC.wslope(cl, 10);
    out[c] = {
      n: DATA[c].length,
      last: cl[cl.length-1],
      s20: s20 ? s20.score : null,
      s10: s10 ? s10.score : null,
      r20: PC.retN(cl, 20), r26: PC.retN(cl, 26), r19: PC.retN(cl, 19),
      ma10: PC.ma(cl, 10),
    };
  }
  window.RESULT = out;
})();
</script></body></html>"""
    tp = os.path.join(HERE, "_test_predict.html")
    with open(tp, "w", encoding="utf-8") as f:
        f.write(page.replace("__DATA__", json.dumps(data, ensure_ascii=False)))

    # ---- 浏览器侧 ----
    from playwright.sync_api import sync_playwright
    url = "file:///" + tp.replace("\\", "/")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(url, wait_until="load")
        pg.wait_for_timeout(800)
        js = pg.evaluate("() => window.RESULT")
        b.close()

    # ---- 对比 ----
    print("\n===== 逐位对比 =====")
    print("  %-7s %-11s %-11s %-9s %-9s %s" % ("code", "py.s20", "js.s20", "Δscore", "py.r20", "结论"))
    worst = 0.0
    for c in MOMO_POOL + BAND_POOL + ["159552"]:
        a, bb = py[c]["s20"], (js.get(c) or {}).get("s20")
        if a is None and bb is None:
            same = "两边都 None"
            d = 0.0
        elif a is None or bb is None:
            same = "⚠ 一边 None"
            d = 999
        else:
            d = abs(a - bb)
            worst = max(worst, d)
            same = "一致" if d < 1e-9 else ("差 %.2e" % d)
        print("  %-7s %-11s %-11s %-9s %-9s %s"
              % (c, "None" if a is None else "%.6f" % a,
                 "None" if bb is None else "%.6f" % bb,
                 "%.2e" % d if d < 900 else "—",
                 "%.4f" % py[c]["r20"] if py[c]["r20"] is not None else "None", same))

    print("\n最大 score 偏差 = %.3e ⇒ %s"
          % (worst, "逐位一致（<1e-9）" if worst < 1e-9 else "⚠ 存在偏差，需排查"))

    # ---- momo 排序是否一致 ----
    js_rows = [{"code": c, "score": js[c]["s20"]} for c in MOMO_POOL
               if js.get(c) and js[c]["s20"] is not None]
    js_rows.sort(key=lambda x: -x["score"])
    same_order = [r["code"] for r in momo_rows] == [r["code"] for r in js_rows]
    print("momo 12 只排序：%s" % ("完全一致" if same_order else "⚠ 不一致"))
    if not same_order:
        print("  py:", [r["code"] for r in momo_rows])
        print("  js:", [r["code"] for r in js_rows])

    os.remove(tp)
    return 0 if worst < 1e-9 and same_order else 1


if __name__ == "__main__":
    raise SystemExit(main())
