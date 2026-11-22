# -*- coding: utf-8 -*-
"""_audit_data2.py —— 逐日对比，定位 513100 / 510300 / 515880 / 513030 的不一致来源"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

DATA = os.path.join(BASE, "data", "all_etf_1119.parquet")
TOKEN = "405585c460d0d7d686644d58e138ea06d34915cee14e9c8914e5ea64"
URL = "https://fast.xiaodefa.cn"
TARGETS = ["513100", "510300", "515880", "513030"]

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

    for c in TARGETS:
        say("=" * 104)
        say("标的 %s" % c)
        say("=" * 104)
        t = pro.fund_daily(ts_code=ts_code(c), start_date="20150101", end_date="20261119")
        t["trade_date"] = pd.to_datetime(t["trade_date"]).dt.strftime("%Y-%m-%d")
        t = t.sort_values("trade_date").set_index("trade_date")
        t["close"] = pd.to_numeric(t["close"], errors="coerce")
        s = df[df.code == c].set_index("date")["close"].astype(float)

        idx = s.index.intersection(t.index)
        both = pd.DataFrame({"local": s.reindex(idx), "ts": t["close"].reindex(idx)})
        both["ratio"] = both["local"] / both["ts"]
        both["rl"] = both["local"].pct_change()
        both["rt"] = both["ts"].pct_change()
        both["d"] = (both["rl"] - both["rt"]).abs()

        say("  重叠 %d 天｜比值：min %.4f  p25 %.4f  中位 %.4f  p75 %.4f  max %.4f"
            % (len(both), both["ratio"].min(), both["ratio"].quantile(.25),
               both["ratio"].median(), both["ratio"].quantile(.75), both["ratio"].max()))
        say("  日收益偏差：中位 %.4f%%  p95 %.4f%%  max %.4f%%"
            % (both["d"].median() * 100, both["d"].quantile(.95) * 100, both["d"].max() * 100))

        # 比值突变点（判断份额折算 / 复权分段）
        ch = both["ratio"].pct_change().abs()
        jumps = ch[ch > 0.15].dropna()
        say("  比值单日变动 >15%% 的天数：%d" % len(jumps))
        for d, v in jumps.head(12).items():
            say("    %s  比值变动 %+.1f%%   local %.4f → ts %.4f"
                % (d, v * 100 * np.sign(both.loc[d, "ratio"] - both["ratio"].shift().loc[d]),
                   both.loc[d, "local"], both.loc[d, "ts"]))

        # 收益偏差最大的 8 天
        say("  日收益偏差最大的 8 天：")
        top = both.nlargest(8, "d")
        for d, r in top.iterrows():
            say("    %s  local %+8.3f%%  ts %+8.3f%%  差 %6.3fpp  (local %.4f / ts %.4f)"
                % (d, r["rl"] * 100, r["rt"] * 100, r["d"] * 100, r["local"], r["ts"]))

        # 分期相关性
        say("  分期收益率相关：")
        for a, b in [("2015", "2017"), ("2018", "2020"), ("2021", "2023"), ("2024", "2026")]:
            seg = both.loc[a:b]
            if len(seg) < 60:
                continue
            cc = seg["rl"].corr(seg["rt"])
            say("    %s~%s  n=%4d  相关 %.5f  比值中位 %.4f"
                % (a, b, len(seg), cc, seg["ratio"].median()))
        say()

    open(os.path.join(BASE, "_audit_data2.log"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n[已保存] _audit_data2.log")


if __name__ == "__main__":
    main()
