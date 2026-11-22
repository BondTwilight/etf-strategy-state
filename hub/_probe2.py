# -*- coding: utf-8 -*-
import io
s = io.open("live_core.js", encoding="utf-8").read()
i = s.find("function judge(")
print("idx", i)
print(s[i:i + 1600])
