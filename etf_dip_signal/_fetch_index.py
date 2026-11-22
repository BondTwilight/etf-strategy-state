# -*- coding: utf-8 -*-
"""拉取中证1000（天基营标的是中证1000）日线与指标，落地缓存。
天基营的回测基准就是中证1000，所以用它的状态做代理是最贴近的检验。
"""
import os
import tushare as ts
import pandas as pd

ts.set_token("405585c460d0d7d686644d58e138ea06d34915cee14e9c8914e5ea64")
pro = ts.pro_api()
pro._DataApi__http_url = "https://fast.xiaodefa.cn"

OUT = os.path.join("data", "index_000852.parquet")
S, E = "20160101", "20261020"

d = pro.index_daily(ts_code="000852.SH", start_date=S, end_date=E)
b = pro.index_dailybasic(ts_code="000852.SH", start_date=S, end_date=E)
print("index_daily %d 行 ｜ index_dailybasic %d 行" % (len(d), len(b)))

d = d.sort_values("trade_date").reset_index(drop=True)
b = b[["trade_date", "turnover_rate", "turnover_rate_f", "pe", "pb"]].copy()
m = d.merge(b, on="trade_date", how="left").sort_values("trade_date").reset_index(drop=True)
m = m.rename(columns={"trade_date": "date"})
m["date"] = m["date"].astype(str)
m = m[["date", "close", "open", "high", "low", "vol", "amount",
       "turnover_rate", "pe", "pb"]]
m.to_parquet(OUT, index=False)
print("已保存 -> %s  %d 行  %s ~ %s" % (OUT, len(m), m.date.iloc[0], m.date.iloc[-1]))
print(m.tail(3).to_string(index=False))
