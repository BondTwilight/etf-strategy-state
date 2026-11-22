# -*- coding: utf-8 -*-
"""可行性探针：复刻「资金面 + 情绪面 → 市场状态」所需的数据到底有没有

天基营自述：多空模型 = 资金面与情绪面数据 + 聚类算法识别市场状态 → 做多/空仓。
要判断"能不能复刻"，先要看这些原料能否拿到、历史够不够长。
"""
import tushare as ts
import pandas as pd

ts.set_token("405585c460d0d7d686644d58e138ea06d34915cee14e9c8914e5ea64")
pro = ts.pro_api()
pro._DataApi__http_url = "https://fast.xiaodefa.cn"

START, END = "20170101", "20261020"


def probe(name, fn, note=""):
    try:
        df = fn()
    except Exception as e:
        print("  %-22s ❌ %s: %s" % (name, type(e).__name__, str(e)[:70]))
        return None
    if df is None or len(df) == 0:
        print("  %-22s ❌ 返回空 %s" % (name, note))
        return None
    cols = ",".join(list(df.columns)[:9])
    rng = ""
    for c in ("trade_date", "cal_date", "end_date"):
        if c in df.columns:
            d = sorted(df[c].astype(str))
            rng = " %s~%s" % (d[0], d[-1])
            break
    print("  %-22s ✅ %6d 行%s  | %s" % (name, len(df), rng, cols))
    return df


print("=" * 100)
print("A. 标的行情（天基营标的是中证1000）")
print("=" * 100)
probe("index_daily 000852", lambda: pro.index_daily(ts_code="000852.SH",
                                                    start_date=START, end_date=END))
probe("index_daily 000300", lambda: pro.index_daily(ts_code="000300.SH",
                                                    start_date=START, end_date=END))

print("\n" + "=" * 100)
print("B. 资金面（天基营说的『资金流出/共振』）")
print("=" * 100)
probe("moneyflow_mkt_dc 大盘资金流", lambda: pro.moneyflow_mkt_dc(start_date=START,
                                                                  end_date=END))
probe("moneyflow_ind_dc 行业资金流", lambda: pro.moneyflow_ind_dc(start_date="20260901",
                                                                  end_date=END), "(仅取近月，量大)")
probe("moneyflow_hsgt 沪深港通", lambda: pro.moneyflow_hsgt(start_date=START,
                                                            end_date=END))
probe("margin 融资融券汇总", lambda: pro.margin(start_date=START, end_date=END))
probe("margin_detail 两融明细", lambda: pro.margin_detail(trade_date="20261020"))

print("\n" + "=" * 100)
print("C. 情绪面（涨跌、成交、换手、涨跌停）")
print("=" * 100)
probe("index_dailybasic 指标", lambda: pro.index_dailybasic(ts_code="000852.SH",
                                                            start_date=START, end_date=END))
probe("daily 全市场单日", lambda: pro.daily(trade_date="20261020"))
probe("limit_list_d 涨跌停", lambda: pro.limit_list_d(trade_date="20261020"))
probe("stk_limit 涨跌停价", lambda: pro.stk_limit(trade_date="20261020"))

print("\n" + "=" * 100)
print("D. 广度类（市场宽度，情绪面的常用代理）")
print("=" * 100)
d = probe("daily 连续区间(取样)", lambda: pro.daily(start_date="20260901",
                                                     end_date="20260930"))
if d is not None:
    print("       单月行数 %d ⇒ 全市场单日约 %d 只，2017 至今约 %.0f 万行"
          % (len(d), len(d) / 20, len(d) / 20 * 240 * 10 / 10000))
