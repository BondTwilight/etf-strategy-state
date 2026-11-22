# -*- coding: utf-8 -*-
"""
cifang_api.py —— 次方量化行情客户端（VIP 会员接口）

用途：给本地回测与信号脚本提供**真前复权**的 ETF 全历史日线。
      腾讯 ifzq 会 501 限流并静默退化到新浪不复权，次方这套是稳定替代。

鉴权：请求头 x-api-key
限流：其余接口 = 同一 IP + 同一接口 60 次/分钟，允许突发 10 次
      批量拉取必须用多代码参数（单次最多 50 只），不要逐只发请求。

⚠️ API Key 等同账号凭证：勿提交仓库、勿外发。
"""
import json
import time
import os
import urllib.request
import urllib.parse

import pandas as pd

API_KEY = (os.environ.get("CIFANG_KEY")
           or "ak_REPLACE_WITH_SECRET")
BASE = "https://www.cifangquant.com/api"
MAX_SYMBOLS_PER_CALL = 50

COLS = ["date", "open", "close", "high", "low", "pct_chg", "volume", "amount", "iopv"]


class RateLimited(Exception):
    pass


def _get(path, params=None, retry=3):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(retry + 1):
        req = urllib.request.Request(url, headers={"x-api-key": API_KEY})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = json.loads(r.read().decode("utf-8"))
            if body.get("code") != 0:
                raise RuntimeError("业务码=%s msg=%s" % (body.get("code"), body.get("message")))
            return body.get("data")
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:                      # 限流 → 退避重试
                time.sleep(2 + i * 3)
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(1 + i * 2)
    raise RuntimeError("请求失败 %s: %s" % (url, last))


def fund_list(key_word=None):
    return _get("/fund/list", {"key_word": key_word} if key_word else None)


def hist_em(symbols, start_date, end_date, adjust="qfq"):
    """批量日线。返回 {code: DataFrame(date/index, open/high/low/close/vol/amount)}。"""
    if isinstance(symbols, str):
        symbols = [symbols]
    symbols = [str(s) for s in symbols]
    out = {}
    for i in range(0, len(symbols), MAX_SYMBOLS_PER_CALL):
        batch = symbols[i:i + MAX_SYMBOLS_PER_CALL]
        data = _get("/fund/hist_em", {
            "symbol": ",".join(batch),
            "start_date": str(start_date),
            "end_date": str(end_date),
            "adjust": adjust,
        }) or {}
        for code, rows in data.items():
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=COLS[:len(rows[0])])
            df = df[["date", "open", "close", "high", "low", "volume", "amount"]].copy()
            for c in ("open", "close", "high", "low", "volume", "amount"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df["date"] = df["date"].astype(str).str[:10]
            out[str(code)] = df.dropna(subset=["close"]).reset_index(drop=True)
        time.sleep(0.6)          # 主动降速，远离 60/min 红线
    return out


def fetch_pool_history(codes, start="2015-01-01", end="2026-10-20",
                       cache_path=None, force=False):
    """拉全池历史并做本地 parquet 缓存。返回 {code: DataFrame}。"""
    if cache_path and os.path.exists(cache_path) and not force:
        df = pd.read_parquet(cache_path)
        return {c: g.reset_index(drop=True) for c, g in df.groupby("code")}

    print("[次方API] 拉取 %d 只 ETF 日线（qfq）%s ~ %s，分 %d 批..." % (
        len(codes), start, end, (len(codes) + 49) // 50))
    t0 = time.time()
    raw = hist_em(codes, start, end, adjust="qfq")
    print("[次方API] 返回 %d/381 只，耗时 %.1fs" % (len(raw), time.time() - t0))

    frames = []
    for code, df in raw.items():
        d = df.copy()
        d["code"] = code
        frames.append(d[["code", "date", "open", "close", "high", "low", "volume", "amount"]])
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        pd.concat(frames, ignore_index=True).to_parquet(cache_path, index=False)
        print("[次方API] 已缓存 -> %s" % cache_path)
    return {c: g.drop(columns=["code"]).reset_index(drop=True)
            for c, g in pd.concat(frames, ignore_index=True).groupby("code")}


if __name__ == "__main__":
    import sys
    pool = json.load(open("data/fixed_pool.json", encoding="utf-8"))["codes"]
    cache = os.path.join("data", "etf_qfq_cifang.parquet")
    force = "--force" in sys.argv
    d = fetch_pool_history(pool, cache_path=cache, force=force)
    lens = sorted(len(v) for v in d.values())
    print("只数=%d 行数 min/median/max = %d/%d/%d" % (
        len(d), lens[0], lens[len(lens) // 2], lens[-1]))
    miss = [c for c in pool if c not in d]
    print("缺失代码 %d 只: %s" % (len(miss), miss[:20]))
