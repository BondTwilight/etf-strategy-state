# -*- coding: utf-8 -*-
"""_hf_fetch.py —— 恒方 11 个产品：每天把信号拉下来，并判定「新不新」

为什么单独一个脚本
------------------
以前 signals.json 只在 hub_build 里顺手抓一次，抓不到就退回本地缓存，
页面只写「信号日」，看不出「这份信号是刚抓的，还是三天前留下的」。
结果就是用户以为它每天在变，其实已经停更 —— 这就是「一次性看板」。

现在把「抓取」和「新鲜度」独立出来：
  · Gitee API v5（Access-Control-Allow-Origin: *，base64）—— 浏览器也能直接调，
    所以手机页即使不重建、不推云，打开就能拿到最新信号
  · 恒方平台 catalog.json（11 个产品的年化/回撤/report/信号时点）
  · 写 _hf_meta.json：signal_date / generated_at / fetched_at / 落后本地几个交易日

口径
----
signal_date = signals.json 里 payload.trade_date 的最大值（**平台的数据日**，
              不是我们本地的数据日；两者差几天就是「信号落后几天」）
generated_at = payload.generated_at（平台最近一次跑策略的时间）
lag_td       = 按工作日算的 signal_date → 本地最新交易日 的间隔
"""
import base64
import datetime
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HF = os.path.join(ROOT, "_localdata", "hf_platform")
SIG_CACHE = os.path.join(HF, "gitee_signals.json")
CAT_CACHE = os.path.join(HF, "catalog.json")
META = os.path.join(HF, "_hf_meta.json")
HIST = os.path.join(HF, "_hf_history.json")

GITEE_API = ("https://gitee.com/api/v5/repos/bolanggu1031/signal/"
             "contents/signals.json")
CAT_URL = ("https://wbapp-j8h0p6es2kpjsngjjvnnad.app.workbuddy.host/"
           "data/catalog.json?sharecode=RC62K4O4GE")

# 本地行情末日的兜底（正常从 parquet 读）
PX = os.path.join(ROOT, "etf_dip_signal", "data", "all_etf_1120.parquet")


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def _data_date():
    """本地最新交易日：优先 parquet 的 max(date)，失败则用 meta 里上次的值"""
    try:
        import pandas as pd
        d = pd.read_parquet(PX, columns=["date"])
        return str(d["date"].max())[:10]
    except Exception:
        try:
            return json.load(open(META, encoding="utf-8")).get("data_date") or ""
        except Exception:
            return ""


def _busday_lag(d0, d1):
    """d0 → d1 的工作日间隔（d1 更晚为正）。节假日不剔除，仅作「落后几天」的量级判断。"""
    if not d0 or not d1:
        return None
    try:
        a = datetime.date.fromisoformat(d0[:10])
        b = datetime.date.fromisoformat(d1[:10])
        return int(__import__("numpy").busday_count(a, b))
    except Exception:
        return None


