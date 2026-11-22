# -*- coding: utf-8 -*-
import io
s = io.open("live_template.html", encoding="utf-8").read()
for k in ["function paint(", "function paintAlerts(", "function bindCards("]:
    i = s.find(k)
    print("###", k, i)
    print(s[i:i + 700])
    print()
