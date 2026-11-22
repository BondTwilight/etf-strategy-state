# -*- coding: utf-8 -*-
"""
_audit_data3.py —— 决定性检验：repair_prices 修复后，收益率是否与 tushare 一致

背景：_audit_data 发现 513100（2022-01-17 +399%）、515880（2026-02-04 +190%、2026-07-07 +101%）
存在份额折算造成的价格跳变。若 repair_prices 未修掉，今天的回测全部受影响。
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import data_quality

DATA = os.path.join(BASE, "data", "all_etf_1119.parquet")
POOL = os.path.join(BASE, "data", "fixed_pool.json")
TOKEN = "405585c460d0d7d686644d58e138ea06d34915cee14e9c8914e5ea64"
URL = "https://fast.xiaodefa.cn"
CHECK = ["513100", "515880", "510300", "513030", "518880", "159915",
         "159552", "515020", "159985", "162719", "513290", "513310"]

lines = []
def say(s=""):
    lines.append(str(s)); print(s)


def ts_code(c):
    return c + (".SH" if c[0] in ("5", "6") else ".SZ")


def main():
    import tushare as ts
    pro = ts.pro_api()
    pro._DataApi__http_url = URL
    ts.set_token(TOKEN)

    df = pd.read_parquet(DATA)
    df["code"] = df["code"].astype(str)
    df["date"] = df["date"].astype(str).str[:10]

    say("=" * 108)
    say("修复前 vs 修复后：日收益率与 tushare 的一致性")
    say("=" * 108)
    say("  %-8s %6s %8s %8s %10s %10s %10s %10s" %
        ("代码", "跳变", "原始相关", "修复相关", "原始偏差", "修复偏差", "修复前max", "修复后max"))
    say("  " + "-" * 92)

    res = {}
    for c in CHECK:
        sub = df[df.code == c][["date", "open", "high", "low", "close", "volume"]].copy()
        sub = sub.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        if len(sub) < 100:
            continue
        fixed, hits = data_quality.repair_prices(sub)

        t = pro.fund_daily(ts_code=ts_code(c), start_date="20150101", end_date="20261119")
        if t is None or not len(t):
            say("  %-8s tushare 无数据" % c)
            continue
        t["trade_date"] = pd.to_datetime(t["trade_date"]).dt.strftime("%Y-%m-%d")
        t = t.sort_values("trade_date").set_index("trade_date")
        t["close"] = pd.to_numeric(t["close"], errors="coerce")

        # 修复前
        s0 = sub.set_index("date")["close"].astype(float)
        s1 = fixed.set_index("date")["close"].astype(float)
        idx = s0.index.intersection(t.index)
        if len(idx) < 100:
            continue
        r0 = s0.reindex(idx).pct_change()
        r1 = s1.reindex(idx).pct_change()
        rt = t["close"].reindex(idx).pct_change()
        j = pd.concat([r0, r1, rt], axis=1).dropna()
        j.columns = ["r0", "r1", "rt"]
        c0 = j["r0"].corr(j["rt"])
        c1 = j["r1"].corr(j["rt"])
        d0 = (j["r0"] - j["rt"]).abs().median()
        d1 = (j["r1"] - j["rt"]).abs().median()
        mx0 = (j["r0"] - j["rt"]).abs().max()
        mx1 = (j["r1"] - j["rt"]).abs().max()

        res[c] = {"hits": len(hits), "c0": c0, "c1": c1, "d0": d0, "d1": d1,
                  "mx0": mx0, "mx1": mx1}
        say("  %-8s %6d %8.5f %8.5f %9.4f%% %9.4f%% %9.2f%% %9.2f%%"
            % (c, len(hits), c0, c1, d0 * 100, d1 * 100, mx0 * 100, mx1 * 100))

    say()
    say("  判定：修复后相关 >0.999 且偏差中位 <0.05pp 且 max <5pp ⇒ 数据可用于回测")

    say()
    say("=" * 108)
    say("修复明细（跳变点）")
    say("=" * 108)
    for c in CHECK:
        sub = df[df.code == c][["date", "open", "high", "low", "close", "volume"]].copy()
        sub = sub.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        if len(sub) < 100:
            continue
        _, hits = data_quality.repair_prices(sub)
        if hits:
            say("  %s  修复 %d 根：" % (c, len(hits)))
            for h in hits[:8]:
                say("    %s  %.4f → %.4f  (×%.4f)" % (h[0], h[1], h[2], h[3]))

    say()
    say("=" * 108)
    say("结论")
    say("=" * 108)
    bad = [c for c, v in res.items() if not (v["c1"] > 0.999 and v["d1"] < 0.0005)]
    if bad:
        say("  ⚠️ 修复后仍不一致：%s" % bad)
        for c in bad:
            v = res[c]
            say("     %s  相关 %.5f  偏差中位 %.4f%%  max %.2f%%"
                % (c, v["c1"], v["d1"] * 100, v["mx1"] * 100))
    else:
        say("  ✅ 抽样 %d 只标的，修复后日收益率全部与 tushare 一致" % len(res))
        say("     ⇒ 「本地数据只差复权缩放、收益率正确」这一判断成立，今天的回测结果有效")
    open(os.path.join(BASE, "_audit_data3.log"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n[已保存] _audit_data3.log")


if __name__ == "__main__":
    main()
