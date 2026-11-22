# -*- coding: utf-8 -*-
import io
s = io.open("live_template.html", encoding="utf-8").read()
for k in ["function mergeTail", "function allTail", "function rowsToTail"]:
    i = s.find(k)
    print("###", k, i)
    print(s[i:i + 620])
    print()
