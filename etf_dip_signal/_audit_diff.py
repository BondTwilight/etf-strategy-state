# -*- coding: utf-8 -*-
"""输出 6 个被修改文件的逐行 diff（unified）。"""
import difflib, os

ZIP_DIR = r"E:\workbuddy1.0\量化agent\_zip_verify\ETF抄底信号_分发包"
DEPLOY  = r"E:\workbuddy1.0\量化agent\etf_dip_signal"

TARGETS = ["config.py", "indicators.py", "signal_alert.py", "web_quote.py",
           "data/positions.json", "data/position_snapshots.json"]


def read(p):
    with open(p, "rb") as f:
        b = f.read()
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return b.decode(enc).splitlines(keepends=False)
        except UnicodeDecodeError:
            continue
    return []


total_add = total_del = 0
out = []
for rel in TARGETS:
    a = read(os.path.join(ZIP_DIR, rel))
    b = read(os.path.join(DEPLOY, rel))
    d = list(difflib.unified_diff(a, b, fromfile=f"ZIP/{rel}",
                                  tofile=f"DEPLOY/{rel}", lineterm="", n=2))
    adds = sum(1 for x in d if x.startswith("+") and not x.startswith("+++"))
    dels = sum(1 for x in d if x.startswith("-") and not x.startswith("---"))
    total_add += adds
    total_del += dels
    out.append(f"\n{'='*76}\n### {rel}   +{adds} 行 / -{dels} 行\n{'='*76}")
    out.extend(d)

txt = "\n".join(out)
print(txt)
print(f"\n\n合计：新增 {total_add} 行，删除 {total_del} 行")
with open(os.path.join(DEPLOY, "_provenance_diff.txt"), "w", encoding="utf-8") as f:
    f.write(txt + f"\n\n合计：新增 {total_add} 行，删除 {total_del} 行\n")
