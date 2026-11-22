# -*- coding: utf-8 -*-
"""建「执行时点价」日频库：hist_intraday（SVIP）

每个交易日截至 HH:MM 的累计 K 线 ⇒ 这一天的「执行价」。
解决的核心口径问题：平台用 14:30/14:50 分时价选股与成交，本地只能用收盘价，
日偏差 |中位| 0.19%、P90 0.62%、最大 1.02%，9 年复利后放大成 12~14pp 的复现误差。

输出：data/intraday_1430.parquet / _1445 / _1450
     列：date, code, open, close, high, low, chg, vol, iopv（close 即该时点价）
"""
import datetime
import json
import os
import time as _t

import pandas as pd

import cf_api

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# momo 12 池 + 96863 6 池 + 96864 两只 + 基准/持仓
MOMO = ["518880", "159509", "588000", "501225", "513100", "513310",
        "159915", "162719", "159985", "513030", "513290", "513520"]
BAND = ["162411", "513100", "161128", "588000", "162415", "515450"]
BANK = ["159552", "515020"]
BENCH = ["510300", "515880", "511880"]
CODES = sorted(set(MOMO + BAND + BANK + BENCH))

TIMES = ["14:30", "14:45", "14:50"]
START = "2018-01-01"
# 以前写死 2026-11-20，和 _build_px 犯过同一个错：链路天天跑、数据日不动。
END = os.environ.get("PX_END") or datetime.date.today().strftime("%Y-%m-%d")

COLS = ["date", "open", "close", "high", "low", "chg", "vol", "iopv"]


def chunks(start, end, days=360):
    a = datetime.date.fromisoformat(start)
    b = datetime.date.fromisoformat(end)
    out = []
    while a <= b:
        c = min(a + datetime.timedelta(days=days - 1), b)
        out.append((a.isoformat(), c.isoformat()))
        a = c + datetime.timedelta(days=1)
    return out


def fetch_time(hhmm):
    rng = chunks(START, END)
    frames = []
    for i, (s, e) in enumerate(rng, 1):
        d = cf_api.get("/fund/hist_intraday", symbol=",".join(CODES),
                       start_date=s, end_date=e, time=hhmm, adjust="qfq")
        got = 0
        for code, rows in (d or {}).items():
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=COLS)
            df["code"] = str(code)
            frames.append(df)
            got += 1
        print("   %-5s [%2d/%d] %s~%s  %d/%d 只" % (hhmm, i, len(rng), s, e, got, len(CODES)))
        _t.sleep(1.1)          # 60 次/分/IP/接口
    if not frames:
        return pd.DataFrame(columns=COLS + ["code"])
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    for c in ("open", "close", "high", "low", "chg", "vol", "iopv"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.drop_duplicates(["date", "code"]).sort_values(["code", "date"])
    return out


def main():
    os.makedirs(DATA, exist_ok=True)
    meta = {}
    for hhmm in TIMES:
        tag = hhmm.replace(":", "")
        path = os.path.join(DATA, "intraday_%s.parquet" % tag)
        print("\n[%s] 拉取 …" % hhmm)
        df = fetch_time(hhmm)
        df.to_parquet(path, index=False)
        cover = df.groupby("code")["date"].agg(["min", "max", "count"])
        meta[hhmm] = {"rows": int(len(df)), "codes": int(df["code"].nunique()),
                      "min": str(df["date"].min().date()), "max": str(df["date"].max().date()),
                      "path": os.path.basename(path)}
        print("   → %s  %d 行 × %d 只  %s ~ %s"
              % (os.path.basename(path), len(df), df["code"].nunique(),
                 df["date"].min().date(), df["date"].max().date()))
        miss = [c for c in CODES if c not in set(df["code"])]
        if miss:
            print("   ⚠️ 缺：", miss)

        # 预热段（momo 从 2018-01-01 起跑，需要 26 日历史）
        print("[%s] 预热段 2017-06-01~2017-12-31 …" % hhmm)
        wd = cf_api.get("/fund/hist_intraday", symbol=",".join(CODES),
                        start_date="2017-06-01", end_date="2017-12-31",
                        time=hhmm, adjust="qfq")
        wrows = []
        for code, rows in (wd or {}).items():
            for x in rows:
                # 列顺序必须与 COLS 完全一致：date, open, close, high, low, chg, vol, iopv
                wrows.append([x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7], str(code)])
        if wrows:
            wdf = pd.DataFrame(wrows, columns=COLS + ["code"])
            wdf["date"] = pd.to_datetime(wdf["date"])
            for c in ("open", "close", "high", "low", "chg", "vol", "iopv"):
                wdf[c] = pd.to_numeric(wdf[c], errors="coerce")
            wdf = wdf.drop_duplicates(["date", "code"]).sort_values(["date", "code"])
            wdf.to_parquet(os.path.join(DATA, "intraday_%s_warm.parquet" % tag),
                           index=False)
            print("   → warm %d 行 × %d 只" % (len(wdf), wdf["code"].nunique()))
        _t.sleep(1.1)
    with open(os.path.join(DATA, "intraday_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("\n完成。", json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
