# -*- coding: utf-8 -*-
import json

d = json.load(open("data/position_snapshots.json", encoding="utf-8"))
print("快照日期：", sorted(d.keys()))
for k in sorted(d.keys()):
    v = d[k]
    if v:
        c = list(v)[0]
        print("  %s  %s  现价 %s  浮盈 %s" % (k, c, v[c].get("last_price"),
                                            v[c].get("pnl_pct")))
    else:
        print("  %s  空仓" % k)
