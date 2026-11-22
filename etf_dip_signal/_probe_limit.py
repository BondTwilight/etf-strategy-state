# -*- coding: utf-8 -*-
"""限流下数据完整性探测：取 8 只 ETF 日线，统计腾讯/新浪各自成功数与耗时。"""
import os, sys, time
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import web_quote

codes = ["159967", "588020", "513310", "159259", "515880", "159667", "510300", "159915"]
ok_t = ok_s = 0
t0 = time.time()
for c in codes:
    tc = web_quote.norm_code(c)
    t = time.time()
    ten = web_quote._kline_tencent(c, 60)
    sina = None
    if ten.empty:
        sina = web_quote._kline_sina(c, 60)
    dt = time.time() - t
    ok_t += 0 if ten.empty else 1
    ok_s += 0 if (sina is None or sina.empty) else 1
    print("%s tencent=%-5s sina=%-5s %.2fs" % (
        c, "OK" if not ten.empty else "FAIL",
        ("OK" if not sina.empty else "FAIL") if sina is not None else "-", dt))
print("\n腾讯成功 %d/%d，新浪兜底成功 %d 只，总耗时 %.1fs" % (ok_t, len(codes), ok_s, time.time() - t0))
