# -*- coding: utf-8 -*-
"""源文件溯源审计：压缩包原始内容 vs 部署目录，逐字节比对。"""
import hashlib, os, sys, json

ZIP_DIR = r"E:\workbuddy1.0\量化agent\_zip_verify\ETF抄底信号_分发包"
DEPLOY  = r"E:\workbuddy1.0\量化agent\etf_dip_signal"


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def walk(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in ("__pycache__", "回测输出", "data_cache")]
        for n in fn:
            if n.endswith(".pyc"):
                continue
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, root).replace("\\", "/")
            out[rel] = p
    return out


src = walk(ZIP_DIR)
dst = walk(DEPLOY)

rows = []
for rel, p in sorted(src.items()):
    if rel not in dst:
        rows.append((rel, "缺失", md5(p)[:8], "-", os.path.getsize(p), 0))
        continue
    h1, h2 = md5(p), md5(dst[rel])
    s1, s2 = os.path.getsize(p), os.path.getsize(dst[rel])
    if h1 == h2:
        rows.append((rel, "原样", h1[:8], h2[:8], s1, s2))
    else:
        rows.append((rel, "已修改", h1[:8], h2[:8], s1, s2))

extra = [r for r in sorted(dst) if r not in src]

print("=" * 78)
print("A. 压缩包内文件 → 部署目录 逐字节比对")
print("=" * 78)
print(f"{'文件':<34}{'状态':<8}{'源MD5':<11}{'部署MD5':<11}{'源字节':>8}{'部署字节':>9}")
print("-" * 78)
for rel, st, h1, h2, s1, s2 in rows:
    print(f"{rel:<34}{st:<8}{h1:<11}{h2:<11}{s1:>8}{s2:>9}")

print()
print("=" * 78)
print("B. 部署目录独有文件（即本次新增，原包中不存在）")
print("=" * 78)
for r in extra:
    print(f"  + {r:<42}{os.path.getsize(dst[r]):>8} bytes")

n_same = sum(1 for r in rows if r[1] == "原样")
n_mod  = sum(1 for r in rows if r[1] == "已修改")
n_miss = sum(1 for r in rows if r[1] == "缺失")
print()
print(f"汇总：包内 {len(src)} 个文件 → 原样 {n_same} / 已修改 {n_mod} / 缺失 {n_miss}；"
      f"新增 {len(extra)} 个")

# 输出 JSON 供文档引用
rep = {"zip_dir": ZIP_DIR, "rows": rows, "extra": extra,
       "summary": {"in_zip": len(src), "same": n_same, "modified": n_mod,
                   "missing": n_miss, "added": len(extra)}}
with open(os.path.join(DEPLOY, "_provenance.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)
print("\n[OK] 审计结果写入 _provenance.json")
