# -*- coding: utf-8 -*-
"""用 AST 严格证明：A/B 除 EXEC_TIME 值外，代码结构完全一致"""
import ast

A = "../deliverables/jq_etf_dip_v44_A_1450.py"
B = "../deliverables/jq_etf_dip_v44_B_1457.py"


def norm(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    body = []
    for node in tree.body:
        # 去掉模块 docstring
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            continue
        # EXEC_TIME 统一成占位符
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "EXEC_TIME" for t in node.targets):
            node.value = ast.Constant(value="<EXEC_TIME>")
        body.append(node)
    tree.body = body
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


da, db = norm(A), norm(B)
print("A 归一化 AST 长度 %d" % len(da))
print("B 归一化 AST 长度 %d" % len(db))
print("除 EXEC_TIME 外代码结构完全一致：", da == db)

if da != db:
    n = min(len(da), len(db))
    for i in range(n):
        if da[i] != db[i]:
            print("首个差异位置 %d：" % i)
            print("  A:", da[max(0, i - 60):i + 60])
            print("  B:", db[max(0, i - 60):i + 60])
            break
