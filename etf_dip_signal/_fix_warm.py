# -*- coding: utf-8 -*-
"""只重建 warm 段（2017-06-01~2017-12-31）——修正列错位后重跑"""
import os
import time as _t

import pandas as pd

import cf_api

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
COLS = ["date", "open", "close", "high", "low", "chg", "vol", "iopv"]

MOMO = ["518880", "159509", "588000", "501225", "513100", "513310",
        "159915", "162719", "159985", "513030", "513290", "513520"]
BAND = ["162411", "513100", "161128", "588000", "162415", "515450"]
BANK = ["159552", "515020"]
BENCH = ["510300", "515880", "511880"]
CODES = sorted(set(MOMO + BAND + BANK + BENCH))

for hh in ("14:30", "14:45", "14:50"):
    tag = hh.replace(":", "")
    d = cf_api.get("/fund/hist_intraday", symbol=",".join(CODES),
                   start_date="2017-06-01", end_date="2017-12-31",
                   time=hh, adjust="qfq")
    rows = []
    for code, rr in (d or {}).items():
        for x in rr:
            rows.append([x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7], str(code)])
    df = pd.DataFrame(rows, columns=COLS + ["code"])
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "close", "high", "low", "chg", "vol", "iopv"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.drop_duplicates(["date", "code"]).sort_values(["date", "code"])
    df.to_parquet(os.path.join(DATA, "intraday_%s_warm.parquet" % tag), index=False)
    print("%s warm: %d 行 × %d 只  %s ~ %s  code 示例 %s"
          % (hh, len(df), df["code"].nunique(),
             df["date"].min().date(), df["date"].max().date(),
             df["code"].iloc[0]))
    _t.sleep(1.1)

# 复核
import importlib
import _px
importlib.reload(_px)
for r in _px.describe()["intraday"]:
    print(r)
