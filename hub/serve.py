# -*- coding: utf-8 -*-
"""serve.py —— 本地实时服务（看板 + 行情代理 + 巡检日志 + 一键重算）

为什么需要它
------------
看板是单文件 HTML，`file://` 打开时浏览器会拦掉跨域请求，拿不到实时价。
起一个本地小服务（只用标准库，不装任何依赖）就能：
  GET  /                 看板（index.html）
  GET  /api/quote        ?codes=515880,510300 → 实时价 + 涨跌 + 距止损
  GET  /api/guard        今日巡检日志（最后 40 行）
  GET  /api/health       心跳 / 数据日
  POST /api/refresh      先跑 _platform.py（真实持仓+市场状态）再重建看板

用法
----
  python serve.py                默认 http://127.0.0.1:8899
  python serve.py 9000           指定端口
  python serve.py 8899 --open    起来后自动开浏览器

注意
----
- 只绑 127.0.0.1，局域网访问不到；要外网请自己加反代 + 鉴权。
- 看板里有持仓金额，**不要直接发布到公网**。
"""
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
DIP = os.path.join(ROOT, "etf_dip_signal")
PY = sys.executable or r"D:\python\python.exe"

sys.path.insert(0, DIP)

_refresh_lock = threading.Lock()


def _qt(codes):
    """腾讯 qt 实时快照（与 web_quote 同源，这里直连避免引入 pandas 开销）"""
    out = {}
    if not codes:
        return out
    for i in range(0, len(codes), 50):
        batch = codes[i:i + 50]
        q = ",".join(("sh" if c[0] in "56" else "sz") + c for c in batch)
        req = urllib.request.Request("https://qt.gtimg.cn/q=" + q,
                                     headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                txt = r.read().decode("gbk", errors="ignore")
        except Exception:
            continue
        for line in txt.split(";"):
            line = line.strip()
            if '="' not in line:
                continue
            body = line.split('="', 1)[1].rstrip('"')
            f = body.split("~")
            if len(f) < 40:
                continue
            code = f[2]
            try:
                price = float(f[3])
                prev = float(f[4])
            except Exception:
                continue
            out[code] = {
                "code": code, "name": f[1], "price": price, "pre_close": prev,
                "open": float(f[5] or 0), "high": float(f[33] or 0),
                "low": float(f[34] or 0),
                "chg": round((price / prev - 1) * 100, 2) if prev else None,
                "amount": float(f[37] or 0) * 1e4,
                "time": f[30] if len(f) > 30 else "",
                "paused": price <= 0,
            }
    return out


class H(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass                      # 静音，别刷屏

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path, qs = u.path, urllib.parse.parse_qs(u.query)

        if path == "/api/health":
            hj = os.path.join(BASE, "hub.json")
            meta = {}
            try:
                meta = (json.load(open(hj, encoding="utf-8")) or {}).get("meta") or {}
            except Exception:
                pass
            return self._json({"ok": True, "data_date": meta.get("data_date"),
                               "built_at": meta.get("built_at")})

        if path == "/api/quote":
            codes = [c.strip() for c in (qs.get("codes", [""])[0] or "").split(",") if c.strip()]
            q = _qt(codes)
            return self._json({"ok": True, "ts": __import__("time").strftime("%H:%M:%S"),
                               "data": q})

        if path == "/api/guard":
            import datetime
            p = os.path.join(DIP, "信号输出",
                             "guard_%s.log" % datetime.date.today().strftime("%Y-%m-%d"))
            lines = []
            if os.path.exists(p):
                lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()[-40:]
            return self._json({"ok": True, "date": datetime.date.today().strftime("%Y-%m-%d"),
                               "lines": lines})

        if path in ("/", "/index.html"):
            self.path = "/index.html"
            return SimpleHTTPRequestHandler.do_GET(self)

        return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != "/api/refresh":
            return self._json({"ok": False, "err": "not found"}, 404)
        if not _refresh_lock.acquire(blocking=False):
            return self._json({"ok": False, "err": "已有一次重算在跑，等它结束"}, 429)
        try:
            logs = []
            for script, args in (("_platform.py", []), ("hub_build.py", [])):
                cwd = DIP if script == "_platform.py" else BASE
                r = subprocess.run([PY, script] + args, cwd=cwd,
                                   capture_output=True, text=True, timeout=600)
                tail = (r.stdout or "")[-400:] + (r.stderr or "")[-400:]
                logs.append("%s → rc=%d\n%s" % (script, r.returncode, tail))
                if r.returncode != 0:
                    return self._json({"ok": False, "log": "\n\n".join(logs)})
            return self._json({"ok": True, "log": "\n\n".join(logs)})
        except Exception as e:
            return self._json({"ok": False, "err": repr(e)})
        finally:
            _refresh_lock.release()


def main():
    port = 8899
    for a in sys.argv[1:]:
        if a.isdigit():
            port = int(a)
    os.chdir(BASE)                 # 以 hub/ 为静态根
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print("看板：http://127.0.0.1:%d/" % port)
    print("行情：http://127.0.0.1:%d/api/quote?codes=515880,510300" % port)
    if "--open" in sys.argv:
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:%d/" % port)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
