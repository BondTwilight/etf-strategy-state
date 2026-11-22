# -*- coding: utf-8 -*-
"""_probe_browser_cors.py —— 在真实浏览器（公网 https 页面）里测三个行情源

urllib 测出的结果与浏览器实测矛盾，所以只信浏览器。
测试环境：https://etf-strategy-live.app.workbuddy.host/ 的页面上下文
"""
from playwright.sync_api import sync_playwright

URL = "https://etf-strategy-live.app.workbuddy.host/?sharecode=XWQ352NNVN"

JS = r"""
async () => {
  const out = {};

  async function tryFetch(name, url, opt) {
    const t0 = Date.now();
    try {
      const r = await fetch(url, opt || { cache: 'no-store' });
      const txt = await r.text();
      out[name] = { ok: r.ok, status: r.status, len: txt.length,
                    ms: Date.now() - t0, head: txt.slice(0, 90) };
    } catch (e) {
      out[name] = { ok: false, err: String(e.message || e).slice(0, 90), ms: Date.now() - t0 };
    }
  }

  // ① 腾讯 ifzq 历史 K 线
  await tryFetch('tx_ifzq',
    'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh515020,day,,,60,qfq&_=' + Date.now());

  // ② 东财 push2his 历史 K 线（补全参数，之前 data:null 是参数不全）
  await tryFetch('em_hist',
    'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.515020&klt=101&fqt=1'
    + '&beg=0&end=20500101&lmt=60'
    + '&fields1=f1,f2,f3,f4,f5,f6'
    + '&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&_=' + Date.now());

  // ③ 次方 hist_em（带 Key）。注意 const D 不挂 window，必须用 typeof 判断
  const k = (typeof D !== 'undefined' && D.cloud && D.cloud.cifangKey) || '';
  out.keyLen = k.length;
  await tryFetch('cf_hist',
    'https://www.cifangquant.com/api/fund/hist_em?symbol=515020&start_date=2026-08-01&end_date=2026-11-22&adjust=qfq',
    { cache: 'no-store', headers: { 'x-api-key': k } });

  // ④ 次方 spot（对照：已知能用）
  await tryFetch('cf_spot',
    'https://www.cifangquant.com/api/fund/spot?symbol=515020',
    { cache: 'no-store', headers: { 'x-api-key': k } });

  return out;
}
"""

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    res = pg.evaluate(JS)
    b.close()

print("=" * 96)
for k, v in res.items():
    if not isinstance(v, dict):
        print("%-10s %s" % (k, v))
        continue
    if v.get("ok"):
        print("%-10s ✅ status=%s len=%s ms=%s  %s"
              % (k, v["status"], v["len"], v["ms"], v["head"][:60]))
    else:
        print("%-10s ❌ %s  (%sms)" % (k, v.get("err") or v.get("status"), v.get("ms")))
print("=" * 96)
