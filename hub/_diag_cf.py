# -*- coding: utf-8 -*-
"""_diag_cf.py —— 定位 OFF 卡在 loading 的原因"""
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
U = "file:///" + os.path.abspath(os.path.join(ROOT, "live", "index.html")).replace("\\", "/")

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.on("console", lambda m: print("  [console.%s] %s" % (m.type, m.text[:160])))
    pg.on("pageerror", lambda e: print("  [pageerror] %s" % str(e)[:160]))
    pg.goto(U, wait_until="domcontentloaded")
    pg.wait_for_timeout(6000)

    print("\n--- 直接调用 CF.myRunning ---")
    print(pg.evaluate("""async () => {
        try {
            const r = await CF.myRunning();
            return { ok: true, type: typeof r, n: (r || []).length,
                     first: r && r[0] ? Object.keys(r[0]).slice(0,6) : null };
        } catch (e) { return { ok: false, err: String(e && e.message || e) }; }
    }"""))

    print("\n--- 直接调用 CF.spot ---")
    print(pg.evaluate("""async () => {
        try {
            const s = await CF.spot(['515020']);
            const c = Object.keys(s || {});
            return { ok: true, n: c.length, iopv: c.length ? s[c[0]].iopv : null };
        } catch (e) { return { ok: false, err: String(e && e.message || e) }; }
    }"""))

    print("\n--- 状态 ---")
    print(pg.evaluate("""() => ({
        hasKey: CF.hasKey(), keyLen: (D.cloud && D.cloud.cifangKey || '').length,
        offState: OFF.state, offErr: OFF.err, offN: OFF.n, offPrem: OFF.prem,
        stats: CF.stats(),
    })"""))

    print("\n--- 手动跑一次 refreshOfficial ---")
    print(pg.evaluate("""async () => {
        try { await refreshOfficial(); return { state: OFF.state, n: OFF.n, err: OFF.err }; }
        catch (e) { return { throw: String(e && e.message || e) }; }
    }"""))
    b.close()
