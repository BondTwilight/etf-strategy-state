# -*- coding: utf-8 -*-
"""验证 state.json 覆盖链路：本地起个 http 服务，模拟 raw.githubusercontent。"""
import http.server
import json
import os
import shutil
import socketserver
import threading

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP = os.path.join(HERE, "_statetest")
os.makedirs(TMP, exist_ok=True)
shutil.copy(os.path.join(ROOT, "live", "index.html"), os.path.join(TMP, "index.html"))
# 只在测试副本里注入地址，不动真实产物（真实产物由 hub/state_url.txt 决定）
_p = os.path.join(TMP, "index.html")
_h = open(_p, encoding="utf-8").read()
assert '"stateUrl": ""' in _h, "产物里 stateUrl 不是空的，测试前提不成立"
_h = _h.replace('"stateUrl": ""', '"stateUrl": "http://127.0.0.1:8899/state.json"', 1)
open(_p, "w", encoding="utf-8").write(_h)

st = json.load(open(os.path.join(ROOT, "data", "state.json"), encoding="utf-8"))
st["built_at"] = "2026-11-22 19:30"
st["data_date"] = "2026-11-21"
st["action"]["head"] = "【云端覆盖测试】515880 已触发止损"
st["ai_note"] = {"text": "今天要卖 515880，收盘已跌破止损线\n银行整块在涨，广度 100%，不是单只问题\n恒方 9/11 有信号，换仓 2 个",
                 "model": "deepseek-chat", "at": "2026-11-22 19:30"}
json.dump(st, open(os.path.join(TMP, "state.json"), "w", encoding="utf-8"),
          ensure_ascii=False)

os.chdir(TMP)


class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, *a):
        pass


srv = socketserver.TCPServer(("127.0.0.1", 8899), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_context(viewport={"width": 390, "height": 900}).new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)[:160]))
    p.goto("http://127.0.0.1:8899/index.html", wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(3500)
    # 打开一个详情弹层，验证「云端刷新后弹层也跟着重画」
    p.evaluate("openStrat('band96863')")
    p.wait_for_timeout(500)
    out = p.evaluate("""() => ({
      tag: (document.getElementById('statetag')||{}).textContent,
      built: D.built_at, date: D.data_date,
      hero: (document.getElementById('hero')||{}).innerText.replace(/\\s+/g,' ').slice(0,120),
      stateOn: (typeof STATE!=='undefined') ? STATE.on : null,
      err: (typeof STATE!=='undefined') ? STATE.err : null,
      sheetFoot: (document.querySelector('#stbox .note:last-child')||{}).innerText
                 ? document.querySelector('#stbox .note:last-child').innerText.replace(/\\s+/g,' ').slice(-90) : 'NO FOOT',
      sheetTitle: (document.querySelector('#stbox h3')||{}).innerText,
      ai: (document.getElementById('nnote')||{}).innerText
          ? document.getElementById('nnote').innerText.replace(/\\s+/g,' ').slice(0,120) : 'NO AI'
    })""")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print("errs:", errs[:2])
    b.close()

srv.shutdown()
