# -*- coding: utf-8 -*-
import io
s = io.open("live_template.html", encoding="utf-8").read()
key = "距止损"
start = 0
n = 0
while True:
    i = s.find(key, start)
    if i < 0:
        break
    n += 1
    seg = s[max(0, i - 700):i + 300]
    print("=== #%d at %d ===" % (n, i))
    print(seg.replace("\n", " ⏎ ")[:1100])
    start = i + 1
print("total", n)