def refresh(verbose=True):
    """抓一次并落盘，返回 meta。任何一步失败都不抛，尽量保住缓存。"""
    os.makedirs(HF, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    sig_ok = cat_ok = False
    d = cat = None

    try:
        j = json.loads(_get(GITEE_API).decode("utf-8"))
        raw = base64.b64decode(j["content"]).decode("utf-8")
        d = json.loads(raw)
        if not isinstance(d, dict) or not d:
            raise ValueError("signals 为空")
        json.dump(d, open(SIG_CACHE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        sig_ok = True
    except Exception as e:
        if verbose:
            print("      [恒方] 信号抓取失败：%r（用缓存）" % (e,))
        try:
            d = json.load(open(SIG_CACHE, encoding="utf-8"))
        except Exception:
            d = None

    try:
        cat = json.loads(_get(CAT_URL).decode("utf-8"))
        if not isinstance(cat, list) or len(cat) < 10:
            raise ValueError("catalog 条目不足：%r" % (len(cat) if cat else 0))
        json.dump(cat, open(CAT_CACHE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        cat_ok = True
    except Exception as e:
        if verbose:
            print("      [恒方] 目录抓取失败：%r（用缓存）" % (e,))
        try:
            cat = json.load(open(CAT_CACHE, encoding="utf-8-sig"))
        except Exception:
            cat = []

    # ---------- 信号日 / 生成时间 ----------
    tds, gens, keys = [], [], []
    for k, v in (d or {}).items():
        pl = (v or {}).get("payload") or (v if isinstance(v, dict) else {})
        if pl.get("trade_date"):
            tds.append(str(pl["trade_date"])[:10])
        if pl.get("generated_at"):
            gens.append(str(pl["generated_at"])[:16])
        keys.append(k)
    sig_date = max(tds) if tds else ""
    gen = max(gens) if gens else ""

    # ---------- 11 个产品里，有几个能在 signals.json 里对上 ----------
    sig_keys = set()
    for x in (cat or []):
        sk = str(x.get("sig_key") or "")
        if sk and sk in (d or {}):
            sig_keys.add(sk)
            continue
        # 老目录没有 sig_key：退回前缀匹配（与 hub_build 同一规则）
        p = str(x.get("prefix") or "")
        p = p[3:] if p.startswith("dt_") else p
        for k in (d or {}):
            if k.startswith(p[:18]) or p.startswith(k[:18]):
                sig_keys.add(k)
                break

    # ---------- 历史轨迹：平台只发「最新一版」，不存档。
    # 我们自己按信号日留档，才能回答「今天和上一个信号日比，谁换仓了」。
    try:
        hist = json.load(open(HIST, encoding="utf-8")) if os.path.exists(HIST) else {}
        items = {}
        for k, v in (d or {}).items():
            pl = (v or {}).get("payload") or (v if isinstance(v, dict) else {})
            effs, acts = [], []
            for cal in pl.get("calibers") or []:
                act = str(cal.get("action") or "")
                eff = "空仓" if ("空仓" in act or "现金" in act) else str(cal.get("target_code") or "")
                effs.append(eff)
                acts.append(act[:24])
            if effs:
                items[k] = {"t": effs, "a": acts}
        if sig_date and items:
            hist[sig_date] = {"items": items, "gen": gen}
            for old in sorted(hist)[:-90]:
                hist.pop(old, None)
            json.dump(hist, open(HIST, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
    except Exception as e:
        if verbose:
            print("      [恒方] 历史轨迹写入失败：%r" % (e,))

    data_date = _data_date()
    meta = {
        "fetched_at": now,
        "signal_date": sig_date,
        "generated_at": gen,
        "data_date": data_date,
        "lag_td": _busday_lag(sig_date, data_date),
        "n_keys": len(keys),
        "n_products": len(cat or []),
        "n_sig_products": len(sig_keys),
        "sig_ok": sig_ok,
        "cat_ok": cat_ok,
        "source": ("实时" if sig_ok else "缓存") + "/" + ("实时" if cat_ok else "缓存"),
    }
    json.dump(meta, open(META, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if verbose:
        print("      [恒方] 信号 %d 键 · 产品 %d 个（有信号 %d）· 信号日 %s · 生成 %s · 落后本地 %s 个交易日 · %s"
              % (meta["n_keys"], meta["n_products"], meta["n_sig_products"],
                 sig_date or "—", gen or "—",
                 "—" if meta["lag_td"] is None else meta["lag_td"],
                 meta["source"]))
    return meta


def load():
    """读缓存（不联网）。返回 (signals, catalog, meta)。"""
    def _j(p, enc="utf-8"):
        try:
            return json.load(open(p, encoding=enc))
        except Exception:
            return None
    meta = _j(META) or {}
    return (_j(SIG_CACHE) or {}, _j(CAT_CACHE, "utf-8-sig") or [], meta)


if __name__ == "__main__":
    m = refresh()
    print(json.dumps(m, ensure_ascii=False, indent=1))
