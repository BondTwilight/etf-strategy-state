# -*- coding: utf-8 -*-
"""诊断：手机页点「完整看台」到底发生了什么"""
from playwright.sync_api import sync_playwright

BASE = "https://etf-strategy-live.app.workbuddy.host"
SC = "?sharecode=XWQ352NNVN"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844})
    p = c.new_page()
    reqs, fails = [], []
    p.on("request", lambda r: reqs.append(r.url) if "hub" in r.url else None)
    p.on("requestfailed", lambda r: fails.append((r.url, r.failure)))
    p.on("response", lambda r: reqs.append("RESP %s %s" % (r.status, r.url)) if "hub.html" in r.url else None)
    p.goto(BASE + "/" + SC, wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(4000)
    print("href =", p.eval_on_selector("#hubnav", "e=>e.getAttribute('href')"))
    print("abs  =", p.eval_on_selector("#hubnav", "e=>e.href"))
    p.locator("#hubnav").click()
    p.wait_for_timeout(5000)
    print("after click url =", p.url)
    print("title =", p.title())
    print("body head =", p.eval_on_selector("body", "e=>e.innerText.slice(0,120).replace(/\\s+/g,' ')"))
    print("reqs =", reqs[-5:])
    print("fails =", fails[-3:])
    b.close()
