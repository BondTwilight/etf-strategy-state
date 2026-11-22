# -*- coding: utf-8 -*-
"""校验 market_state 复算结果 vs 次方页面"""
import cf_api
import market_state as ms

d = cf_api.hist("510300", "2025-06-01", "2026-11-22", "none")
r = ms.detect(d["510300"])
i, s = r["ind"], r["score"]

print("date", i["date"], "close", i["close"])
print("MA5 {:.4f} MA10 {:.4f} MA20 {:.4f} MA60 {:.4f}".format(
    i["MA5"], i["MA10"], i["MA20"], i["MA60"]))
print("DIF {:.4f} DEA {:.4f} RSI {:.2f} ATR {:.4f} BW {:.4f}".format(
    i["DIF"], i["DEA"], i["RSI"], i["ATR"], i["BOLL_bw"]))
print("vol5 {:.2f} vol20 {:.2f} ratio {:.3f} ret5 {:+.2f}".format(
    i["vol5"], i["vol20"], i["vol_ratio"], i["ret5"]))
print()
for x in s["dims"]:
    print("  {:<4} {:>3}%  {:>6.1f}  {:<22} {}".format(
        x["k"], x["w"], x["v"], x["label"], x["detail"]))
print()
print("综合 {}  状态 {}  置信 {}%  ({})".format(s["total"], s["state"], s["conf"], s["conf_note"]))
print("次方页面: -31.5 熊市 31%")
print("chart bars:", len(ms.chart_series(d["510300"])))
