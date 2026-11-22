# -*- coding: utf-8 -*-
"""为 381 池建 14:45 分时 OHLC 库（线C 真实执行时点）

线C 线上 14:40 启动、14:49 出邮件、14:45—14:55 下单 ⇒ 执行价 ≈ 14:45 分时价。
库里 close 是「截至 14:45 的收盘」，high/low 也是截至 14:45 的极值 —— 比用全天
高低点更贴近真实可观测信息（回测里用全天最低点会偷到未来）。

输出：data/all_etf_1445.parquet（schema 同 all_etf_1120：code/date/open/high/low/close/volume）
"""
import datetime
import json
import os
import time as _t

import pandas as pd

import _p4_band as pb
import cf_api

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
TIME = "14:45"
START = "2019-01-01"
# 和 _build_px / _build_intraday 同一个坑：END 写死就永远是那一天。
END = os.environ.get("PX_END") or datetime.date.today().strftime("%Y-%m-%d")
OUT = os.path.join(DATA, "all_etf_1445.parquet")
PROG = os.path.join(DATA, "_pool1445_progress.json")

COLS = ["date", "open", "close", "high", "low", "chg", "vol", "iopv"]


def chunks(start, end, days=360):
    a, b = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)
    out = []
    while a <= b:
        c = min(a + datetime.timedelta(days=days - 1), b)
        out.append((a.isoformat(), c.isoformat()))
        a = c + datetime.timedelta(days=1)
    return out


def main():
    codes, _ = pb.load_pool_codes()
    extra = ["510300", "159915", "510880", "515880", "511880", "512800",
             "515020", "159552", "159100"]
    codes = sorted(set(map(str, codes)) | set(extra))
    print("池 %d 只，时点 %s，%s ~ %s" % (len(codes), TIME, START, END))

    rng = chunks(START, END)
    done = {}
    if os.path.exists(PROG):
        done = json.load(open(PROG, encoding="utf-8"))
    # 🔴 进度文件说「都做过了」但历史库不在（换机器 / 缓存没命中）⇒ 进度作废重来。
    #    否则会一段都不抓，最后 SystemExit，CI 上表现为「一直退回收盘价」。
    if done and not os.path.exists(OUT):
        print("   ! 有进度文件但没有历史库，进度作废，重新全量")
        done = {}
    frames = []
    for ci, (s, e) in enumerate(rng, 1):
        key = "%s_%s" % (s, e)
        for bi in range(0, len(codes), 50):
            batch = codes[bi:bi + 50]
            k = key + "_" + str(bi)
            if k in done:
                continue
            try:
                d = cf_api.get("/fund/hist_intraday", symbol=",".join(batch),
                               start_date=s, end_date=e, time=TIME, adjust="qfq")
            except Exception as ex:
                print("   ! %s %s 失败 %r" % (key, bi, ex))
                _t.sleep(5)
                continue
            n = 0
            for code, rows in (d or {}).items():
                if not rows:
                    continue
                df = pd.DataFrame(rows, columns=COLS)
                df["code"] = str(code)
                frames.append(df)
                n += 1
            done[k] = n
            _t.sleep(1.05)
        print("   [%2d/%d] %s~%s 完成，累计 %d 段" % (ci, len(rng), s, e, len(frames)))
        with open(PROG, "w", encoding="utf-8") as f:
            json.dump(done, f)
        # 分段落盘，防中断全丢
        if frames and ci % 4 == 0:
            pd.concat(frames, ignore_index=True).to_parquet(
                OUT + ".part", index=False)

    if not frames:
        # 增量：上次的 parquet 已经覆盖了老区间，这次没新段就直接用它
        if os.path.exists(OUT):
            df = pd.read_parquet(OUT)
        elif os.path.exists(OUT + ".part"):
            df = pd.read_parquet(OUT + ".part")
        else:
            raise SystemExit("没有新增段，也没有历史库：%s" % OUT)
    else:
        frames = [pd.concat(frames, ignore_index=True)]
        if os.path.exists(OUT):
            # 老库打底，新抓的段覆盖同名日期（keep="last"）——
            # 前复权基准会随分红变化，能让新数据赢的地方就别让旧的赢。
            frames.insert(0, pd.read_parquet(OUT))
        df = pd.concat(frames, ignore_index=True)

    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "close", "high", "low", "chg", "vol", "iopv"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # keep="last"：后面 concat 进来的是本次新抓的段，同日以新为准
    df = df.drop_duplicates(["date", "code"], keep="last").sort_values(["code", "date"])

    # 统一成 all_etf_1120 的 schema
    out = df.rename(columns={"vol": "volume"})[
        ["code", "date", "open", "high", "low", "close", "volume"]]
    out.to_parquet(OUT, index=False)
    print("\n→ %s  %d 行 × %d 只  %s ~ %s"
          % (os.path.basename(OUT), len(out), out["code"].nunique(),
             out["date"].min().date(), out["date"].max().date()))
    miss = [c for c in codes if c not in set(out["code"])]
    print("   未返回（多为未上市）：%d 只" % len(miss))
    if os.path.exists(OUT + ".part"):
        os.remove(OUT + ".part")


if __name__ == "__main__":
    main()
