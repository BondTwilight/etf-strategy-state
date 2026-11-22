# -*- coding: utf-8 -*-
"""次方量化官方 API 客户端（x-api-key 鉴权）

Key 存放：_localdata/cifang_api_key.txt（禁止写入前端/仓库）
限额：除 back-test 外 60 次/分/IP/接口；批量取数请用多代码参数。
"""
import json
import os
import time
import urllib.parse
import urllib.request

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "_localdata", "cifang_api_key.txt")
KEY_FILE2 = os.path.join(ROOT, "_localdata", "cifang_api_key.txt")
BASE = "https://www.cifangquant.com/api"

_cache = {}


def api_key():
    # CI（GitHub Actions）用环境变量注入，本地仍读文件
    k = (os.environ.get("CIFANG_KEY") or os.environ.get("CIFANG_API_KEY") or "").strip()
    if k:
        return k
    for p in (KEY_FILE2, KEY_FILE):
        if os.path.exists(p):
            k = open(p, encoding="utf-8").read().strip()
            if k:
                return k
    raise RuntimeError("未找到 API Key：请写入 _localdata/cifang_api_key.txt "
                       "或设置环境变量 CIFANG_KEY")


def _req(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-api-key": api_key(),
                                               "User-Agent": "Mozilla/5.0"})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("code") == 0:
                return d.get("data")
            raise RuntimeError("API 业务错误 %s: %s" % (path, d.get("message")))
        except Exception as e:            # 429 / 网络抖动 → 退避
            last = e
            code = getattr(e, "code", None)
            if code == 401:
                raise RuntimeError("API Key 无效或已失效（401）") from e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("API 调用失败 %s: %r" % (path, last))


def get(path, **params):
    return _req(path, params or None)


def post(path, body):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"x-api-key": api_key(),
                                          "Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("code") != 0:
        raise RuntimeError("API 业务错误 %s: %s" % (path, d.get("message")))
    return d.get("data")


# ------------------------------------------------------------------ 行情
HIST_COLS = ["date", "open", "close", "high", "low", "chg", "volume", "amount", "iopv"]


def hist(symbols, start, end, adjust="none", chunk=45):
    """返回 {code: DataFrame}；DataFrame 索引为日期，列含 IOPV。"""
    if isinstance(symbols, str):
        symbols = [symbols]
    out = {}
    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]
        d = get("/fund/hist_em", symbol=",".join(part), start_date=start,
                end_date=end, adjust=adjust)
        for code, rows in (d or {}).items():
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=HIST_COLS)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            for c in ("open", "close", "high", "low", "volume", "amount", "iopv"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            out[code] = df
    return out


def spot(symbols):
    """实时/最近收盘快照：last、iopv、五档量价。"""
    if isinstance(symbols, str):
        symbols = [symbols]
    out = {}
    for i in range(0, len(symbols), 50):
        part = symbols[i:i + 50]
        d = get("/fund/spot", symbol=",".join(part))
        out.update(d or {})
    return out


def fund_name(codes):
    """代码 → 名称。用 /fund/list 逐个查（接口只支持单关键词）。"""
    names = {}
    for c in codes:
        try:
            d = get("/fund/list", key_word=c)
            for x in (d or []):
                if str(x.get("fund_code")) == str(c):
                    names[str(c)] = x.get("fund_name")
                    break
        except Exception:
            pass
    return names


# ------------------------------------------------------------------ 策略
def my_running():
    return get("/strategy/my-running") or []


def strategy_preview(sid):
    return get("/strategy/preview/%s" % sid)


def rank(start, end=None, top_n=20):
    p = {"start_date": start, "top_n": top_n}
    if end:
        p["end_date"] = end
    return get("/strategy/list/rank", **p) or []


def premium(code, df=None, sp=None):
    """溢价率 = 价格 / IOPV − 1（必须用不复权价）。返回 (当前, 20日中位)。"""
    cur = med = None
    if sp and code in sp and sp[code].get("iopv"):
        s = sp[code]
        cur = (s["last"] / s["iopv"] - 1) * 100
    if df is not None and code in df:
        x = df[code]
        ser = (x["close"] / x["iopv"] - 1).dropna() * 100
        if len(ser):
            med = float(ser.tail(20).median())
            if cur is None:
                cur = float(ser.iloc[-1])
    return cur, med
