# -*- coding: utf-8 -*-
import io
s = io.open("live_template.html", encoding="utf-8").read()
for k in ["口径：本地统一账本", "降采样到"]:
    i = s.find(k)
    print("###", k, i)
    if i > 0:
        print(s[max(0, i - 360):i + 200])
