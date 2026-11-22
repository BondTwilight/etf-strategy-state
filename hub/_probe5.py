# -*- coding: utf-8 -*-
import io
s = io.open("_build_live.py", encoding="utf-8").read()
i = s.find('"cloud": C')
print("idx", i)
print(s[i - 200:i + 700])
