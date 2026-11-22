# -*- coding: utf-8 -*-
"""诊断交易日历源：SH000001 / 510300 / 159967 各自能否取到日线"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tdx_api

for code in ("SH000001", "510300", "159967", "000001"):
    try:
        df = tdx_api.get_daily_kline(code, count=20)
        if df is None or len(df) == 0:
            print("%-10s 空" % code)
            continue
        print("%-10s 行数 %-4d 首 %s  末 %s  末收 %.4f"
              % (code, len(df), df["date"].iloc[0], df["date"].iloc[-1],
                 float(df["close"].iloc[-1])))
    except Exception as e:
        print("%-10s 异常 %s: %s" % (code, type(e).__name__, str(e)[:80]))
