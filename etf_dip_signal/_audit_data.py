# -*- coding: utf-8 -*-
"""
_audit_data.py —— 数据源交叉验证（2026-11-22 复盘）

要回答三个问题：
  Q1 本地 parquet 的价格，与 tushare 官方日线是否一致？（收益率层面）
  Q2 若不一致，是「复权缩放」（收益率仍对）还是「真的错了」？
  Q3 我们三个池子（381 / 12 / 20）里的标的，有没有受 close<=0 污染？
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

DATA = os.path.join(BASE, "data", "all_etf_1119.parquet")
POOL = os.path.join(BASE, "data", "fixed_pool.json")

TOKEN = "405585c460d0d7d686644d58e138ea06d34915cee14e9c8914e5ea64"
URL = "https://fast.xiaodefa.cn"

SAMPLE = ["518880", "513100", "159915", "510300", "515880",
          "159552", "515020", "513030", "159985", "162719"]

lines = []
def say(s=""):
    lines.append(str(s))
    print(s)


def ts_code(c):
    """ETF 代码 → tushare 后缀：5/6 开头沪市，1/3 开头深市"""
    return c + (".SH" if c[0] in ("5", "6") else ".SZ")


def main():
    import tushare as ts
    pro = ts.pro_api()
    pro._DataApi__http_url = URL
    ts.set_token(TOKEN)

    df = pd.read_parquet(DATA)
    df["code"] = df["code"].astype(str)
    df["date"] = df["date"].astype(str).str[:10]

    say("=" * 104)
    say("Q1/Q2 本地 vs tushare 官方日线（不复权）—— 价格比值 & 收益率偏差")
    say("=" * 104)
    say("  %-8s %-6s %7s %10s %10s %11s %10s %9s" %
        ("代码", "行数", "重叠", "比值中位", "比值std", "收益相关", "收益偏差", "结论"))
    say("  " + "-" * 92)

    out = {}
    for c in SAMPLE:
        try:
            t = pro.fund_daily(ts_code=ts_code(c), start_date="20150101", end_date="20261119")
        except Exception as e:
            say("  %-8s 拉取失败 %r" % (c, e))
            continue
        if t is None or not len(t):
            say("  %-8s tushare 无数据" % c)
            continue
        t = t.copy()
        t["trade_date"] = pd.to_datetime(t["trade_date"]).dt.strftime("%Y-%m-%d")
        t = t.sort_values("trade_date").set_index("trade_date")
        t["close"] = pd.to_numeric(t["close"], errors="coerce")

        s = df[df.code == c].set_index("date")["close"].astype(float)
        idx = s.index.intersection(t.index)
        if len(idx) < 100:
            say("  %-8s 重叠仅 %d 天" % (c, len(idx)))
            continue

        ratio = (s.reindex(idx) / t["close"].reindex(idx)).replace([np.inf, -np.inf], np.nan).dropna()
        r_local = s.reindex(idx).pct_change().dropna()
        r_ts = t["close"].reindex(idx).pct_change().dropna()
        both = pd.concat([r_local, r_ts], axis=1).dropna()
        if len(both) < 50:
            continue
        corr = both.iloc[:, 0].corr(both.iloc[:, 1])
        diff = (both.iloc[:, 0] - both.iloc[:, 1]).abs()

        # 判定：比值恒定 ⇒ 仅复权缩放；比值跳变 ⇒ 复权因子分段（前复权的正常现象）
        rstd = ratio.std()
        if rstd < 1e-6:
            verdict = "仅缩放"
        elif corr > 0.999:
            verdict = "分段复权"
        else:
            verdict = "⚠️不一致"

        say("  %-8s %-6d %7d %10.4f %10.2e %11.5f %9.4f%% %9s"
            % (c, len(s), len(idx), ratio.median(), rstd, corr,
               diff.median() * 100, verdict))
        out[c] = {"ratio_median": float(ratio.median()), "ratio_std": float(rstd),
                  "ret_corr": float(corr), "ret_diff_med": float(diff.median()),
                  "n": int(len(idx))}

    say()
    say("  判定标准：收益相关系数 > 0.999 且 日收益偏差中位 < 0.05pp ⇒ 可用于回测")
    say("  比值 std 大不是问题：前复权会把历史价按分红/拆分分段缩放，")
    say("  只要「日收益率」一致，回测的复利结果就一致。")

    say()
    say("=" * 104)
    say("Q3 三个池子的标的，是否受 close<=0 污染")
    say("=" * 104)
    bad = set(df.loc[df["close"] <= 0, "code"].unique())
    say("  全库 close<=0 的标的：%d 只（清一色 16xxxx LOF，长期无报价）" % len(bad))

    d = json.load(open(POOL, encoding="utf-8"))
    p381 = [str(x) for x in d["codes"]]
    p12 = ["518880", "159509", "588000", "501225", "513100", "513310",
           "159915", "162719", "159985", "513030", "513290", "513520"]
    hit381 = [c for c in p381 if c in bad]
    hit12 = [c for c in p12 if c in bad]
    say("  381 池：%d 只，其中 close<=0 的 %d 只 %s" % (len(p381), len(hit381), hit381 or ""))
    say("  12 池 ：%d 只，其中 close<=0 的 %d 只 %s" % (len(p12), len(hit12), hit12 or ""))

    # 池内标的的「当日缺数据」比例（NaN 在原始 parquet 里不存在，但要查是否整段缺失）
    say()
    say("  池内标的的数据缺口（2015-01-05 ~ 2026-11-19 应有 2886 个交易日）：")
    cnt = df.groupby("code")["date"].nunique()
    for c in ["515880", "159552", "515020"]:
        if c in cnt.index:
            say("    %s  %d / 2886 天（%.0f%%）" % (c, cnt[c], cnt[c] / 2886 * 100))

    say()
    say("=" * 104)
    say("结论汇总")
    say("=" * 104)
    ok = [c for c, v in out.items() if v["ret_corr"] > 0.999 and v["ret_diff_med"] < 0.0005]
    say("  收益率一致的标的：%d / %d 只 %s" % (len(ok), len(out), ok))
    badret = [c for c, v in out.items() if not (v["ret_corr"] > 0.999 and v["ret_diff_med"] < 0.0005)]
    if badret:
        say("  ⚠️ 需要复核：%s" % badret)
    else:
        say("  ✅ 抽样标的的日收益率全部与 tushare 一致（>0.999）⇒ 本地数据可用于回测")

    json.dump(out, open(os.path.join(BASE, "_audit_data.json"), "w"), ensure_ascii=False, indent=1)
    open(os.path.join(BASE, "_audit_data.log"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n[已保存] _audit_data.log")


if __name__ == "__main__":
    main()
