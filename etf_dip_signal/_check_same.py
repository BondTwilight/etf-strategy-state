# -*- coding: utf-8 -*-
"""核对：生成的 A 文件 与原版 v44 是否只有 docstring / EXEC_TIME 差异"""
import ast

FILES = {
    "原版 v44": "../deliverables/jq_etf_dip_v44.py",
    "A(14:50)": "../deliverables/jq_etf_dip_v44_A_1450.py",
    "B(14:57)": "../deliverables/jq_etf_dip_v44_B_1457.py",
    "C(14:45)": "../deliverables/jq_etf_dip_v44_C_1445.py",
}


def norm(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    body = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "EXEC_TIME" for t in node.targets):
            node.value = ast.Constant(value="<EXEC>")
        body.append(node)
    tree.body = body
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


sig = {k: norm(v) for k, v in FILES.items()}
base = sig["原版 v44"]
print("以原版 v44 为基准，逐份比对（已抹掉 docstring 与 EXEC_TIME 的值）：")
for k, v in sig.items():
    print("  %-10s 长度 %6d  与基准一致: %s" % (k, len(v), v == base))

# 再逐字节看一下 EXEC_TIME 行
print("\n各文件 EXEC_TIME 实际值：")
for k, p in FILES.items():
    for l in open(p, encoding="utf-8"):
        if l.startswith("EXEC_TIME"):
            print("  %-10s %s" % (k, l.strip()[:60]))
            break
